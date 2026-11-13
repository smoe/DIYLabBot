"""Derive orientation-only L01/ENU axes from the confirmed compass sector.

No metric translation, building calibration or CAD transformation is inferred.
"""
import json,math,collections
from pathlib import Path
import relative_floorplan as floor
import assembly_model as assembly
ROOT=floor.ROOT
SOURCE=ROOT/'model/l01-orientation.reference.json'
SECTORS={'N':0,'NE':45,'E':90,'SE':135,'S':180,'SW':225,'W':270,'NW':315}

def derive(source=None):
    s=json.loads(SOURCE.read_text()) if source is None else source
    if s['format']!='solidcraftbot.orientation-reference/1' or s['purpose']!='orientation_reference_only':raise ValueError('Orientation-only contract required')
    for reference in s['sources'].values():assembly.validate_reference(reference)
    if s['metric_registration'] is not None:raise ValueError('Metric registration is not implemented')
    if s['window_direction']['measured_azimuth_deg'] is not None:raise ValueError('This reference supports a compass sector, not a surveyed azimuth')
    if s['room_frame']!={'id':'L01','positive_y':'towards_windows','positive_z':'up'}:raise ValueError('Unsupported local axis convention')
    plan=floor.load(assembly.validate_reference(s['sources']['floorplan']))
    room=next(a for a in plan['areas'] if a['id']==s['room_area_id'])
    incidence=collections.Counter(r['wall'] for a in plan['areas'] for r in a['boundary'])
    walls={w['id']:w for w in plan['walls']};refs={r['wall']:r for r in room['boundary']}
    segments=[];weighted=[0.,0.]
    for identity in s['exterior_facade_wall_ids']:
        if identity not in refs or incidence[identity]!=1:raise ValueError('Facade must be an exterior boundary of the selected room: '+identity)
        wall=walls[identity];order=('start','end') if refs[identity]['direction']==1 else ('end','start')
        a,b=[plan['vertices'][wall[k]] for k in order];dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        outward=[dy,-dx];weighted=[x+y for x,y in zip(weighted,outward)]
        segments.append({'wall_id':identity,'endpoints_relative':[a,b],'outward_unit_normal_in_drawing':[v/length for v in outward]})
    nominal=SECTORS[s['window_direction']['compass_sector']];az=math.radians(nominal)
    y=[math.sin(az),math.cos(az),0.];x=[math.cos(az),-math.sin(az),0.];z=[0.,0.,1.]
    norm=math.hypot(*weighted)
    return {'format':'solidcraftbot.orientation-report/1','source_sha256':floor.digest(SOURCE) if source is None else None,
        'source_files_sha256':{**{ref['source']:ref['source_sha256'] for ref in s['sources'].values()},
            **{str(path.relative_to(ROOT)):floor.digest(path) for path in (Path(__file__),Path(floor.__file__),Path(assembly.__file__))}},
        'window_compass_sector':s['window_direction']['compass_sector'],'nominal_window_azimuth_deg_clockwise_from_true_north':nominal,
        'measured_window_azimuth_deg':s['window_direction']['measured_azimuth_deg'],
        'l01_axes_azimuth_deg':{'+X':(nominal+90)%360,'+Y':nominal},
        'rotation_l01_to_enu':[list(row) for row in zip(x,y,z)],'true_north_in_l01':[x[1],y[1],z[1]],
        'facade_segments':segments,'length_weighted_outward_unit_normal_in_f03_drawing':[v/norm for v in weighted],
        'metric_registration':None,'azimuth_evidence':s['window_direction']['evidence'],
        'map_comparison':s['map_reference'],'limitations':s['limitations']}

if __name__=='__main__':print(json.dumps(derive(),indent=2,ensure_ascii=False))
