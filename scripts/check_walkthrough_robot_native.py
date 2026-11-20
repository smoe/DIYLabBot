"""Sample the empty robot's complete path against checked building/L01 BReps.

Run with FreeCAD's Python. This is a discrete native check, not a continuous
collision certificate or permission to move hardware. Existing stationary
joint/interface contacts are reported separately; new/increased overlap fails.
"""
import json
import sys
from pathlib import Path
import FreeCAD as App
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'scripts/freecad')]
import export_building_walkthrough_freecad as mesh
import solidcraftbot_freecad as geo
import robot_spec as robot
import lab_layout_model as layout
import walkthrough_robots as commands


def matrix(value):return App.Matrix(*[v for row in value for v in row])
def placed(shape, transform):
    result=shape.copy();result.Placement=App.Placement(matrix(transform)).multiply(result.Placement);return result


def check(program, output):
    current_objects,current_configs=commands.compile({'laboratories':program['laboratories']})
    if current_configs!=program['robots']:
        raise ValueError('Stale robot command program')
    for expected in current_objects:
        actual=next(o for o in program['objects'] if o['id']==expected['id'])
        for key in ('joint','moving_body_ids','states','parent_object_id'):
            if actual.get(key)!=expected.get(key):raise ValueError('Stale robot joint '+expected['id'])
    pins={str(p.relative_to(ROOT)):mesh.digest(p) for p in commands.dependencies()+[Path(__file__)]}
    shapes={};roles={};docs=[]
    for kind,source in [('building',next(iter(program['scene_sources'].values()))),('lab',program['equipment_source'])]:
        report=mesh.checked_report(ROOT/source['build_report'],kind)
        doc=App.openDocument(str(ROOT/report['files']['freecad']));docs.append(doc)
        bindings=mesh.native_equipment_bindings(program['laboratories']) if kind=='lab' else []
        for obj in geo.features(doc):
            name=obj.SourceBody;shape=geo.world_shape(obj);role=getattr(obj,'ModelRole','')
            if kind=='lab':
                matches=[d for _,d in bindings if name.startswith(d['id']+'__')]
                if not matches:continue
                if len(matches)!=1:raise ValueError('Ambiguous device')
                d=matches[0];shape=placed(shape,d['transform']);name=d['body_prefix']+name[len(d['id']+'__'):]
            shapes[name]=shape;roles[name]=role
    config=program['robots'][0];objects={o['id']:o for o in program['objects']}
    lab=next(l for l in program['laboratories'] if l['id']==commands.load()['laboratory'])
    source=json.loads((ROOT/lab['layout_source']['source']).read_text());item=next(i for i in source['instances'] if i['id']==commands.load()['instance'])
    spec=layout.instance_source(source,item);world=next(d['world_pose'] for d in lab['device_instances'] if d['id']==item['id'])
    refs=robot.forward(spec,config['reference_deg']);body_links={}
    for j,identity in zip(spec['joints'],config['joint_object_ids']):
        for name in objects[identity]['moving_body_ids']:body_links[name]=j['child']
    for name in body_links:
        if name not in shapes:raise ValueError('Missing native moving body '+name)
    fixed_bounds={name:shape.BoundBox for name,shape in shapes.items()}
    def transformed_bounds(name,transform):
        bb=fixed_bounds[name]
        b=mesh.rigid_bounds(transform,{'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]})
        return App.BoundBox(*b['min'],*b['max'])
    baseline={};contacts={};count=0;max_new=0
    static_links={spec['links'][0]['id']}
    for j,a,b in zip(spec['joints'],config['reference_deg'],config['demo_deg']):
        if j['parent'] in static_links and a==b:static_links.add(j['child'])
    active_bodies={n for n,link in body_links.items() if link not in static_links}
    link_index={link["id"]:i for i,link in enumerate(spec["links"])}
    offsets=[b-a for a,b in zip(config["reference_deg"],config["demo_deg"])]
    invariant_pairs=set();adjacent_pairs=set()
    # Compare each moving link with fixed geometry and other links; same-link
    # contacts are rigid construction, not collision candidates.
    for step in range(13):
        u=step/12;q=[a+u*(b-a) for a,b in zip(config['reference_deg'],config['demo_deg'])];fk=robot.forward(spec,q)
        transforms={link:robot.multiply(robot.multiply(world,fk[link]),robot.inverse(robot.multiply(world,refs[link]))) for link in refs}
        boxes={n:transformed_bounds(n,transforms[link]) for n,link in body_links.items()}
        moved={}
        def shape_at(name):
            if name not in body_links:return shapes[name]
            if name not in moved:moved[name]=placed(shapes[name],transforms[body_links[name]])
            return moved[name]
        seen=set()
        for a in active_bodies:
            for b,original in shapes.items():
                if a==b or (b in body_links and body_links[a]==body_links[b]) or roles[b] in {'planning_overlay','viewing_cone','room_marker','marker'}:continue
                pair=tuple(sorted((a,b)))
                if b in body_links:
                    lo,hi=sorted((link_index[body_links[a]],link_index[body_links[b]]))
                    if hi-lo==1:
                        adjacent_pairs.add(pair);continue
                    if not any(offsets[lo:hi]):
                        invariant_pairs.add(pair);continue
                if pair in seen:continue
                seen.add(pair)
                if not boxes[a].intersect(boxes.get(b,fixed_bounds[b])):continue
                shape,other=shape_at(a),shape_at(b)
                output.parent.mkdir(parents=True,exist_ok=True)
                output.with_suffix('.current-pair.json').write_text(json.dumps({'step':step,'a':a,'b':b}))
                count+=1;volume=shape.common(other).Volume
                if step==0 and volume>1e-3:baseline[pair]=volume
                increase=volume-baseline.get(pair,0);max_new=max(max_new,increase)
                if increase>1e-3:contacts[pair]=max(contacts.get(pair,0),increase)
        progress={'position':step,'intersections':count,'new_contacts':[{'a':a,'b':b,'increase_mm3':v} for (a,b),v in contacts.items()],'excluded_adjacent_link_pairs':len(adjacent_pairs),'invariant_rigid_pairs':len(invariant_pairs),'baseline_contacts':[{'a':a,'b':b,'volume_mm3':v} for (a,b),v in baseline.items()]}
        output.parent.mkdir(parents=True,exist_ok=True);output.with_suffix('.progress.json').write_text(json.dumps(progress,indent=2)+'\n')
        print('Native robot position',step,'intersections',count,'new contacts',len(contacts),flush=True)
        if contacts:break
    result={'passed':not contacts,'positions':step+1,'pair_intersections':count,'maximum_new_overlap_mm3':max_new,
        'excluded_adjacent_link_pairs':len(adjacent_pairs),'invariant_rigid_pairs':len(invariant_pairs),'baseline_contacts':[{'a':a,'b':b,'volume_mm3':v} for (a,b),v in baseline.items()],
        'new_contacts':[{'a':a,'b':b,'increase_mm3':v} for (a,b),v in contacts.items()],
        'scope':'Discrete empty-arm BRep overlap check of environment and non-adjacent links on one reversible joint-space path. Adjacent mechanical joint interfaces excluded. No continuous, hardware or human-speed qualification.'}
    mesh.verify_pins(pins)
    result['source_files_sha256']=pins
    result['native_builds']={k:mesh.digest(ROOT/v['build_report']) for k,v in [('building',next(iter(program['scene_sources'].values()))),('lab',program['equipment_source'])]}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n')
    for doc in docs:App.closeDocument(doc.Name)
    if not result['passed']:raise ValueError('Robot path develops native overlap; see '+str(output))
    return result

if __name__=='__main__':
    program=json.loads(Path(sys.argv[1]).read_text());print(check(program,Path(sys.argv[2])))
