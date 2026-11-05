"""One-time T01 migration: reviewed dimensions/curves to a portable CAD source.

The historical T01 files are read only. Never overwrites an existing shared source.
"""
import copy
import json
from pathlib import Path
from prepare_tip_collector import ROOT, SOURCE as ORIGINAL, prepare, write_json
from robot_spec import digest

TARGET=ROOT/'model/tip-collector-t01.shared.json'
MARKS=ROOT/'model/tip-collector-t01-markings.json'


def main():
    if TARGET.exists() or MARKS.exists(): raise FileExistsError('Shared source already exists')
    original=json.loads(ORIGINAL.read_text(encoding='utf-8'))
    native_path=ROOT/'cad/tip-collector-t01/TipCollector_T01.native.json'
    native=json.loads(native_path.read_text(encoding='utf-8'))
    commands,refs,_=prepare(original)
    spec={k:copy.deepcopy(v) for k,v in original.items() if k!='dimensions'}
    spec.update(format='solidcraftbot.collector/1',id='TipCollector_T01_Shared',
        historical_source='model/tip-collector-t01.json',
        parameters={},components=[{'id':c,'fixed':True} for c in ['Frame','Bin','InsertS','InsertM','InsertL']],
        bodies=[],operations=[],marking_asset='model/tip-collector-t01-markings.json')
    for c in commands:
        if c['command']=='parameters.add':
            p=c['params']; expression=p['expression'].replace(' mm','')
            spec['parameters'][p['name']]={'expression':expression,'unit':'mm'}
    for name,value in {'guide_gap':1,'guide_width':4,'guide_h':6,'guide_overhang':2,
                       'table_inset':12,'post_hole_d':5.5,'pilot_d':4.2,'pilot_depth':12,
                       'post_hole_spacing':16,'mark_depth':0.3,'umr_height':24,'umr_depth':0.8}.items():
        spec['parameters'][name]={'expression':value,'unit':'mm'}
    for g in spec['grooves']:
        spec['parameters']['lane_'+g['id']+'_x']={'expression':g['x_mm'],'unit':'mm'}
    spec['parameters']['bin_h']['range_mm']=[140,175]
    for g in spec['grooves']: spec['parameters']['groove_'+g['id']]['range_mm']=[2,12]
    rename={n:(n.split('_')[0]+'_'+n.split('_')[1] if n.startswith('Fork_') else n) for n in refs}
    for name,ref in refs.items():
        spec['bodies'].append({'id':rename[name],'component':ref['group'],
            'role':'structure' if ref['group']=='Frame' else 'bin' if ref['group']=='Bin' else 'stripper_insert',
            'appearance':{'color':ref['color'],'opacity':1}})
    for c in commands:
        command,p=c['command'],copy.deepcopy(c['params'])
        if command not in ['solid.box','solid.cylinder']: continue
        name=p['name']
        shape={'kind':command.split('.')[1]}
        if shape['kind']=='box': shape.update(size=[p[k] for k in ['length','width','height']],center=p['center'])
        else: shape.update(diameter=p['diameter'],height=p['height'],base=p['base'],axis=[0,0,1])
        if name.startswith('TableHole'):
            x,y=p['base'][:2]
            shape['base']=[f'{1 if x>0 else -1}*(base_x/2-table_inset)',f'{1 if y>0 else -1}*(base_y/2-table_inset)',-1]
        if name.startswith(('PostTopPilot','PostBottomPilot','PostBaseClearance','BeamPostClearance')):
            sign=-1 if ('Left' in name or p['base'][0]<0) else 1
            shape['base'][0]=f'{sign}*post_center_x'
            shape['base'][1]='beam_center_y'+('-' if p['base'][1]<42 else '+')+'post_hole_spacing/2'
            if 'Pilot' in name:
                shape['diameter']='pilot_d'; shape['height']='pilot_depth+1'
                shape['base'][2]='fork_z-beam_t-pilot_depth' if 'Top' in name else 'base_t-1'
            elif name.startswith('Beam'):
                shape.update(diameter='post_hole_d',height='beam_t+2')
                shape['base'][2]='fork_z-beam_t-1'
            else: shape.update(diameter='post_hole_d',height='base_t+2')
        if name.startswith('BinGuide'):
            sign=-1 if name.endswith('Left') else 1
            shape.update(size=['guide_width','bin_y+2*guide_overhang','guide_h'],
                center=[f'{sign}*(bin_x/2+guide_gap+guide_width/2)',0,'base_t+guide_h/2'])
        if name=='BinRearStop':
            shape.update(size=['bin_x','guide_width','guide_h'],center=[0,'bin_y/2+guide_gap+guide_width/2','base_t+guide_h/2'])
        if name.startswith('Fork_'): shape['center'][0]='lane_'+name.split('_')[1]+'_x'
        if name.startswith('InsertFix'):
            lane=name[len('InsertFix')]
            sign=-1 if name.endswith('-1') else 1
            shape['base'][0]=f'lane_{lane}_x+{sign}*insert_hole_dx'
        operation={'id':name,'action':'create' if p['operation']=='new' else 'subtract','shape':shape}
        if p['operation']=='new': operation['body']=rename[p['body_name']]
        else: operation['targets']=[rename[t] for t in p['targets']]
        spec['operations'].append(operation)
        if name.startswith('Fork_'):
            lane=name.split('_')[1]
            spec['operations'].append({'id':'GrooveCut'+lane,'action':'subtract','targets':[rename[name]],
                'shape':{'kind':'stripper_groove','lane':lane}})
    # Keep all the original line and quadratic Bezier curves in neutral units,
    # relative to each capacity marking's baseline. No installed font is required.
    marks={'format':'solidcraftbot.profile-asset/1','units':'mm',
        'provenance':{'source':'cad/tip-collector-t01/TipCollector_T01.native.json','sha256':digest(native_path),
            'note':'One-time extraction of reviewed capacity outlines; line/quadratic curves, no native references'},'profiles':{}}
    for g in spec['grooves']:
        lane=g['id']; s=next(f['sketch'] for f in native['features'] if f.get('name')=='MarkSketch'+lane)
        def point(index):
            p=s['points'][index]['pos']; return [p[0]-g['x_mm'],p[1]-18]
        curves=[]
        for c in s['curves']:
            curve={'kind':'line' if c['type']=='line' else 'quadratic','start':point(c['a']),'end':point(c['b'])}
            if c['type']=='conic':
                if c['rho']!=0.5: raise ValueError('Nonquadratic text curve')
                curve['control']=point(c['apex'])
            elif c['type']!='line': raise ValueError('Unknown text curve')
            curves.append(curve)
        marks['profiles'][lane]={'text':str(g['target_pipette_capacity_ul'])+' uL','curves':curves}
        spec['operations'].append({'id':'CapacityMark'+lane,'action':'subtract','targets':['Fork_'+lane],
            'shape':{'kind':'profile','asset_profile':lane,'origin':['lane_'+lane+'_x',18,'fork_z+fork_t-mark_depth'],
                'u_axis':[1,0,0],'v_axis':[0,1,0],'depth':'2*mark_depth'}})
    spec['labels']=[{'id':'UMR','component':'Bin','text':'UMR','height':'umr_height','depth':'umr_depth',
        'origin':[0,'-bin_y/2','base_t+bin_h/2-umr_height/2'],'u_axis':[1,0,0],'v_axis':[0,0,1],
        'tracking':2,'appearance':{'color':'#0f2d4b','opacity':1},'role':'marking'}]
    spec['scope'].append('Native CAD edits are explorations; adopt them in this shared source and rebuild both models')
    write_json(MARKS,marks); write_json(TARGET,spec)
    print(json.dumps({'source':str(TARGET),'operations':len(spec['operations']),'base_bodies':len(spec['bodies']),'additional_UMR_bodies':3}))


if __name__=='__main__': main()
