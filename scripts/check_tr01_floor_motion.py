"""Continuous conservative clearance certificate against native L01 solids.

A midpoint native distance minus a rigid-body displacement upper bound proves
an entire interval. Unresolved intervals and actual margin violations fail.
Only the declared floor support contact is excluded; no body collision masks.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import tr01_floor_motion as model


def box(shape):
    b=shape.BoundBox
    return {'min':[b.XMin,b.YMin,b.ZMin],'max':[b.XMax,b.YMax,b.ZMax]}


def box_distance(a,b):
    return math.sqrt(sum(max(0.,a['min'][i]-b['max'][i],b['min'][i]-a['max'][i])**2 for i in range(3)))


def displacement(curve,start,end,radius):
    middle=(start+end)/2;pose=curve.evaluate(middle)[model.F[0]]
    bounds=model.extrema(curve,start,end)
    delta=[max(abs(bounds['min'][i]-pose[i]),abs(bounds['max'][i]-pose[i])) for i in range(3)]
    return math.hypot(*delta[:2])+radius*min(2.,delta[2]),pose


def validate(program,vehicle,obstacles,radius,App):
    s=program['definition'];settings=s['collision'];margin=settings['minimum_clearance_mm'];tolerance=settings['distance_tolerance_mm']
    reports=[]
    for route in program['routes']:
        curve=model.motion.Curve(model.canonical(route['points']));leaves=[];failures=[];queries=0;pruned=0
        def visit(start,end,depth):
            nonlocal queries,pruned
            upper,pose=displacement(curve,start,end,radius)
            moved=vehicle.copy();moved.Placement=App.Placement(App.Vector(pose[0],pose[1],0),App.Rotation(App.Vector(0,0,1),math.degrees(pose[2])))
            bounds=box(moved);lower=math.inf;limiting=None
            for name,shape,ob in obstacles:
                distance=box_distance(bounds,ob)
                if distance-upper-tolerance<margin:
                    queries+=1;distance=moved.distToShape(shape)[0]
                else:pruned+=1
                candidate=distance-upper-tolerance
                if candidate<lower:lower,limiting=candidate,name
                if distance-tolerance<margin:
                    failures.append({'start_s':start,'end_s':end,'midpoint_s':(start+end)/2,
                                     'body':name,'native_distance_mm':distance,'reason':'actual clearance below required margin'})
                    return
            if lower>=margin:
                leaves.append({'start_s':start,'end_s':end,'depth':depth,'clearance_lower_bound_mm':lower,
                               'limiting_body':limiting,'rigid_displacement_upper_mm':upper})
                return
            if depth>=settings['maximum_depth'] or end-start<=settings['minimum_interval_s']:
                failures.append({'start_s':start,'end_s':end,'body':limiting,'lower_bound_mm':lower,'reason':'unresolved interval; no pass from samples'})
                return
            middle=(start+end)/2;visit(start,middle,depth+1);visit(middle,end,depth+1)
        for start,end in zip(curve.times,curve.times[1:]):visit(start,end,0)
        # Proof leaves must cover every original curve interval without gaps.
        covered=bool(leaves) and not failures and abs(leaves[0]['start_s'])<1e-9 and abs(leaves[-1]['end_s']-route['duration_s'])<1e-9
        covered=covered and all(abs(a['end_s']-b['start_s'])<1e-9 for a,b in zip(leaves,leaves[1:]))
        reports.append({'id':route['id'],'passed':covered,'minimum_certified_clearance_mm':min((v['clearance_lower_bound_mm'] for v in leaves),default=None),
                        'native_distance_queries':queries,'bbox_certificates':pruned,'leaves':leaves,'failures':failures,
                        'obstacle_count':len(obstacles),'maximum_depth_used':max((leaf['depth'] for leaf in leaves),default=0)})
        print(json.dumps({k:v for k,v in reports[-1].items() if k not in {'leaves','failures'}},ensure_ascii=False),flush=True)
        if failures:print(json.dumps(failures[:6]),flush=True)
    return {'passed':all(r['passed'] for r in reports),'routes':reports,
            'method':'native BRep midpoint distances or AABB lower distances minus conservative interval rigid-motion displacement',
            'physical_obstacles':[name for name,_,_ in obstacles],'excluded_contact_bodies':[settings['floor_contact_body']],
            'scope':'all source-defined fixed L01 solids; full TR01 load and cover; arms static, lower cupboard fronts closed; no people or drive physics'}


def main(argv=None):
    import FreeCAD as App
    import Part
    import build_sample_transport_freecad as native
    from build_extraction_kit_station import write
    import lab_layout_model as layout
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
    import solidcraftbot_freecad as geometry
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('context');args=parser.parse_args(argv)
    context=json.loads(Path(args.context).read_text());s=model.load();ls=layout.load()
    report=json.loads((model.ROOT/'cad/lab-layout-l01/shared-build-report.json').read_text())
    if not report['passed'] or report['source_sha256']!=model.robot.digest(layout.SOURCE):raise ValueError('Current checked L01 scene required')
    model.verify(report['source_files_sha256'])
    scene_path=model.ROOT/report['files']['freecad']
    if model.robot.digest(scene_path)!=report['artifact_sha256']['freecad']:raise ValueError('Native L01 scene changed')
    doc=App.openDocument(str(scene_path));obstacles=[];scene=[]
    for obj in geometry.features(doc):
        shape=geometry.world_shape(obj);scene.append((obj,shape,box(shape)))
        if obj.LayoutInstance in {'Guides','TR01'} or obj.SourceBody==s['collision']['floor_contact_body']:continue
        obstacles.append((obj.SourceBody,shape,box(shape)))
    installation=[]
    context_parameters=layout.parameters(ls)
    for item in ls['instances']:
        if item['asset'] not in layout.INSTRUMENTS:continue
        bodies=[(obj,shape,bounds) for obj,shape,bounds in scene if obj.LayoutInstance==item['id']]
        top=next(bounds for obj,shape,bounds in scene if obj.SourceBody==item['host']+'_Worktop')
        supported=bool(bodies) and abs(min(bounds['min'][2] for obj,shape,bounds in bodies)-top['max'][2])<1e-6
        contained=all(top['min'][axis]<=bounds['min'][axis] and bounds['max'][axis]<=top['max'][axis]
                      for obj,shape,bounds in bodies for axis in (0,1))
        installation.append({'id':item['id']+'.worktop','passed':supported and contained,
                             'supported':supported,'footprints_on_host':contained})
        if item['asset']=='tapestation':
            dp=layout.provider('tapestation').parameters(layout.instance_source(ls,item))
            margin=dp['side_clearance']
            keepout=Part.makeBox(dp['width']+2*margin,dp['depth']+2*margin,dp['height']+dp['top_clearance'],App.Vector(-margin,-margin,0))
            transform=App.Placement(App.Matrix(*[v for row in layout.matrix(item,context_parameters) for v in row]))
            keepout.Placement=transform.multiply(keepout.Placement)
            hits=[]
            for obj,shape,bounds in scene:
                if obj.LayoutInstance in {'Guides',item['id']}:continue
                if box_distance(box(keepout),bounds)>0:continue
                volume=keepout.common(shape).Volume
                if volume>1e-3:hits.append({'body':obj.SourceBody,'overlap_mm3':volume})
            installation.append({'id':'TS01.installation_clearance','passed':not hits,'collisions':hits,
                                 'local_origin_mm':[-margin,-margin,0],
                                 'size_mm':[dp['width']+2*margin,dp['depth']+2*margin,dp['height']+dp['top_clearance']]})
    spec,p,variant=model.vehicle_source(s,ls)
    tr=native.build(spec,p,variant,Path(context['vehicle_file']))
    shapes=[geometry.world_shape(obj) for obj in geometry.features(tr)]
    if any(not shape.isValid() or shape.Volume<=0 for shape in shapes):raise ValueError('Invalid loaded vehicle solid')
    vehicle_geometry=native.measurements(tr)
    if sum(obj.ModelRole=='closed_tube_reference_envelope' for obj in geometry.features(tr))!=48:
        raise ValueError('All 48 carried tube envelopes required')
    vehicle=Part.makeCompound(shapes)
    bounds=box(vehicle);radius=max(math.hypot(x,y) for x in (bounds['min'][0],bounds['max'][0]) for y in (bounds['min'][1],bounds['max'][1]))
    program=model.compile_program(radius)
    for path in (model.ROOT/'cad/lab-layout-l01/shared-build-report.json',scene_path,model.ROOT/report['files']['validation']):
        program['source_files_sha256'][str(path.relative_to(model.ROOT))]=model.robot.digest(path)
    result=validate(program,vehicle,obstacles,radius,App)
    result['installation_checks']=installation
    result['passed']=result['passed'] and all(check['passed'] for check in installation)
    result.update(vehicle_body_count=len(shapes),vehicle_geometry=vehicle_geometry,vehicle_local_bbox=bounds,full_cover_included=True,
                  layout_report_sha256=model.robot.digest(model.ROOT/'cad/lab-layout-l01/shared-build-report.json'),
                  layout_artifact_sha256=report['artifact_sha256']['freecad'],layout_scene=str(scene_path.relative_to(model.ROOT)))
    # Native snapshots at every route's departure/arrival preserve inspection poses.
    poses=[]
    for route in program['routes']:
        curve=model.motion.Curve(model.canonical(route['points']))
        for endpoint,t in [('departure',0.),('arrival',route['duration_s'])]:
            pose=curve.evaluate(t)[model.F[0]]
            name=route['id']+'_'+endpoint
            obj=doc.addObject('Part::Feature',name);obj.Shape=vehicle.copy()
            obj.Placement=App.Placement(App.Vector(pose[0],pose[1],0),App.Rotation(App.Vector(0,0,1),math.degrees(pose[2])))
            poses.append(name)
    doc.recompute();doc.saveAs(context['inspection_file'])
    write(context['program'],program);write(context['validation'],result)
    App.closeDocument(doc.Name);App.closeDocument(tr.Name)
    if not result['passed']:raise AssertionError('TR01 route clearance certification failed')


if __name__=='__main__':
    import check_tr01_floor_motion as adapter
    adapter.main()
