"""One-time C01 migration. Preserve the reviewed original and never overwrite source."""
import copy
import json
from pathlib import Path
import prepare_tube_station_draft as legacy

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'model/tube-station-c01.shared.json'


def main():
    if TARGET.exists(): raise FileExistsError(TARGET)
    spec=json.loads(legacy.SOURCE.read_text(encoding='utf-8'))
    parts,cuts=legacy.geometry(spec)
    result=copy.deepcopy(spec)
    result['format']='solidcraftbot.station/1'
    result['id']='TubeStation_C01'
    result['abstraction_revision']='S1'
    result['parameters']={name:{'expression':value,'unit':'mm','range':[value,value]} for name,value in spec['dimensions'].items()}
    result['parameters']['base_length']['range']=[200,220]
    result['parameters']['tube_mouth_z']['range']=[100,110]
    result['parameters']['pivot_z']['expression']='tube_mouth_z + 1'
    result['parameters']['pivot_z']['range']=[101,111]
    del result['dimensions']
    result['components']=[{'id':name,'grounded':name=='Frame'} for name in ['Frame','Opener','Closer','ReferenceLid']]
    result['bodies']=[]; result['cuts']=[]
    def z_expression(value):
        offset=round(value-100,9)
        return 'tube_mouth_z' if offset==0 else 'tube_mouth_z %s %s'%('+' if offset>0 else '-',abs(offset))
    def primitive(part,kind):
        shape={'type':part['kind']}
        if part['kind']=='box':
            shape['size']=part['size'][:]
            shape['origin']=[c-s/2 for c,s in zip(part['center'],part['size'])]
        else:
            shape.update(radius=part['diameter']/2,height=part['height'],origin=part['base'][:],axis=[1,0,0] if part['axis']=='X' else [0,0,1])
        name=part['name']
        if name=='Base':
            shape.update(size=['base_length','base_width','base_thickness'],origin=['-base_length / 2','-base_width / 2',0])
        elif name.startswith('FramePost'):
            shape['size'][2]='tube_mouth_z - base_thickness - 12'
            shape['origin'][2]='base_thickness'
        elif name not in {'IceReservoir','IceWaterReference','ReservoirCavity'}:
            shape['origin'][2]=z_expression(shape['origin'][2])
        return shape
    for part in parts:
        result['bodies'].append({'id':part['name'],'component':part['group'],'role':part['role'],'appearance':{'color':part['color'],'opacity':1},'geometry':primitive(part,'body')})
    for cut in cuts:
        item=copy.deepcopy(cut)
        if cut['name']=='CoolantDisplacement':
            item.update(size=[36,36,48],center=[0,0,70])
        result['cuts'].append({'id':cut['name'],'target':cut['target'],'geometry':primitive(item,'cut')})
    result['joints']=[{'id':name,'type':'revolute','parent':'Frame','child':name,'origin':[0,'pivot_y','pivot_z'],'axis':[1,0,0],'reference_x':[0,1,0],'limits_deg':limits,'visual_reference_only':name=='ReferenceLid'} for name,limits in [('Opener',[-140,0]),('Closer',[-150,3]),('ReferenceLid',[-130,0])]]
    result['parameter_scope']='Ranges are geometry exploration ranges, not qualified operating or thermal ranges. Rebuild from this source for both CADs.'
    TARGET.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(TARGET)


if __name__=='__main__': main()
