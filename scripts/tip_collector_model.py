"""CAD-neutral T01 recipe, arithmetic references and SolidCraft adapter."""
from pathlib import Path
import ast
import copy
import json
import math
import robot_spec

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'model/tip-collector-t01.shared.json'
digest=robot_spec.digest
evaluate=robot_spec.evaluate


def load(path=SOURCE):
    spec=json.loads(Path(path).read_text(encoding='utf-8'))
    if spec['format']!='solidcraftbot.collector/1' or spec['units']['length']!='mm': raise ValueError('Collector format/mm required')
    p=parameters(spec)
    names=[b['id'] for b in spec['bodies']]
    if len(set(names))!=len(names): raise ValueError('Duplicate body')
    if any(b['component'] not in {c['id'] for c in spec['components']} for b in spec['bodies']): raise ValueError('Unknown group')
    asset=json.loads((ROOT/spec['marking_asset']).read_text(encoding='utf-8'))
    for g in spec['grooves']:
        if {'x_mm','width_mm'} & set(g): raise ValueError('Groove dimensions belong only in parameters')
        if asset['profiles'][g['id']]['text']!=str(g['target_pipette_capacity_ul'])+' uL': raise ValueError('Capacity marking mismatch')
        if not 0<p['groove_'+g['id']]<p['mouth_width']<p['fork_x']: raise ValueError('Groove width order')
    if not p['fork_front_y']<p['taper_end_y']<p['slot_end_y']<p['beam_center_y']: raise ValueError('Groove length order')
    if p['bin_wall']*2>=min(p['bin_x'],p['bin_y']): raise ValueError('Bin wall too large')
    return spec


def parameters(spec,overrides=None):
    for name in overrides or {}:
        if name in spec['parameters'] and any(isinstance(n,ast.Name) for n in ast.walk(ast.parse(str(spec['parameters'][name]['expression']),mode='eval'))):
            raise ValueError('Override driving parameter, not '+name)
    p=robot_spec.parameters(spec,overrides)
    for name,value in p.items():
        definition=spec['parameters'][name]
        if definition['unit']!='mm': raise ValueError('Expected length parameter')
        lo,hi=definition.get('range_mm',[-2000,2000])
        if not lo<=value<=hi: raise ValueError('Outside reviewed exploration range: '+name)
    for name in ['base_x','base_y','base_t','bin_x','bin_y','bin_h','bin_wall','fork_t','fork_x',
                 'beam_x','beam_y','beam_t','post_x','post_y','post_h','rim_to_fork','umr_height','umr_depth']:
        if p[name]<=0: raise ValueError('Nonpositive dimension: '+name)
    if p['bin_wall']*2>=min(p['bin_x'],p['bin_y']): raise ValueError('Bin wall too large')
    for g in spec['grooves']:
        if not 0<p['groove_'+g['id']]<p['mouth_width']<p['fork_x']: raise ValueError('Groove width order')
    if not p['fork_front_y']<p['taper_end_y']<p['slot_end_y']<p['beam_center_y']: raise ValueError('Groove length order')
    return p



def grooves(spec,p):
    """Derived view of lane positions and widths; the parameter table owns all dimensions."""
    return [{**g,'x_mm':p['lane_'+g['id']+'_x'],'width_mm':p['groove_'+g['id']]} for g in spec['grooves']]

def expanded(spec,p):
    result=copy.deepcopy(spec)
    asset=json.loads((ROOT/spec['marking_asset']).read_text(encoding='utf-8'))
    for op in result['operations']:
        shape=op['shape']
        if shape['kind']=='profile': shape['curves']=asset['profiles'][shape['asset_profile']]['curves']
    for label in result['labels']:
        scale=evaluate(label['height'],p)/10
        width=(len(label['text'])*6+(len(label['text'])-1)*label['tracking'])*scale
        for i,char in enumerate(label['text']):
            name=label['id']+'_'+char+'_'+str(i)
            shift=(i*(6+label['tracking'])*scale-width/2)
            origin=[f'({value}) + ({shift*axis})' for value,axis in zip(label['origin'],label['u_axis'])]
            curves=[]
            for loop in robot_spec.GLYPHS[char]:
                points=[[x*scale,y*scale] for x,y in loop]
                curves.extend({'kind':'line','start':a,'end':b} for a,b in zip(points,points[1:]+points[:1]))
            result['bodies'].append({'id':name,'component':label['component'],'role':'marking','appearance':label['appearance']})
            result['operations'].append({'id':name,'body':name,'action':'create','shape':{'kind':'profile','curves':curves,
                'origin':origin,'u_axis':label['u_axis'],'v_axis':label['v_axis'],'depth':label['depth']}})
    return result


def poly_mul(a,b):
    out=[0.]*(len(a)+len(b)-1)
    for i,x in enumerate(a):
        for j,y in enumerate(b): out[i+j]+=x*y
    return out


def integral(a): return sum(v/(i+1) for i,v in enumerate(a))


def profile_stats(curves):
    area=mx=my=0.
    for c in curves:
        if c['kind']=='line':
            x=[c['start'][0],c['end'][0]-c['start'][0]]
            y=[c['start'][1],c['end'][1]-c['start'][1]]
        else:
            a,k,b=c['start'],c['control'],c['end']
            x=[a[0],2*(k[0]-a[0]),a[0]-2*k[0]+b[0]]
            y=[a[1],2*(k[1]-a[1]),a[1]-2*k[1]+b[1]]
        dx=[i*v for i,v in enumerate(x)][1:]; dy=[i*v for i,v in enumerate(y)][1:]
        area+=(integral(poly_mul(x,dy))-integral(poly_mul(y,dx)))/2
        mx+=integral(poly_mul(poly_mul(x,x),dy))/2
        my-=integral(poly_mul(poly_mul(y,y),dx))/2
    if abs(area)<1e-9: raise ValueError('Empty or inconsistently oriented profile')
    return abs(area),[mx/area,my/area]


def references(spec,p):
    """Analytic volumes, first moments and bounds, including quadratic text curves."""
    result={}
    for op in expanded(spec,p)['operations']:
        s=op['shape']; kind=s['kind']
        if kind=='box':
            size=[evaluate(v,p) for v in s['size']]; com=[evaluate(v,p) for v in s['center']]
            volume=math.prod(size); bounds={'min':[v-d/2 for v,d in zip(com,size)],'max':[v+d/2 for v,d in zip(com,size)]}
        elif kind=='cylinder':
            r=evaluate(s['diameter'],p)/2; h=evaluate(s['height'],p); base=[evaluate(v,p) for v in s['base']]
            com=[base[0],base[1],base[2]+h/2]; volume=math.pi*r*r*h
            bounds={'min':[base[0]-r,base[1]-r,base[2]],'max':[base[0]+r,base[1]+r,base[2]+h]}
        elif kind=='profile':
            area,xy=profile_stats(s['curves']); depth=evaluate(s['depth'],p)
            o=[evaluate(v,p) for v in s['origin']]; u,v=s['u_axis'],s['v_axis']
            n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            com=[o[j]+u[j]*xy[0]+v[j]*xy[1]+n[j]*depth/2 for j in range(3)]; volume=area*depth
            pts=[c[k] for c in s['curves'] for k in ['start','end']]
            coords=[[o[j]+u[j]*a+v[j]*b+n[j]*z for j in range(3)] for a,b in pts for z in [0,depth]]
            bounds={k:[fun(pt[j] for pt in coords) for j in range(3)] for k,fun in [('min',min),('max',max)]}
        elif kind!='stripper_groove': raise ValueError(kind)
        if op['action']=='create':
            result[op['body']]={'body':op['body'],'volume_mm3':volume,'center_of_mass_mm':com,'bbox':bounds}
            continue
        for target in op['targets']:
            ref=result[target]; box=ref['bbox']
            if kind=='stripper_groove':
                w=p['groove_'+s['lane']]; r=w/2; length=p['taper_end_y']-p['fork_front_y']
                areas=[length*(p['mouth_width']+w)/2,(p['slot_end_y']-p['taper_end_y'])*w,math.pi*r*r/2]
                ys=[p['fork_front_y']+length*(p['mouth_width']+2*w)/(3*(p['mouth_width']+w)),
                    (p['taper_end_y']+p['slot_end_y'])/2,p['slot_end_y']+4*r/(3*math.pi)]
                removed=sum(areas)*p['fork_t']; cc=[p['lane_'+s['lane']+'_x'],sum(a*y for a,y in zip(areas,ys))/sum(areas),p['fork_z']+p['fork_t']/2]
            elif kind=='box':
                lo=[max(a,b) for a,b in zip(box['min'],bounds['min'])]; hi=[min(a,b) for a,b in zip(box['max'],bounds['max'])]
                removed=math.prod(max(0,b-a) for a,b in zip(lo,hi)); cc=[(a+b)/2 for a,b in zip(lo,hi)]
            elif kind in ['cylinder','profile']:
                lo=max(box['min'][2],bounds['min'][2]); hi=min(box['max'][2],bounds['max'][2]); overlap=max(0,hi-lo)
                removed=(math.pi*r*r if kind=='cylinder' else area)*overlap
                cc=[com[0],com[1],(lo+hi)/2]
            else: raise ValueError(kind)
            remaining=ref['volume_mm3']-removed
            if remaining<=0: raise ValueError('Cut removed entire body')
            ref['center_of_mass_mm']=[(ref['volume_mm3']*a-removed*b)/remaining for a,b in zip(ref['center_of_mass_mm'],cc)]
            ref['volume_mm3']=remaining
    return list(result.values())


def solidcraft_commands(spec,p):
    source=expanded(spec,p); commands=[]
    def add(command,**params): commands.append({'command':command,'params':params})
    for name,d in source['parameters'].items():
        # Driving parameters retain the requested case value; dependent ones remain expressions.
        expression=d['expression'] if any(isinstance(n,ast.Name) for n in ast.walk(ast.parse(str(d['expression']),mode='eval'))) else p[name]
        add('parameters.add',name=name,expression=str(expression),unit='mm')
    add('document.metadata.set',values={'org.solidcraftbot.tip-collector':{'source':'model/tip-collector-t01.shared.json',
        'source_sha256':digest(SOURCE),'marking_sha256':digest(ROOT/source['marking_asset']),'revision':'T01-shared','status':source['status']}})
    for op in source['operations']:
        s=op['shape']; kind=s['kind']
        args={'name':op['id'],'operation':'new' if op['action']=='create' else 'cut'}
        if op['action']=='create': args['body_name']=op['body']
        else: args['targets']=op['targets']
        if kind=='box':
            args.update(dict(zip(['length','width','height'],s['size'])),center=s['center']); add('solid.box',**args)
        elif kind=='cylinder':
            add('solid.cylinder',diameter=s['diameter'],height=s['height'],base=s['base'],axis=s['axis'],**args)
        elif kind=='stripper_groove':
            lane=s['lane']; x='lane_'+lane+'_x'; w='groove_'+lane
            add('sketch.create',name=op['id']+'_profile',plane='XY',offset='fork_z-1')
            add('sketch.line',points=[[x+'-mouth_width/2','fork_front_y-1'],[x+'+mouth_width/2','fork_front_y-1'],
                [x+'+mouth_width/2','fork_front_y'],[x+'+'+w+'/2','taper_end_y'],[x+'+'+w+'/2','slot_end_y']],infer=False)
            add('sketch.arc.three_point',start='l4.end',end=[x+'-'+w+'/2','slot_end_y'],through=[x,'slot_end_y+'+w+'/2'])
            add('sketch.line',points=['a1.end',[x+'-'+w+'/2','taper_end_y'],[x+'-mouth_width/2','fork_front_y'],'l1.start'],infer=False)
            add('sketch.finish'); add('solid.extrude',distance='fork_t+2',**args)
        elif kind=='profile':
            # Origin planes plus expression offsets preserve native parameter edits.
            # Explicit custom-plane origins in SolidCraft are fixed numeric frames.
            o=s['origin']
            if s['u_axis']==[1,0,0] and s['v_axis']==[0,1,0]:
                add('sketch.create',name=op['id']+'_profile',plane='XY',offset=o[2])
                def point(v): return [f'({o[0]})+({v[0]})',f'({o[1]})+({v[1]})']
            elif s['u_axis']==[1,0,0] and s['v_axis']==[0,0,1]:
                add('sketch.create',name=op['id']+'_profile',plane='XZ',offset=o[1],flip=True)
                def point(v): return [f'({o[0]})+({v[0]})',f'({o[2]})+({v[1]})']
            else: raise ValueError('Unsupported profile frame')
            for c in s['curves']:
                if c['kind']=='line': add('sketch.line',points=[point(c['start']),point(c['end'])],infer=False)
                else: add('sketch.conic',start=point(c['start']),end=point(c['end']),apex=point(c['control']),rho=0.5)
            add('sketch.finish'); add('solid.extrude',distance=s['depth'],**args)
    for group in source['components']:
        add('component.create',name=group['id'],parent='root',activate=False,grounded=True)
        add('component.move_bodies',component=group['id'],bodies=[b['id'] for b in source['bodies'] if b['component']==group['id']])
    for b in source['bodies']: add('appearance.assign',bodies=[b['id']],**b['appearance'])
    return commands
