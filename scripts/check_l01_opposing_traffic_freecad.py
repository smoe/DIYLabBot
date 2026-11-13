"""Independent native interval clearance for the exported three-vehicle curves."""
import FreeCAD as App
import Part
import json,sys
from pathlib import Path
import l01_local_traffic as local
import l01_opposing_traffic as traffic
import check_tr01_floor_motion as check
ROOT=local.ROOT
sys.path.insert(0,str(ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo

def main():
    path=ROOT/'exports/tr01-workcell/opposing-traffic.json';program=json.loads(path.read_text());report=program['native_context']
    local.floor.verify(program['source_files_sha256'])
    for key in ('vehicle','freecad'):
        if local.digest(ROOT/report['files'][key])!=report['artifact_sha256'][key]:raise ValueError('Changed native input')
    scene=App.openDocument(str(ROOT/report['files']['freecad']));obstacles=[(o.Label,geo.world_shape(o),check.box(geo.world_shape(o))) for o in scene.Objects if hasattr(o,'Shape') and not o.Shape.isNull()]
    car=App.openDocument(str(ROOT/report['files']['vehicle']));vehicle=Part.makeCompound([geo.world_shape(o) for o in geo.features(car)])
    routes=[];errors={}
    for t in program['trajectories']:
        points=[{'time_s':p[0],local.F[0]:p[1],local.F[1]:p[2],local.F[2]:p[3]} for p in t['points']]
        reduced,error=traffic.reduced_native_reference(points,program['radius_mm']);errors[t['id']]=error
        routes.append({'id':t['id'],'duration_s':program['duration_s'],'points':local.floor.public(reduced)})
    definition=local.floor.load();baseline=definition['collision']['minimum_clearance_mm'];maximum=max(errors.values());definition['collision']['minimum_clearance_mm']+=maximum;print('Native reference reconstruction bounds',errors,flush=True);result=check.validate({'definition':definition,'routes':routes},vehicle,obstacles,program['radius_mm'],App)
    result['reference_curve_error_upper_mm']=errors
    for route in result['routes']:route['original_curve_clearance_lower_mm']=route['minimum_certified_clearance_mm']-maximum
    result['original_required_clearance_mm']=baseline
    result['program_sha256']=local.digest(path);result['source_files_sha256']=program['source_files_sha256'];result['checker_sha256']=local.digest(__file__);result['native_inputs_sha256']={report['files'][k]:report['artifact_sha256'][k] for k in ('vehicle','freecad')}
    result['scope']='Full loaded covered transporter against checked native workcell with parked arms; dynamic vehicle/person and occupied bench clearance separately audited by the traffic simulator; no new CAD scene or hardware execution'
    (ROOT/'exports/tr01-workcell/opposing-native-clearance.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    if not result['passed']:raise SystemExit('Native opposing-traffic clearance failed')
if __name__=='__main__':
    import check_l01_opposing_traffic_freecad as adapter
    adapter.main()
