"""Correlation-preserving FK intervals for the water demo's upright 6R paths.

Uses the common polynomial, interval and derivative-jet arithmetic. The small
pitch/yaw residuals of the actual exported quintics are retained, not rounded
to zero. No speed, acceleration or jerk limit is changed.
"""
import math
import sample_motion as fk
from solidcraftbot_ros import motion


def validate_chain(kin):
    p=kin.p
    axes=[[0,0,1],[0,1,0],[0,1,0],[0,0,1],[0,1,0],[0,0,1]]
    for i,(joint,axis) in enumerate(zip(kin.arm['joints'],axes)):
        frame=joint['frame'];origin=[motion_value(v,p) for v in frame['origin']]
        if frame['axis']!=axis:raise ValueError('Unsupported upright-chain axis')
        if i in (0,5) and max(abs(origin[k]) for k in (0,1))>1e-10:raise ValueError('Offset yaw/roll axis')
        if i in (1,2,4):
            height={1:p['shoulder_z'],2:p['shoulder_z']+p['upper_len'],4:p['wrist_z']}[i]
            if abs(origin[0])+abs(origin[2]-height)>1e-10:raise ValueError('Unsupported planar pitch axis')
    if max(abs(v) for v in kin.flange[:2])>1e-10 or abs(p['wrist_z']-p['shoulder_z']-p['upper_len']-p['fore_len'])>1e-10:
        raise ValueError('Unsupported axial pipette offset')


def motion_value(v,p):
    import robot_spec
    return robot_spec.evaluate(v,p)


def combined(segment,indices,constant=0):
    result=[]
    for k in range(len(segment[0])):
        value=fk.Interval(constant if k==0 else 0)
        for i,sign in indices:value=value+fk.Interval(segment[i][k])*sign
        result.append(value)
    return result


def interval_jet(coefficients,lo,hi,h):
    values=[];u=fk.Interval(lo,hi);row=coefficients
    for order in range(4):
        value=fk.Interval(0)
        for c in reversed(row):value=value*u+c
        values.append(value*(1/h**order))
        row=[c*(i+1) for i,c in enumerate(row[1:])]
    return fk.Jet(*values)


def raw(kin,q,pitch,yaw_difference,points):
    # q4 is identically zero. J2/J3/J5 share the planar pitch direction.
    s,c=q[0].sincos();s2,c2=q[1].sincos();s23,c23=(q[1]+q[2]).sincos()
    sd,cd=pitch.sincos();sb,cb=yaw_difference.sincos();one=fk.Jet(1)
    p=kin.p;lever=kin.flange[2]+kin.length-p['wrist_z']
    radius=p['upper_len']*s2+p['fore_len']*s23-lever*sd
    z=p['shoulder_z']+p['upper_len']*c2+p['fore_len']*c23-lever*cd
    local=[radius*c,radius*s,z]
    tool=[sum(kin.base[i][j]*local[j] for j in range(3))+kin.base[i][3] for i in range(3)]
    # E = Rz(q1) Ry(pitch residual) Rz(-q1). The zero-residual
    # factor is Rz(q1-q6) Ry(pi); this avoids interval cancellation.
    e=[[one+(cd-one)*c*c,(cd-one)*c*s,sd*c],
       [(cd-one)*c*s,one+(cd-one)*s*s,sd*s],[-sd*c,-sd*s,cd]]
    r0=[[-cb,-sb,fk.Jet(0)],[-sb,cb,fk.Jet(0)],[fk.Jet(0),fk.Jet(0),fk.Jet(-1)]]
    r=[[sum(e[i][k]*r0[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    rotation=[[sum(kin.base[i][k]*r[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    pd=fk.Jet(*pitch.d[1:],0);qd=fk.Jet(*q[5].d[1:],0);bd=fk.Jet(*yaw_difference.d[1:],0)
    omega=[-s*pd-c*qd*sd,c*pd-s*qd*sd,bd+qd*(one-cd)]
    omega=[sum(kin.base[i][j]*omega[j] for j in range(3)) for i in range(3)]
    return {**fk._linear(tool),**{field:[v.d[order] for v in omega] for order,field in enumerate(fk.ANGULAR)},
            'points':[fk._linear(fk._point(rotation,tool,point)) for point in points]}


def bounds(kin,points,points_mm,subdivisions):
    validate_chain(kin);curve=points if isinstance(points,motion.Curve) else motion.Curve(points)
    result={field:0. for field in (*fk.LINEAR[1:],*fk.ANGULAR)}
    for i,segment in enumerate(curve.segments):
        if any(v!=0 for v in segment[3]):raise ValueError('Upright proof requires identically zero J4')
        h=curve.times[i+1]-curve.times[i]
        pitch=combined(segment,[(1,1),(2,1),(4,1)],-math.pi)
        yaw=combined(segment,[(0,1),(5,-1)])
        derivatives=[[motion.derivative(c,o) for c in segment] for o in range(4)]
        for step in range(subdivisions):
            lo,hi=step/subdivisions,(step+1)/subdivisions
            q=[fk.Jet(*(fk._polynomial_interval(derivatives[o][j],lo,hi,h**o) for o in range(4))) for j in range(6)]
            residual=interval_jet(pitch,lo,hi,h)
            # Include binary64 pi's numerical representation uncertainty.
            residual=fk.Jet(residual.d[0]+fk.Interval(-1e-15,1e-15),*residual.d[1:])
            value=raw(kin,q,residual,interval_jet(yaw,lo,hi,h),points_mm)
            for field in fk.LINEAR[1:]:result[field]=max(result[field],fk._norm_upper(value[field]),*[fk._norm_upper(v[field]) for v in value['points']])
            for field in fk.ANGULAR:result[field]=max(result[field],fk._norm_upper(value[field]))
    return {**result,'scope':'conservative_numeric_interval_upright_chain_with_polynomial_residuals',
            'formal_floating_point_certificate':False,'subdivisions':subdivisions,'intervals':len(curve.segments)*subdivisions}
