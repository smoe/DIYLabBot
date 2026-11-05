"""Shared H03 transfer/reset timeline; reuse the mechanism's cam and latch laws."""
import json
import math
import tube_cam_model as model

SOURCE=model.ROOT/'model/tube-cam-h03-cycle.shared.json'


def load(path=SOURCE):
    data=json.loads(path.read_text(encoding='utf-8'))
    if data['format']!='solidcraftbot.tube-cam-cycle/1':raise ValueError('Unsupported H03 cycle format')
    if model.digest(model.ROOT/data['geometry_source'])!=data['geometry_sha256']:
        raise ValueError('Review H03 cycle against changed geometry')
    times=[k['time_s'] for k in data['keyframes']]
    if times[0]!=0 or any(b<=a for a,b in zip(times,times[1:])):raise ValueError('Strictly increasing cycle times required')
    return data


def keys(data,p):
    return [{**k,'inputs':[model.evaluate(v,p) for v in k['inputs']]} for k in data['keyframes']]


def at_time(spec,p,data,time_s):
    if not math.isfinite(time_s):raise ValueError('Finite playback time required')
    frames=keys(data,p);t=max(0,min(frames[-1]['time_s'],time_s))
    for a,b in zip(frames,frames[1:]):
        if t<=b['time_s']:
            u=(t-a['time_s'])/(b['time_s']-a['time_s'])
            controls=[x+(y-x)*u for x,y in zip(a['inputs'],b['inputs'])]
            state=a if t==0 else b
            values=model.values_at(spec,p,*controls)
            model.protocol_check(spec,p,values)
            if b['inputs'][0]>a['inputs'][0]:
                model.authorize_turn(spec,a['inputs'][0],controls[0],b.get('capture_confirmed',False))
            return {'time_s':round(t,6),'phase':state['phase'],'label':state['label'],'detail':state['detail'],
                    'inputs':controls,'values':values}
    raise AssertionError('Timeline segment not found')


def samples(spec,p,data):
    count=round(data['keyframes'][-1]['time_s']*data['sample_fps'])
    times=sorted(set([i/data['sample_fps'] for i in range(count+1)]+[k['time_s'] for k in data['keyframes']]))
    return [at_time(spec,p,data,t) for t in times]
