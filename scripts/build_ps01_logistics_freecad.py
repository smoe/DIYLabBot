"""FreeCAD construction and native collision audit from shared PS01/TR01 sources."""
from pathlib import Path
import sys
import json
import FreeCAD as App
import Part

import build_ps01_logistics as build
import build_pipetting_station_freecad as base
import ps01_logistics_geometry as geometry
from ps01_logistics_validation import Program,certify,transformed

s=geometry.s


def metrics(shape):
    bb=shape.optimalBoundingBox(False,False)
    return {'bbox':{'min':[bb.XMin,bb.YMin,bb.ZMin],'max':[bb.XMax,bb.YMax,bb.ZMax]},
        'volume_mm3':shape.Volume,'center_of_mass_mm':[sum(x.CenterOfMass[i]*x.Volume for x in shape.Solids)/shape.Volume for i in range(3)]}


def main(directory):
    dest=Path(directory);scene=geometry.Scene();program=Program(s.read(dest/'program.json'),scene)
    records=build.definitions(scene,program);lookup={r['id']:r for r in records};shapes={}
    # Build one prototype for each declared arm variant; instances share that
    # definition, never hand-copied links or joints.
    prototypes={}
    for identity,entry in scene.arms.items():
        key=json.dumps(entry['arm'],sort_keys=True)
        if key not in prototypes:
            doc=base.arm_native.build(entry['arm'],dest/(identity+'_source.FCStd'));home=s.robot.forward(entry['arm'])
            looks=s.robot.appearances(entry['arm']);prototype={}
            for obj in base.motion.features(doc):
                if getattr(obj,'ModelRole','')=='viewing_cone':continue
                shape=base.motion.world_shape(obj);shape.Placement=base.placement(s.robot.inverse(home[obj.RigidLink])).multiply(shape.Placement)
                rgb,opacity=base.motion.source_color(looks,obj.SourceBody,obj.RigidLink)
                prototype[obj.SourceBody]=(shape,{'color':'#'+''.join('%02x'%round(c*255) for c in rgb),'opacity':opacity})
            prototypes[key]=prototype;App.closeDocument(doc.Name)
        for name,(shape,appearance) in prototypes[key].items():
            shapes[identity+'.'+name]=shape.copy();lookup[identity+'.'+name]['appearance']=appearance
    for item in scene.waste:
        spec=base.collector.load(s.assembly.validate_reference(item['source']));p=base.collector.parameters(spec)
        doc=base.waste_native.build(spec,p,dest/(item['id']+'_source.FCStd'))
        looks={b['id']:b['appearance'] for b in base.collector.expanded(spec,p)['bodies']}
        for obj in base.motion.features(doc):
            name=item['id']+'.'+obj.SourceBody;shapes[name]=base.motion.world_shape(obj);lookup[name]['appearance']=looks[obj.SourceBody]
        App.closeDocument(doc.Name)
    for record in records:
        if 'part' in record:
            shapes[record['id']]=base.part_shape(record['part']);record['appearance']=record['part']['appearance']
        shape=shapes[record['id']];s.require(shape.isValid() and shape.Volume>0,'Invalid native solid '+record['id'])
        record['local_metrics']=metrics(shape);record['local_bbox']=record['local_metrics']['bbox']
    doc=App.newDocument('PS01_TR01_Logistics');bodies={};mesh=[];looks=[];boxes=[]
    for record in records:
        name=record['id'];matrix=program.matrix(record,'load.approach',0.);shape=shapes[name].copy()
        record['saved_world_matrix']=matrix
        shape.Placement=base.placement(matrix).multiply(shape.Placement)
        obj=doc.addObject('Part::Feature',name.replace('.','_'));obj.Label=name;obj.Shape=shape
        obj.addProperty('App::PropertyString','SourceBody','Source');obj.SourceBody=name
        bodies[name]=metrics(shape);boxes.append({'body':name,'bbox':bodies[name]['bbox']});looks.append({'id':name,'appearance':record['appearance']})
        vertices,faces=shapes[name].tessellate(1.8)
        mesh.append({'id':name,'vertices':[[v.x,v.y,v.z] for v in vertices],'faces':faces,'appearance':record['appearance']})
    path=dest/'Logistics.FCStd';doc.recompute();doc.saveAs(str(path))
    for obj in base.motion.features(doc):obj.Shape=shapes[obj.SourceBody]
    doc.recompute();doc.saveAs(str(dest/'Logistics-local.FCStd'));App.closeDocument(doc.Name)
    doc=App.openDocument(str(path));reopened=all(base.motion.world_shape(o).isValid() for o in base.motion.features(doc));App.closeDocument(doc.Name)
    presentation=base.persist(path,{'bodies':looks},boxes)
    build.write(dest/'freecad-local-report.json',{'passed':reopened and presentation['passed'],'records':records,
        'bodies':bodies,'solidcraft_construction_dependency':False,'presentation':presentation,'freecad_version':App.Version()})
    build.write(dest/'meshes.json',mesh)
    print({'built_bodies':len(records),'reopened_valid':reopened},flush=True)


if __name__=='__main__':main(sys.argv[1])
