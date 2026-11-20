"""Independent native FreeCAD PS01 assembly from shared sources and vendor originals."""
from pathlib import Path
import sys
import FreeCAD as App

import pipetting_station as model
import build_pipetting_station as build
import build_neutral_freecad as arm_native
import build_tip_collector_freecad as waste_native
import tip_collector_model as collector
import labware_transfer as handling
from build_synthetic_lab_scene_freecad import primitive, placement

sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion
from persist_station_view import persist


def part_shape(part):
    shape=primitive(part['shape'])
    for extra in part.get('additions',[]):shape=shape.fuse(primitive(extra))
    for cut in part.get('cuts',[]):shape=shape.cut(primitive(cut))
    return shape.removeSplitter()


def grip_fit(context, records):
    h=context['handling'];p=handling.parameters(h['source']);checks=[]
    for identity,carrier in h['carriers'].items():
        target_instances={identity}
        if carrier['payload']['kind']=='existing_labware':target_instances.add(carrier['payload']['instance'])
        objects=[r for r in records if r['instance'] in target_instances]
        frame=h['frames'][carrier['host']];point=model.robot.transform(frame,[0,0,p['foot_h']])
        pose=placement(handling.tool_target(point,0,h['layout']['park']['roll_deg']))
        for gap in [p['carrier_d'],(p['carrier_d']+p['open_gap'])/2,p['open_gap']]:
            overlaps=[];support_distances=[]
            for part in handling.gripper_parts(h['source'],gap):
                shape=part_shape(part);shape.Placement=pose.multiply(shape.Placement)
                for other in objects:
                    if shape.BoundBox.intersect(other['shape'].BoundBox):
                        volume=shape.common(other['shape']).Volume
                        if volume>1e-4:overlaps.append({'tool':part['id'],'body':other['body'],'volume_mm3':volume})
                    if part['id'].endswith('SupportLip') and other['body']==identity+'.Base':
                        support_distances.append(shape.distToShape(other['shape'])[0])
            contact=gap!=p['carrier_d'] or len(support_distances)==2 and max(support_distances)<1e-5
            checks.append({'carrier':identity,'gap_mm':gap,'overlaps':overlaps,'support_distances_mm':support_distances,
                           'passed':not overlaps and contact})
    return {'passed':all(v['passed'] for v in checks),'checks':checks,
            'scope':'Three local jaw positions against each carrier and payload; closed support contact, no grasp-force, swept-arm-path or hardware qualification.'}


def main(directory):
    dest=Path(directory);saved=model.read(dest/'build-context.json');build.verify_pins(saved['source_files_sha256'])
    context=model.compile_setup();records=[]
    def add(instance,name,shape,appearance,link=None):
        model.require(shape.isValid() and shape.Volume>0 and len(shape.Solids)>0,'Invalid native body: '+name)
        records.append({'instance':instance,'body':instance+'.'+name,'shape':shape,'appearance':appearance,'link':link})
    for identity,entry in context['arms'].items():
        arm=entry['arm'];arm_doc=arm_native.build(arm,dest/(identity+'_Source.FCStd'))
        home=model.robot.forward(arm);arm_looks=model.robot.appearances(arm)
        for obj in motion.features(arm_doc):
            if getattr(obj,'ModelRole','')=='viewing_cone':continue
            delta=model.robot.multiply(entry['state']['world_links'][obj.RigidLink],model.robot.inverse(home[obj.RigidLink]))
            shape=motion.world_shape(obj);shape.Placement=placement(delta).multiply(shape.Placement)
            color,opacity=motion.source_color(arm_looks,obj.SourceBody,obj.RigidLink)
            look={'color':'#'+''.join('%02x'%round(v*255) for v in color),'opacity':opacity}
            add(identity,obj.SourceBody,shape,look,obj.RigidLink)
        App.closeDocument(arm_doc.Name)
    item=context['spatial']['devices']['PS01Waste'];spec=collector.load(model.assembly.validate_reference(item['source']));p=collector.parameters(spec)
    waste=waste_native.build(spec,p,dest/'T01_Source.FCStd');styles={b['id']:b['appearance'] for b in collector.expanded(spec,p)['bodies']}
    for obj in motion.features(waste):
        shape=motion.world_shape(obj);shape.Placement=placement(item['matrix']).multiply(shape.Placement)
        add('PS01Waste',obj.SourceBody,shape,styles[obj.SourceBody])
    App.closeDocument(waste.Name)
    for group in build.groups(context,saved['plan']):
        for part in group['parts']:
            shape=part_shape(part);shape.Placement=placement(group['matrix']).multiply(shape.Placement)
            add(group['id'],part['id'],shape,part['appearance'])
    doc=App.newDocument('PipettingStation_PS01');bodies={};geometry=[];looks=[]
    for record in records:
        name=record['body'];obj=doc.addObject('Part::Feature',name.replace('.','_'));obj.Label=name;obj.Shape=record['shape']
        obj.addProperty('App::PropertyString','SourceBody','Source');obj.SourceBody=name
        shape=record['shape']
        # FreeCAD's default BoundBox can use a triangulation-dependent envelope.
        # Compare exact surface extrema, as reported by the SolidCraft adapter.
        bb=shape.optimalBoundingBox(False,False)
        bounds={'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]}
        center=[sum(s.CenterOfMass[i]*s.Volume for s in shape.Solids)/shape.Volume for i in range(3)]
        bodies[name]={'volume_mm3':shape.Volume,'center_of_mass_mm':center,'bbox':bounds,'valid':shape.isValid(),'solid_count':len(shape.Solids)}
        geometry.append({'body':name,'bbox':bounds});looks.append({'id':name,'appearance':record['appearance']})
    # Check station/robot/tool interactions in this static parked pose. Original
    # internal rigid arm/T01 overlaps and the mounting flange contact stay separate.
    hits=[];exact_checks=0;excluded=[]
    for i,a in enumerate(records):
        for b in records[i+1:]:
            if a['instance']==b['instance'] and a['instance'] in {*context['arms'],'PS01Waste','PipetteEnvelope','LabwareGripper'}:continue
            mounts={'PipetteEnvelope':'PS01Arm','LabwareGripper':'PS01TransferArm'}
            if any(mounts.get(x['instance'])==y['instance'] and y['link']=='L6_BareFlange' for x,y in ((a,b),(b,a))):
                excluded.append([a['body'],b['body']]);continue
            ba,bb=bodies[a['body']]['bbox'],bodies[b['body']]['bbox']
            if any(ba['max'][k]<=bb['min'][k]+1e-6 or bb['max'][k]<=ba['min'][k]+1e-6 for k in range(3)):continue
            exact_checks+=1;volume=a['shape'].common(b['shape']).Volume
            if volume>1e-4:hits.append({'a':a['body'],'b':b['body'],'volume_mm3':volume})
    grip=grip_fit(context,records)
    path=dest/'PS01.FCStd';doc.recompute();doc.saveAs(str(path));App.closeDocument(doc.Name)
    reopened=App.openDocument(str(path));reopen_ok=True
    for obj in motion.features(reopened):
        ref=bodies[obj.SourceBody];shape=motion.world_shape(obj)
        reopen_ok &= shape.isValid() and abs(shape.Volume-ref['volume_mm3'])<max(1e-5,ref['volume_mm3']*1e-9)
    App.closeDocument(reopened.Name)
    presentation=persist(path,{'bodies':looks},geometry)
    build.verify_pins(saved['source_files_sha256'])
    report={'passed':not hits and reopen_ok and presentation['passed'] and grip['passed'],'bodies':bodies,'freecad_version':App.Version(),
        'handling_grip_fit':grip,
        'bounding_box_method':'optimalBoundingBox(useTriangulation=False, useShapeTolerance=False)',
        'parked_pose_interference':{'passed':not hits,'collisions':hits,'exact_checks':exact_checks,'excluded_flange_contacts':excluded,
            'scope':'Station/arm/tool and separate station solids in the saved pose; internal arm/T01/tool-body construction overlaps and flange mounting contacts excluded. No swept path or new arm self-collision qualification.'},
        'reopened_valid':bool(reopen_ok),'presentation':presentation,'solidcraft_construction_dependency':False}
    build.write(dest/'freecad-report.json',report)
    print({'passed':report['passed'],'bodies':len(bodies),'collisions':hits},flush=True)
    model.require(report['passed'],'FreeCAD PS01 parked pose failed')


if __name__=='__main__':main(sys.argv[1])
