"""Native rigid-pose metrology without recomputing invariant body mass properties.

All bounds start from measured closed native BReps at the zero construction
pose. Native motion.play supplies actual solved world occurrence frames. Eight
construction-box corners enclose every transformed body point. Nearby pairs
still use native BRep distances; no tessellation distance enters the audit.
"""
import itertools
import math
import h02_arm_pickup as model

STUDY='H02NativeAuditPoint'

def keys(program,phase,u):
    s=program.state(phase,u);values=list(zip([j['id'] for j in program.arm['joints']],s['joints_deg']))+list(s['coordinates'].items())
    return [{'joint':name,'points':[[0,value],[1,value]]} for name,value in values]


def drive(program,phase,u):
    return [{'command':'motion.study','params':{'study':STUDY,'steps':1,'keys':keys(program,phase,u)}},
            {'command':'motion.play','params':{'study':STUDY,'step':0,'quiet':True}}]


def pose_matrix(pose):
    m=model.robot.identity()
    for j,axis in enumerate(['x','y','z']):
        for i in range(3):m[i][j]=pose[axis][i]
    for i in range(3):m[i][3]=pose['origin'][i]
    if any(not math.isfinite(v) for row in m for v in row):raise ValueError('Nonfinite native pose')
    if max(abs(sum(m[k][i]*m[k][j] for k in range(3))-(i==j)) for i in range(3) for j in range(3))>1e-7:raise ValueError('Native occurrence is not rigid')
    x,y,z=[pose[a] for a in ['x','y','z']]
    determinant=x[0]*(y[1]*z[2]-y[2]*z[1])-y[0]*(x[1]*z[2]-x[2]*z[1])+z[0]*(x[1]*y[2]-x[2]*y[1])
    if abs(determinant-1)>1e-7:raise ValueError('Native occurrence changed handedness')
    return m


def update(cache,results):
    plays=[]
    for r in results:
        if not isinstance(r,dict) or 'positions' not in r or 'values' not in r:continue
        if r.get('stopped_by_contact') or r.get('stopped_by_loop') or r.get('conflicts') or r.get('unmoved'):raise ValueError('Native inspection pose did not solve freely')
        for item in r['positions']:cache[item['occurrence'].split('/')[-1].removesuffix(':1')]=pose_matrix(item['pose'])
        plays.append(r)
    return plays


def transformed(box,m):
    points=[model.robot.transform(m,p) for p in itertools.product(*zip(box['min'],box['max']))]
    return {'min':[min(p[i] for p in points) for i in range(3)],'max':[max(p[i] for p in points) for i in range(3)]}


def snapshot(program,records,zero,cache):
    boxes={r['id']:transformed(r['native_zero_bbox'],cache.get(r['group'],model.robot.identity())) for r in records}
    centers={}
    for probe in model.probes(program):
        b=zero[probe['id']]['bbox'];point=[(a+b)/2 for a,b in zip(b['min'],b['max'])]
        centers[probe['id']]=model.robot.transform(cache.get(probe['group'],model.robot.identity()),point)
    b=zero['ToolMount']['bbox'];centers['ToolMount']=model.robot.transform(cache['Tool'],[(a+b)/2 for a,b in zip(b['min'],b['max'])])
    return boxes,centers
