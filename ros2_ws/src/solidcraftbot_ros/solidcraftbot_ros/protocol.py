"""ROS-independent trajectory validation and unit handling."""
import math

from . import motion


DERIVATIVES=('velocities_rad_s','accelerations_rad_s2')


def derivative_mode(points):
    present=any(field in point for point in points for field in DERIVATIVES)
    if present and any(not all(field in point for field in DERIVATIVES) for point in points):
        raise ValueError('Position, velocity and acceleration must be supplied together for every point')
    return present


def finite_vector(values,name):
    if (not isinstance(values,(list,tuple)) or len(values)!=6
            or any(type(value) not in (int,float) or not math.isfinite(value) for value in values)):
        raise ValueError('Six finite numeric values required: '+name)
    return values


def derivative_bounds(config,points):
    """Check the exact quintic extrema, including extrema between supplied knots."""
    contract=config.get('interpolation',{})
    if (contract.get('method')!='quintic' or contract.get('controller_interpolation')!='splines'
            or contract.get('live_configuration_verified') is not False):
        raise ValueError('Explicit quintic/splines controller requirement with unverified live configuration required')
    limits=config.get('motion_limits',{})
    if config.get('mode')!='mock' or limits.get('qualified') is not False:
        raise ValueError('Explicit unqualified mock derivative limits required')
    bounds=motion.bounds(points)
    for item in bounds.values():
        for name in ('min','max','max_abs'):finite_vector(item[name],'quintic '+name)
    for field,limit_name in [('velocities_rad_s','velocity_rad_s'),
                             ('accelerations_rad_s2','acceleration_rad_s2'),('jerks_rad_s3','jerk_rad_s3')]:
        limit=limits.get(limit_name)
        values=[limit]*6 if type(limit) in (int,float) else limit
        finite_vector(values,limit_name)
        if any(value<=0 for value in values):raise ValueError('Positive mock derivative limits required')
        if any(actual>maximum+1e-10 for actual,maximum in zip(bounds[field]['max_abs'],values)):
            raise ValueError('Quintic interior exceeds configured mock '+limit_name)
    for lower,upper,(allowed_lower,allowed_upper) in zip(bounds['positions_rad']['min'],bounds['positions_rad']['max'],config['limits_rad']):
        if lower<allowed_lower-1e-10 or upper>allowed_upper+1e-10:
            raise ValueError('Quintic interior joint position outside limits')
    return bounds


def scenario(config,scenario_id):
    names=config["joint_names"]
    if len(names)!=6 or len(set(names))!=6 or len(config["limits_rad"])!=6:
        raise ValueError("Exactly six unique joints and six limits required")
    candidate=next((s for s in config["scenarios"] if s["id"]==scenario_id),None)
    if candidate is None: raise ValueError("Unknown scenario: "+scenario_id)
    if not candidate["points"]: raise ValueError("Empty trajectory")
    pva=derivative_mode(candidate['points'])
    if pva and len(candidate['points'])<2:raise ValueError('At least two PVA knots required')
    previous=-1.; previous_q=None
    for point in candidate["points"]:
        t=point["time_s"]; q=point["positions_rad"]
        if pva and (type(t) not in (int,float) or not math.isfinite(t) or not math.isfinite(t*1e9)):
            raise ValueError('Finite numeric PVA knot times required')
        if not math.isfinite(t) or t<0 or t<=previous: raise ValueError("Trajectory times must increase")
        if pva:
            if t!=round(t*1_000_000_000)/1_000_000_000:
                raise ValueError('PVA knot times must be finite nanosecond-representable values')
            for field in ('positions_rad',*DERIVATIVES):finite_vector(point[field],field)
        if len(q)!=6: raise ValueError("Every point must command six joints")
        for value,(lo,hi) in zip(q,config["limits_rad"]):
            if not math.isfinite(value) or not lo<=value<=hi: raise ValueError("Joint position outside limits")
        if not pva and previous_q is not None and any(abs(a-b)/(t-previous)>config["velocity_limit_rad_s"]+1e-12 for a,b in zip(q,previous_q)):
            raise ValueError("Segment exceeds configured mock velocity limit")
        previous=t; previous_q=q
    if pva:derivative_bounds(config,candidate['points'])
    return candidate


def duration_parts(seconds):
    if not math.isfinite(seconds) or seconds<0: raise ValueError("Invalid duration")
    return divmod(round(seconds*1_000_000_000),1_000_000_000)


def message_point(point,factory):
    """Populate a ROS message or a test stub without importing ROS here."""
    pva=derivative_mode([point]);message=factory()
    message.positions=list(point['positions_rad'])
    if pva:
        for field in ('positions_rad',*DERIVATIVES):finite_vector(point[field],field)
        message.velocities=list(point['velocities_rad_s'])
        message.accelerations=list(point['accelerations_rad_s2'])
    message.time_from_start.sec,message.time_from_start.nanosec=duration_parts(point['time_s'])
    return message
