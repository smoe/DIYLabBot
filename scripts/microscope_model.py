"""One portable, detailed static upright research microscope definition."""
import json
import math
from pathlib import Path

import robot_spec as robot
import tube_carrier_model as portable

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/microscope-mi01.shared.json'
digest, evaluate = robot.digest, robot.evaluate


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text())
    if (spec['format'] != 'solidcraftbot.microscope/1'
            or spec['recipe'] != 'upright_trinocular_fluorescence_v1'
            or spec['units'] != {'length': 'mm', 'angle': 'deg'}
            or spec['reference']['dimensions_measured'] is not False):
        raise ValueError('Independent illustrative microscope contract required')
    parameters(spec)
    return spec


def parameters(spec, overrides=None):
    names = {'base_width', 'base_depth', 'stage_z', 'head_z', 'interpupillary_distance'}
    if set(spec['parameters']) != names or set(overrides or {})-names:
        raise ValueError('Only declared microscope parameters may be varied')
    p = robot.parameters(spec, overrides)
    for name, definition in spec['parameters'].items():
        if definition['unit'] != 'mm' or not definition['range'][0] <= p[name] <= definition['range'][1]:
            raise ValueError('Microscope parameter outside declared range: '+name)
    if len(spec['objectives']) != 6 or len({v['id'] for v in spec['objectives']}) != 6:
        raise ValueError('Six distinct source-defined objectives required')
    for obj in spec['objectives']:
        if type(obj['length_mm']) not in (int, float) or not 50 <= obj['length_mm'] <= 86:
            raise ValueError('Objective would exceed the stage clearance envelope')
    return p


def expanded(spec, p):
    result = {'id': spec['id'], 'status': spec['status'],
              'components': [{'id': 'Microscope', 'grounded': True}],
              'bodies': [], 'operations': [], 'joints': []}
    cream, dark, silver, accent = '#e2e4df', '#29333b', '#aebbc1', '#2e718e'
    w, d, stage, head = [p[k] for k in ('base_width', 'base_depth', 'stage_z', 'head_z')]
    sample_y, turret = -45, stage+90

    def add(name, shape, color=cream, role='microscope_structure', opacity=1):
        result['bodies'].append({'id': name, 'component': 'Microscope', 'role': role,
                                'appearance': {'color': color, 'opacity': opacity}})
        result['operations'].append({'id': name, 'body': name, 'action': 'create', 'shape': shape})
        return name

    def cut(name, target, shape):
        result['operations'].append({'id': name, 'body': target, 'action': 'cut', 'shape': shape})

    def box(name, origin, size, color=cream, role='microscope_structure', opacity=1):
        return add(name, {'kind': 'box', 'origin': origin, 'size': size}, color, role, opacity)

    def cyl(name, origin, radius, height, color=dark, axis=None, role='microscope_optics', opacity=1):
        return add(name, {'kind': 'cylinder', 'origin': origin, 'radius': radius,
                         'height': height, 'axis': axis or [0, 0, 1]}, color, role, opacity)

    def cone(name, origin, radius, top, height, color=silver, axis=None):
        return add(name, {'kind': 'cone', 'origin': origin, 'radius': radius,
                         'top_radius': top, 'height': height, 'axis': axis or [0, 0, 1]}, color)

    def prism(name, points, offset, depth, color=cream, plane='XY', role='microscope_structure'):
        return add(name, {'kind': 'polygon_prism', 'plane': plane, 'points': points,
                         'offset': offset, 'depth': depth, 'fixed': True}, color, role)

    def rounded(name, x, y, width, depth, z, height, radius, color=cream, role='microscope_structure'):
        points = []
        for cx, cy, start in [(x+width-radius,y+depth-radius,0),(x+radius,y+depth-radius,90),
                              (x+radius,y+radius,180),(x+width-radius,y+radius,270)]:
            for step in range(9):
                a = math.radians(start+step*90/8)
                points.append([cx+radius*math.cos(a), cy+radius*math.sin(a)])
        return prism(name, points, z, height, color, role=role)

    # Rounded cast foot, dark separation seam and four independent rubber pads.
    rounded('BaseSkirt',-w/2,-d/2,w,d,9,13,42,dark)
    rounded('CastBase',-w/2+3,-d/2+3,w-6,d-6,22,35,40)
    rounded('BaseTop',-w/2+13,-d/2+17,w-26,d-34,57,9,32)
    for i,x,y in [(1,-w/2+45,-d/2+45),(2,w/2-45,-d/2+45),
                  (3,-w/2+45,d/2-45),(4,w/2-45,d/2-45)]:
        cyl('Foot'+str(i),[x,y,0],17,9,dark,role='microscope_support_foot')
    # A profiled C-shaped casting leaves the stage and optical axis open.
    spine = [[102,64],[183,64],[190,90],[190,head-65],[184,head-32],
             [167,head-8],[136,head+14],[94,head+25],[-4,head+25],
             [-4,head-30],[94,head-30],[111,head-50],[116,head-85],[116,84],[102,84]]
    prism('StandCasting',spine,-53,106,plane='YZ')
    prism('StandAccent',[[144,92],[177,92],[177,head-66],[164,head-38],
                        [143,head-20],[131,head-27],[145,head-57]],53,3,accent,'YZ')
    box('FocusGuide',[-42,91,85],[84,23,stage+30-85],dark)
    box('StageCarriage',[-50,57,stage-42],[100,60,27],silver)
    # Coaxial coarse/fine knobs with concentric rim and knurled grip detail.
    for side,sign in [('Left',-1),('Right',1)]:
        axis=[sign,0,0]
        cyl(side+'FocusHub',[sign*53,112,155],25,10,silver,axis)
        cyl(side+'CoarseFocus',[sign*63,112,155],32,18,dark,axis,role='microscope_focus_control')
        cyl(side+'CoarseRim',[sign*80,112,155],30,2,silver,axis)
        cyl(side+'FineFocus',[sign*82,112,155],17,14,dark,axis,role='microscope_focus_control')
        cyl(side+'FineCap',[sign*96,112,155],14,2,accent,axis)
        for n in range(12):
            a=n*math.tau/12
            cyl(side+'FocusGrip'+str(n),[sign*66,112+31*math.cos(a),155+31*math.sin(a)],1.6,12,'#48535b',axis)
    rounded('StageLower',-125,-123,250,200,stage-29,12,12,dark,'microscope_stage')
    cut('StageLowerAperture','StageLower',{'kind':'cylinder','origin':[0,sample_y,stage-30],'radius':29,'height':14})
    rounded('StageUpper',-115,-118,230,190,stage-16,16,7,'#343c43','microscope_stage')
    cut('StageOpticalAperture','StageUpper',{'kind':'cylinder','origin':[0,sample_y,stage-17],'radius':26,'height':18})
    box('StageRailX',[-118,-117,stage-29],[236,5,10],silver)
    box('StageRailY',[115,-112,stage-29],[5,180,10],silver)
    box('SlideCarrier',[-49,-72,stage],[98,54,2],dark)
    cut('CarrierAperture','SlideCarrier',{'kind':'cylinder','origin':[0,sample_y,stage-1],'radius':23,'height':4})
    box('GlassSlide',[-37.5,sample_y-12.5,stage+2],[75,25,1], '#97c5cd','microscope_specimen_slide',.48)
    box('SlideLabel',[22,sample_y-12,stage+3],[14,24,.2],'#efeee4','microscope_slide_label')
    for i,x in enumerate([-46,40]):
        box('SlideClip'+str(i),[x,sample_y-20,stage+2],[6,35,3],silver)
    cyl('StageControlStem',[128,-53,stage-60],8,46,silver)
    for i,z in enumerate([stage-63,stage-86]):
        cyl('StageXYKnob'+str(i),[128,-53,z],14,20,dark,role='microscope_stage_control')
    cyl('CondenserCarrier',[0,sample_y,stage-91],32,15,silver)
    cyl('CondenserIris',[0,sample_y,stage-76],30,14,dark)
    cone('CondenserBody',[0,sample_y,stage-62],28,18,25,dark)
    cyl('CondenserLens',[0,sample_y,stage-37],17,5,'#6ba9b0',opacity=.75)
    cyl('IrisLever',[27,sample_y,stage-71],2.2,24,silver,[1,0,0])
    cyl('FieldDiaphragm',[0,sample_y,66],29,12,dark)
    cyl('IlluminationLens',[0,sample_y,78],23,3,'#80c8ce',opacity=.8)
    cyl('IntensityDial',[w/2-2,-115,40],14,8,dark,[1,0,0],role='microscope_illumination_control')
    box('PowerSwitch',[w/2-1,-156,33],[3,17,11],dark)
    # Six separately identifiable objectives share one recessed nosepiece.
    cyl('NosepieceHub',[0,0,turret+16],25,head-35-(turret+16),silver)
    cyl('ObjectiveTurret',[0,0,turret],64,17,dark,role='microscope_objective_turret')
    cyl('TurretTopRing',[0,0,turret+17],60,3,silver)
    for i,obj in enumerate(spec['objectives']):
        a=-math.pi/2+i*math.tau/6; x,y=45*math.cos(a),45*math.sin(a)
        tag='Objective_'+obj['id']; length=obj['length_mm']; bottom=turret-length
        cyl(tag+'_Mount',[x,y,turret-9],14,9,dark)
        cyl(tag+'_Barrel',[x,y,bottom+15],12,length-24,silver,role='microscope_objective')
        cyl(tag+'_Band',[x,y,bottom+28],12.3,5,obj['band_color'],role='microscope_objective_band')
        cone(tag+'_Tip',[x,y,bottom+2],6.5,12,13,silver)
        cyl(tag+'_Lens',[x,y,bottom],5.7,2,'#4b8a9d')
    rounded('EpiIlluminator',-66,-5,132,216,head-37,42,13,cream,'microscope_fluorescence_housing')
    box('EpiRearVent',[-48,208,head-31],[96,8,28],dark)
    for n in range(8):box('EpiVentSlat'+str(n),[-43+n*11,216,head-28],[3,2,22],silver)
    cyl('FilterSelector',[-69,78,head-16],26,12,dark,[-1,0,0],role='microscope_filter_control')
    cyl('FilterSelectorCap',[-82,78,head-16],21,1,accent,[-1,0,0])
    # Binocular prism head and 30-degree ocular tubes, with actual open eyecups.
    prism('BinocularHead',[[-60,head-18],[45,head-18],[45,head+35],[-16,head+35],[-60,head+12]],-66,132,cream,'YZ')
    axis=[0,-math.cos(math.pi/6),math.sin(math.pi/6)]
    for side,sign in [('Left',-1),('Right',1)]:
        root=[sign*p['interpupillary_distance']/2,-36,head+8]
        point=lambda t:[root[k]+axis[k]*t for k in range(3)]
        cyl(side+'OcularTube',root,15,70,silver,axis)
        cyl(side+'DiopterRing',point(48),17,12,dark,axis,role='microscope_diopter_control')
        cyl(side+'Eyepiece',point(68),15.5,27,dark,axis)
        cup=cyl(side+'Eyecup',point(91),19,10,dark,axis)
        cut(side+'EyecupBore',cup,{'kind':'cylinder','origin':point(90),'radius':12,'height':12,'axis':axis})
        cyl(side+'OcularGlass',point(91),11.8,1.2,'#568b96',axis,opacity=.7)
    cyl('TrinocularPort',[0,69,head+5],22,54,cream)
    cyl('CameraAdapter',[0,69,head+59],17,27,dark)
    rounded('ScientificCamera',-52,27,104,84,head+86,67,11,accent,'microscope_camera')
    rounded('CameraCap',-48,31,96,76,head+153,5,8,dark)
    for n in range(8):box('CameraCoolingFin'+str(n),[-42+n*12,111,head+94],[3,9,49],dark)
    box('CameraConnector',[39,109,head+101],[17,14,13],dark)
    cyl('CameraStatusLED',[36,40,head+158],2.7,1.2,'#7ad5a8',role='microscope_status_indicator')
    # A restrained cable route follows the rear of the stand.
    path=[[47,123,head+108],[56,148,head+108],[63,175,head+80],
          [64,194,head+30],[64,199,head-65],[64,199,100],[40,192,65]]
    for i,(a,b) in enumerate(zip(path,path[1:])):
        length=math.dist(a,b); direction=[(b[k]-a[k])/length for k in range(3)]
        cyl('CameraCable'+str(i),a,2.7,length,dark,direction,role='microscope_cable')
        add('CableBend'+str(i),{'kind':'sphere','origin':a,'radius':2.7},dark,'microscope_cable')
    return result


def pose(spec, p, name=None): return {}
def samples(spec, p): return []
def solidcraft_commands(spec, p):
    import sys
    return portable.solidcraft_commands(spec, p, sys.modules[__name__])


def shape_bounds(shape):
    """Conservative bounds, including inclined optical tubes and profile planes."""
    s=shape; kind=s['kind']
    if kind=='box':
        return {'min':s['origin'][:],'max':[s['origin'][i]+s['size'][i] for i in range(3)]}
    if kind=='polygon_prism':
        axes={'XY':(0,1,2),'XZ':(0,2,1),'YZ':(1,2,0)}[s['plane']]
        lo=[0]*3;hi=[0]*3
        for i,axis in enumerate(axes[:2]):lo[axis]=min(p[i] for p in s['points']);hi[axis]=max(p[i] for p in s['points'])
        lo[axes[2]]=s['offset'];hi[axes[2]]=s['offset']+s['depth']
        return {'min':lo,'max':hi}
    r=max(s['radius'],s.get('top_radius',s['radius']));axis=s.get('axis',[0,0,1]);h=s.get('height',0)
    extent=[r if kind=='sphere' else r*math.sqrt(max(0,1-v*v)) for v in axis]
    return {'min':[s['origin'][i]+min(0,h*axis[i])-extent[i] for i in range(3)],
            'max':[s['origin'][i]+max(0,h*axis[i])+extent[i] for i in range(3)]}


def bounds(operations):
    boxes=[shape_bounds(op['shape']) for op in operations if op['action']!='cut']
    return {key:[fn(b[key][i] for b in boxes) for i in range(3)] for key,fn in [('min',min),('max',max)]}
