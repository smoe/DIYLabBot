"""Orientation-bound solar position and approximate window-emitter geometry."""
import math,json,calendar,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import l01_orientation as orientation
import lab_room_model as room
import assembly_model as assembly
ROOT=room.ROOT
SOURCE=ROOT/'model/l01-daylight.render.json'

def solar_position(latitude,longitude,instant):
    """NOAA fractional-year equations; geometric centre, no refraction."""
    if instant.tzinfo is None:raise ValueError('Timezone-aware solar instant required')
    utc=instant.astimezone(datetime.timezone.utc);hour=utc.hour+utc.minute/60+utc.second/3600
    gamma=2*math.pi/(366 if calendar.isleap(utc.year) else 365)*(utc.timetuple().tm_yday-1+(hour-12)/24)
    eq=229.18*(.000075+.001868*math.cos(gamma)-.032077*math.sin(gamma)-.014615*math.cos(2*gamma)-.040849*math.sin(2*gamma))
    dec=.006918-.399912*math.cos(gamma)+.070257*math.sin(gamma)-.006758*math.cos(2*gamma)+.000907*math.sin(2*gamma)-.002697*math.cos(3*gamma)+.00148*math.sin(3*gamma)
    ha=math.radians((hour*60+eq+4*longitude)/4-180);lat=math.radians(latitude)
    east=-math.cos(dec)*math.sin(ha);north=math.cos(lat)*math.sin(dec)-math.sin(lat)*math.cos(dec)*math.cos(ha)
    up=math.sin(lat)*math.sin(dec)+math.cos(lat)*math.cos(dec)*math.cos(ha)
    return {'azimuth_deg':math.degrees(math.atan2(east,north))%360,'altitude_deg':math.degrees(math.asin(max(-1,min(1,up)))),'direction_enu':[east,north,up]}

def gl_point(p):return [p[0]/4000,p[2]/4000,-p[1]/4000]
def gl_direction(p):return [p[0],p[2],-p[1]]
def unit(v):
    length=math.sqrt(sum(x*x for x in v));return [x/length for x in v]

def derive():
    s=json.loads(SOURCE.read_text())
    if s['format']!='solidcraftbot.daylight-render/1':raise ValueError('Daylight render contract required')
    optical=s['optical_assumptions']
    if not 0<=optical['glazing_transmittance']<=1 or optical['exposure']<=0:raise ValueError('Invalid daylight optical assumptions')
    if optical['window_area_samples_per_window']!=3:raise ValueError('This renderer supports three samples per window')
    for ref in s['sources'].values():assembly.validate_reference(ref)
    o=orientation.derive();rs=room.load();p=room.parameters(rs);portals=[];emitters=[]
    for window_index,w in enumerate(rs['windows']):
        points=[[room.evaluate(v,p) for v in point] for point in room.environment.curve(rs,w['start_fraction'],w['end_fraction'])]
        lengths=[math.dist(a,b) for a,b in zip(points,points[1:])];area=sum(lengths)*(p['window_top']-p['window_sill'])
        for a,b in zip(points,points[1:]):portals.append({'id':window_index,'segment_gl':[a[0]/4000,-a[1]/4000,b[0]/4000,-b[1]/4000]})
        for fraction,height in ((.2,.25),(.5,.75),(.8,.25)):
            x=p['room_width']*(w['start_fraction']+(w['end_fraction']-w['start_fraction'])*fraction)
            a,b=next((a,b) for a,b in zip(points,points[1:]) if a[0]-1e-8<=x<=b[0]+1e-8)
            u=(x-a[0])/(b[0]-a[0]);y=a[1]+u*(b[1]-a[1])+p['wall_t']/2
            outward=unit([-(b[1]-a[1]),b[0]-a[0],0]);position=[x,y,p['window_sill']+height*(p['window_top']-p['window_sill'])]
            emitters.append({'window_id':window_index,'position_gl':gl_point(position),'outward_gl':gl_direction(outward),'area_gl2':area/3/4000**2})
    if len(portals)>24 or len(emitters)!=9:raise ValueError('Daylight player supports three windows and at most 24 facade segments')
    def evaluate(instant):
        solar=solar_position(s['site']['latitude_deg'],s['site']['longitude_deg'],instant)
        matrix=o['rotation_l01_to_enu'];local=[sum(matrix[i][j]*solar['direction_enu'][i] for i in range(3)) for j in range(3)]
        possible=solar['altitude_deg']>0 and any(sum(a*b for a,b in zip(e['outward_gl'],gl_direction(local)))>0 for e in emitters)
        attenuation=optical['clear_atmosphere_transmittance']**(1/max(.08,solar['direction_enu'][2])) if solar['altitude_deg']>0 else 0
        return {**solar,'utc_datetime':instant.astimezone(datetime.timezone.utc).isoformat(),'sun_direction_gl':gl_direction(local),
            'direct_relative':optical['direct_solar_relative']*attenuation*optical['glazing_transmittance'],'direct_window_incidence_possible':possible}
    control=s['time_control'];artificial=s['artificial_lighting']
    if control['sample_interval_minutes']<=0 or 1440%control['sample_interval_minutes']:raise ValueError('Daily samples must divide 24 hours')
    if control['twilight_dark_altitude_deg']>=control['twilight_full_day_altitude_deg']:raise ValueError('Invalid twilight interval')
    if len(artificial['panels'])!=4 or artificial['auto_full_on_altitude_deg']>=artificial['auto_off_altitude_deg']:raise ValueError('Four panels and an ordered automatic-light interval required')
    cases=[]
    for scenario in s['scenarios']:
        instant=datetime.datetime.fromisoformat(scenario['local_datetime']).replace(tzinfo=ZoneInfo(s['site']['timezone']))
        midnight=instant.replace(hour=0,minute=0,second=0)
        samples=[]
        for minute in range(0,1441,s['time_control']['sample_interval_minutes']):
            value=evaluate(midnight+datetime.timedelta(minutes=minute))
            samples.append([round(x,7) for x in [*value['sun_direction_gl'],value['azimuth_deg'],value['altitude_deg'],value['direct_relative']]])
        cases.append({**scenario,**evaluate(instant),'default_minute':instant.hour*60+instant.minute,'time_samples':samples})
    artificial=s['artificial_lighting'];panels=[]
    for panel in artificial['panels']:
        f=panel['position_room_fraction']
        if len(f)!=3 or not all(0<v<1 for v in f) or len(panel['size_mm'])!=2 or not all(v>0 for v in panel['size_mm']):raise ValueError('Invalid ceiling panel geometry')
        position=[f[0]*p['room_width'],f[1]*min(p['left_depth'],p['right_depth']),f[2]*p['room_height']]
        panels.append({'id':panel['id'],'position_gl':gl_point(position),'outward_gl':[0,1,0],
            'area_gl2':math.prod(panel['size_mm'])/4000**2,'position_mm':position,'size_mm':panel['size_mm']})
    dependencies={str(SOURCE.relative_to(ROOT)):room.digest(SOURCE),str(Path(__file__).relative_to(ROOT)):room.digest(__file__),
        str(orientation.SOURCE.relative_to(ROOT)):room.digest(orientation.SOURCE),str(Path(orientation.__file__).relative_to(ROOT)):room.digest(orientation.__file__),
        **{r['source']:r['source_sha256'] for r in s['sources'].values()}}
    return {'format':'solidcraftbot.daylight-render-program/1','default_scenario':s['default_scenario'],'scenarios':cases,'emitters':emitters,'portals':portals,
        'window_vertical_gl':[p['window_sill']/4000,p['window_top']/4000],'wall_thickness_gl':p['wall_t']/4000,
        'time_control':s['time_control'],'artificial_lighting':{**artificial,'panels':panels},'optical_assumptions':s['optical_assumptions'],'shadow_mapping':s['shadow_mapping'],'orientation_azimuth_deg':o['nominal_window_azimuth_deg_clockwise_from_true_north'],
        'source_files_sha256':dependencies,'limitations':s['limitations']}

if __name__=='__main__':print(json.dumps(derive(),indent=2,ensure_ascii=False))
