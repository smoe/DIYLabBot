"""Discrete new pipettor versus its own current arm, including both cameras."""
import json
import math
import sys
import FreeCAD as App
import Part
import water_practice_l01 as m
import build_water_practice_l01_freecad as build
import check_tr01_floor_motion as boxes
from build_synthetic_lab_scene_freecad import primitive
sys.path.insert(0,str(m.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo


def main():
    cached=m.read(m.OUT/'motion-cache.json');program=cached['program']
    if build.canonical(program)!=cached['sha256']:raise ValueError('Changed motion cache')
    for path,sha in program['source_files_sha256'].items():
        if m.digest(m.ROOT/path)!=sha:raise ValueError('Changed motion input: '+path)
    meta=m.read(m.OUT/'arm-build.json');arm_path=m.OUT/meta['file']
    for path,sha in meta['source_files_sha256'].items():
        if m.digest(m.ROOT/path)!=sha:raise ValueError('Changed geometry input: '+path)
    if m.digest(arm_path)!=meta['artifact_sha256']:raise ValueError('Changed native arm')
    source=m.robot.load();doc=App.openDocument(str(arm_path));ref=m.robot.forward(source,geo.angles(doc));local={}
    for o in geo.features(doc):
        if getattr(o,'ModelRole','')=='viewing_cone':continue
        local.setdefault(o.RigidLink,[]).append(build.moved(geo.world_shape(o),m.robot.inverse(ref[o.RigidLink])))
    local={link:Part.makeCompound(shapes) for link,shapes in local.items()}
    parts,_=m.tools.kit_parts(program['kit'],program['definition']['pipette_case'])
    tool=Part.makeCompound([primitive(p['shape']) for p in parts]);bounds=boxes.box(tool);checks=[]
    def overlap(a,b):
        return all(a['max'][i]>b['min'][i]+1e-6 and b['max'][i]>a['min'][i]+1e-6 for i in range(3))
    for name,path in program['paths'].items():
        kin=m.kinematics(program['definition'],path['actor'],program['actors'])
        for part,c in path['curves'].items():
            curve=m.motion.Curve(c['points']);times=sorted(set(curve.times+[(a+b)/2 for a,b in zip(curve.times,curve.times[1:])]))
            failures=[];queries=0
            for t in times:
                q=[math.degrees(v) for v in curve.evaluate(t)[m.F[0]]];fk=kin.forward(q)
                flange=m.robot.multiply(fk[source['flange_reference']['link']],m.pickup.placement(kin.flange,0))
                current=build.moved(tool,flange);bound=boxes.box(current)
                for link,shape in local.items():
                    arm=build.moved(shape,fk[link])
                    if not overlap(bound,boxes.box(arm)):continue
                    queries+=1;volume=current.common(arm).Volume
                    if volume>1e-3:failures.append({'time_s':t,'link':link,'overlap_mm3':volume})
                if failures:break
            checks.append({'path':name,'part':part,'samples':len(times),'queries':queries,'failures':failures,'passed':not failures})
            print(json.dumps(checks[-1]),flush=True)
    proof={'passed':all(c['passed'] for c in checks),'checks':checks,
           'scope':'Discrete pipettor versus all own-arm links, cameras included, at PVA knots and interval midpoints; no general self-collision certificate or hardware qualification',
           'excluded_contacts':[],'paths_sha256':build.canonical(program['paths']),
           'arm_artifact_sha256':meta['artifact_sha256'],
           'source_files_sha256':{**program['source_files_sha256'],**meta['source_files_sha256'],
                                  'scripts/check_water_practice_tool_freecad.py':m.digest(__file__),
                                  'scripts/build_water_practice_l01_freecad.py':m.digest(build.__file__)}}
    build.write(m.OUT/'tool-arm-proof.json',proof)
    if not proof['passed']:raise ValueError('Pipettor overlaps own arm')


if __name__=='__main__':
    import check_water_practice_tool_freecad as adapter
    adapter.main()
