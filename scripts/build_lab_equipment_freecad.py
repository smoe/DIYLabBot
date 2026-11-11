"""Native mixed-joint equipment validation, including manual storage access."""
import argparse
import json
import math
from pathlib import Path
import sys

import FreeCAD as App
import Part

import build_tube_carrier_freecad as native
import lab_equipment as model
import robot_spec as robot


def access_checks(doc,spec,p,values):
    shapes = {o.SourceBody:native.motion.world_shape(o) for o in native.objects(doc)}
    refs = model.interfaces(spec,p,values)
    result = []
    family=spec['profile']['family']
    if family in ('water_bath','fume_hood'):
        for identity,frame in refs.items():
            point=App.Vector(*frame['origin_mm'])
            if family=='water_bath':
                probe=Part.makeCylinder(4,p['height']+200-point.z,point)
                overlap=sum(s.common(probe).Volume for s in shapes.values());clear=overlap<1e-5
            else:
                obstructions=[]
                for path in frame.get('access_paths_mm',[{'approach_mm':[point.x,-150,point.z],'origin_mm':list(point)}]):
                    probe=Part.makeLine(App.Vector(*path['approach_mm']),App.Vector(*path['origin_mm']))
                    obstructions.append(sum(s.common(probe).Length for s in shapes.values()))
                overlap=sum(obstructions);clear=all(v<1e-6 for v in obstructions)
            result.append({'id':identity,'accessible':frame['accessible'],'probe_obstruction':overlap,'passed':clear==frame['accessible']})
    elif family=='analytical_balance':
        frame = refs['pan_surface']
        probe = Part.makeCylinder(p['pan_radius'],p['shield_height']+120,
                                  App.Vector(0,p['pan_y'],p['pan_z']+.5))
        overlap = sum(s.common(probe).Volume for s in shapes.values())
        pan_top = shapes['WeighingPan'].BoundBox.ZMax
        result.append({'id':'weighing_surface', 'surface_z_mm':pan_top,
                       'passed':abs(pan_top-p['pan_z'])<1e-7})
        clear = frame['vertical_accessible']
        result.append({'id':'draft_shield_vertical_access','accessible':clear,'obstruction_mm3':overlap,
                       'passed':overlap<1e-5 if clear else overlap>1e-3})
    else:
        for identity,frame in refs.items():
            point = App.Vector(*frame['origin_mm'])
            if frame['access_kind']=='vertical_drawer':
                probe = Part.makeCylinder(3,p['height']+200-point.z,point)
                overlap = sum(s.common(probe).Volume for s in shapes.values())
                clear = overlap<1e-5
            else:
                front = -p['door_thickness']-p['handle_depth']-100
                probe = Part.makeLine(App.Vector(point.x,front,point.z),point)
                overlap = sum(s.common(probe).Length for s in shapes.values())
                clear = overlap<1e-6
            result.append({'id':identity,'accessible':frame['accessible'],'probe_obstruction':overlap,
                           'passed':clear==frame['accessible']})
        if spec['profile']['insert']['kind']=='plastic_drawers':
            source = model.expanded(spec,p)
            for level in model.storage_levels(spec,p):
                i = level['index']
                point = [0,p['drawer_gap']+p['drawer_depth']/2,
                         level['z_mm']+p['shelf_thickness']+4+p['drawer_wall']+20]
                point = robot.transform(model.component_matrix(source,'DrawerGroup%02d'%i,p,values),point)
                cavity = Part.makeSphere(2,App.Vector(*point))
                overlap = shapes['Drawer%02d'%i].common(cavity).Volume
                result.append({'id':'hollow_plastic_drawer_%02d'%i,'interior_overlap_mm3':overlap,'passed':overlap<1e-6})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('report',type=Path)
    parser.add_argument('--compare-step',type=Path)
    args = parser.parse_args()
    case = json.loads(args.case.read_text())
    is_overview = case.get('kind')=='overview'
    if is_overview:
        spec,source,placements = model.overview(model.load())
        p = {}
        class Provider:
            ROOT = model.ROOT
            SOURCE = model.SOURCE
            digest = staticmethod(model.digest)
            evaluate = staticmethod(model.evaluate)
            expanded = staticmethod(lambda spec,p:source)
            pose = staticmethod(lambda spec,p:{})
        native.model=Provider
    else:
        spec = model.materialize(model.load(),case['profile'],case.get('overrides'))
        p = model.parameters(spec)
        source = model.expanded(spec,p)
        native.model = model
    doc = native.build(spec,p,args.output)
    baseline = native.measurements(doc)
    exact = native.step_check(doc,args.compare_step) if args.compare_step else None
    start = {} if is_overview else model.pose(spec,p)
    old = {b['body']:b for b in baseline}
    checks,poses,cache = {},[],{}
    for sample in ([] if is_overview else model.samples(spec,p)):
        values = sample['joint_values']
        native.set_pose(doc,source,values)
        geometry = native.measurements(doc)
        error = 0
        for body in geometry:
            expected = model.pose_change_point(source,body['component'],old[body['body']]['world_center_of_mass_mm'],p,start,values)
            error = max(error,math.dist(expected,body['world_center_of_mass_mm']))
        collisions = native.interference(doc,cache)
        poses.append({**sample,'maximum_pose_error_mm':error,**collisions,
                      'passed':error<1e-7 and collisions['passed']})
        if sample['id'] in {'closed','access','all_open','base_access'}:
            checks[sample['id']] = access_checks(doc,spec,p,values)
    if is_overview:
        closed = None
        refs = None
        collision = native.interference(doc)
    else:
        native.set_pose(doc,source,model.pose(spec,p,'closed'))
        closed = native.measurements(doc)
        native.set_pose(doc,source,start)
        refs = model.interfaces(spec,p,start)
        collision = native.interference(doc)
    for name,value in [('Profile',spec['id']),('Handling','derived_overview' if is_overview else spec['profile']['handling']),
                       ('InterfacesJSON',json.dumps(refs)),('Readings','Unknown; geometry model only'),
                       ('UpdatePolicy','Regenerate from the shared source after native dimension edits')]:
        doc.Controller.addProperty('App::PropertyString',name,'Equipment')
        setattr(doc.Controller,name,value)
        doc.Controller.setEditorMode(name,1)
    doc.save()
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(args.output))
    doc.recompute()
    reopened = native.measurements(doc)
    reopen_ok = len(reopened)==len(baseline) and all(b['valid'] and b['solid_count']==1 for b in reopened)
    report = {'passed':(all(b['valid'] and b['solid_count']==1 for b in baseline) and reopen_ok
                         and (exact is None or all(c['passed'] for c in exact))
                         and all(c['passed'] for c in poses) and collision['passed']
                         and all(c['passed'] for group in checks.values() for c in group)),
              'geometry':baseline,'closed_geometry':closed,'solidcraft_step_xor':exact,
              'motion_samples':poses,'access_checks':checks,'interfaces':refs,
              'reopened':{'passed':reopen_ok},'freecad_version':App.Version(),
              'backend':'Native primitives, booleans, expression-driven hinges and sliders; no imported geometry'}
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    App.closeDocument(doc.Name)
    print(json.dumps({'profile':spec['id'],'passed':report['passed'],
        'failed_poses':[s['id'] for s in poses if not s['passed']],
        'failed_access':{k:[c['id'] for c in v if not c['passed']] for k,v in checks.items()},
        'interference_pairs':sorted({(c['a'],c['b']) for s in poses for c in s['between_components']})}),flush=True)
    if not report['passed']:
        raise AssertionError('Equipment geometry/access checks failed: '+str(args.report))


if __name__=='__main__':
    import build_lab_equipment_freecad as adapter
    adapter.main()
