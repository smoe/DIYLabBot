'use strict';

// This is a local detour around one cross-corridor room-door leaf, not a router.
// Native vertex positions are metres; route points and evidence are millimetres.
const {createCameraCollider,createPicker,jointMatrix}=require('../scripts/walkthrough_interaction.js');

const dot=(a,b)=>a.reduce((sum,value,axis)=>sum+value*b[axis],0);
const minus=(a,b)=>a.map((value,axis)=>value-b[axis]);
const multiply=(a,b)=>Array.from({length:16},(_,i)=>[0,1,2,3].reduce((sum,k)=>sum+a[k*4+i%4]*b[Math.floor(i/4)*4+k],0));
const transform=(p,m)=>[0,1,2].map(i=>m[i]*p[0]+m[i+4]*p[1]+m[i+8]*p[2]+m[i+12]);
const finitePoint=p=>Array.isArray(p)&&p.length===3&&p.every(Number.isFinite);

function detourOpenDoor({data,positions,indices,from,to,doorId,state,waypointToleranceMm=200}){
  if(!finitePoint(from)||!finitePoint(to)||Math.abs(from[2]-to[2])>.01)
    throw Error('The door detour requires finite horizontal millimetre endpoints.');
  if(!Number.isFinite(waypointToleranceMm)||waypointToleranceMm<0)
    throw Error('An explicit nonnegative waypoint tolerance is required.');
  const objectById=new Map(data.objects.map(object=>[object.id,object]));
  const door=objectById.get(doorId);
  if(!door||door.mechanism!=='room_door')throw Error(`Unknown room door ${doorId}`);
  const stateName=typeof state==='string'?state:state?.state||(door.initial_state||door.reference_state);
  const value=typeof state==='number'?state:Number.isFinite(state?.value)?state.value:door.states[stateName];
  if(!Number.isFinite(value))throw Error(`Unknown current state for ${doorId}`);
  const hidden=new Set(data.hidden_body_ids?.building||[]);
  const groups=data.scenes.building.groups.filter(group=>!hidden.has(group.id));
  const leafGroups=door.moving_body_ids.map(id=>groups.find(group=>group.id===id));
  if(leafGroups.some(group=>!group))throw Error(`${doorId}: a native moving leaf body is missing`);
  const leaf=leafGroups.find(group=>/^concept_open_.*_room_door$/.test(group.role))||leafGroups[0];
  const nav=data.navigation;
  const colliderOptions={positions,indices,radius:nav.camera_radius_mm/1000,
    margin:nav.contact_margin_mm/1000,iterations:nav.max_contact_iterations,slides:nav.max_slides};
  const matrix=object=>{
    const current=object===door?value:object.states[object.initial_state||object.reference_state];
    const local=jointMatrix(object.joint,current,object.states[object.reference_state]);
    return object.parent_object_id?multiply(matrix(objectById.get(object.parent_object_id)),local):local;
  };
  const transforms=new Map();
  for(const object of data.objects)for(const id of object.moving_body_ids)transforms.set(id,[matrix(object)]);
  const options={transformsForBody:id=>transforms.get(id)||[null]};
  const fromM=from.map(v=>v/1000),deltaM=minus(to,from).map(v=>v/1000);
  const hit=createCameraCollider({...colliderOptions,groups:leafGroups}).firstHit(fromM,deltaM,options);
  if(!hit)return {waypoints:[[...to]],evidence:[]};

  const fail=(message,extra={})=>{
    const evidence={object_id:doorId,body_id:leaf.id,state:stateName,joint_value:value,
      classification:'state_dependent',resolution:'blocked',...extra};
    const error=Error(`${doorId}: state_dependent blocked, no derived detour: ${message}`);
    error.evidence=evidence;throw error;
  };
  const length=Math.hypot(deltaM[0],deltaM[1])*1000;
  if(length<1)fail('the route segment is too short');
  const along=minus(to,from).map((v,i)=>i===2?0:v/length);
  // The source front selects the corridor side; remove its along-route component.
  const front=door.front;
  if(!finitePoint(front))fail('the door has no source front direction');
  const across=front.map((v,i)=>i===2?0:v-along[i]*dot(front,along));
  const crossLength=Math.hypot(...across);
  if(crossLength<1e-6)fail('the requested leg is a doorway crossing, not a corridor crossing');
  for(let i=0;i<3;i++)across[i]/=crossLength;
  const vertices=[];
  for(const group of leafGroups){
    const m=transforms.get(group.id)[0];
    for(const index of new Set(indices.slice(group.index_start,group.index_start+group.index_count))){
      const p=transform([positions[index*3],positions[index*3+1],positions[index*3+2]],m).map(v=>v*1000);
      vertices.push(p);
    }
  }
  const alongValues=vertices.map(p=>dot(minus(p,from),along));
  const acrossValues=vertices.map(p=>dot(minus(p,from),across));
  const alongMin=Math.min(...alongValues),alongMax=Math.max(...alongValues);
  const acrossMin=Math.min(...acrossValues),tip=Math.max(...acrossValues);
  if(tip-acrossMin<=alongMax-alongMin)fail('the actual leaf is not crosswise to this corridor leg');
  const cameraGuard=nav.camera_radius_mm+nav.contact_margin_mm;
  const numericalAllowance=1;
  const guard=cameraGuard+waypointToleranceMm+numericalAllowance;
  const before=alongMin-guard,after=alongMax+guard;
  if(before<=0||after>=length)fail('the segment endpoints do not leave room for both guarded pass points');
  const pointAt=(s,q)=>from.map((v,i)=>i===2?v:v+along[i]*s+across[i]*q);
  const wallGroups=groups.filter(group=>group.level_id===door.level_id&&group.role==='concept_storey_wall');
  const wallPicker=createPicker({positions,indices,groups:wallGroups});
  // Cast at both pass points as well as the leaf: an angled opposite wall must
  // not yield a wide gap at the hinge while narrowing at an approach waypoint.
  const wallSamples=[before,(alongMin+alongMax)/2,after].map(s=>{
    const origin=pointAt(s,tip+numericalAllowance);
    const wall=wallPicker.pick(origin.map(v=>v/1000),across,{reach:Infinity,targetForBody:id=>id,minDistance:0});
    if(!wall)fail('no opposite native wall bounds the free strip',{ray_origin_mm:origin});
    return {body_id:wall.body_id,origin_mm:origin,
      point_mm:origin.map((v,i)=>v+across[i]*wall.distance_m*1000),
      across_mm:tip+numericalAllowance+wall.distance_m*1000};
  });
  const opposite=Math.min(...wallSamples.map(sample=>sample.across_mm));
  const freeGap=opposite-tip;
  if(freeGap<2*guard)fail('the native free strip cannot contain the camera and arrival tolerance',{
    free_gap_mm:freeGap,required_free_gap_mm:2*guard,waypoint_tolerance_mm:waypointToleranceMm,
    maximum_waypoint_tolerance_mm:freeGap/2-cameraGuard-numericalAllowance,opposite_native_walls:wallSamples});
  const passAcross=(tip+opposite)/2;
  const passPoints=[pointAt(before,passAcross),pointAt(after,passAcross)];
  const waypoints=[...passPoints,[...to]];
  const collider=createCameraCollider({...colliderOptions,groups});
  let previous=from;
  for(const target of waypoints){
    const contact=collider.firstHit(previous.map(v=>v/1000),minus(target,previous).map(v=>v/1000),options);
    if(contact)fail('an unchanged native camera query blocks a derived segment',{
      contact_body_id:contact.body_id,segment_from_mm:previous,segment_to_mm:target});
    previous=target;
  }
  return {waypoints,evidence:[{object_id:doorId,body_id:leaf.id,moving_body_ids:door.moving_body_ids,
    state:stateName,joint_value:value,classification:'state_dependent',resolution:'detour',
    straight_contact_body_id:hit.body_id,free_gap_mm:freeGap,camera_guard_mm:cameraGuard,
    waypoint_tolerance_mm:waypointToleranceMm,numerical_allowance_mm:numericalAllowance,
    minimum_pass_clearance_mm:freeGap/2,pass_points_mm:passPoints,
    native_leaf_projected_interval_mm:{along:[alongMin,alongMax],across:[acrossMin,tip]},
    opposite_native_walls:wallSamples,native_camera_segments_clear:true}]};
}

module.exports={detourOpenDoor};
