"""Explicit workstation priority; pure state transitions for durable callers.

This is a synthetic coordination contract, not a personnel safety function.
No time-based release, request tone or automatic occupant eviction exists.
"""
from manual_tasks import TaskError


def initial(areas):
    return {name:{'status':'unknown','epoch':0,'release':None,'observations':[]} for name in areas}


def observe(state,area,status,observation_id,actor_id):
    if area not in state or status not in {'occupied','clear','unknown'} or not observation_id or not actor_id:
        raise TaskError('Named area, fresh observation and actor required')
    item=state[area]
    if observation_id in item['observations']:raise TaskError('Reused work-area observation')
    item['observations'].append(observation_id);item['status']=status;item['epoch']+=1;item['release']=None


def release(state,area,actor_id,observation_id,*,owner_consents,arms_parked,destination_ready):
    if area not in state:raise TaskError('Unknown work area')
    item=state[area]
    if item['status']!='clear' or not all(v is True for v in (owner_consents,arms_parked,destination_ready)):
        raise TaskError('Observed clear area, explicit owner consent, parked arms and destination readiness required')
    if not actor_id or not observation_id or observation_id in item['observations']:raise TaskError('Fresh release observation and actor required')
    item['observations'].append(observation_id)
    item['release']={'epoch':item['epoch'],'actor_id':actor_id,'observation_id':observation_id}
    return dict(item['release'])


def entry(state,area,token):
    item=state.get(area)
    if not item or item['status']!='clear' or not item['release'] or token!=item['release'] or token['epoch']!=item['epoch']:
        raise TaskError('Workstation entry blocked; wait at the aisle centre without displacing the occupant')
    return True
