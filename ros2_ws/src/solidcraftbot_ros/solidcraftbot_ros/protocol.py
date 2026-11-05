"""ROS-independent trajectory validation and unit handling."""
import math


def scenario(config,scenario_id):
    names=config["joint_names"]
    if len(names)!=6 or len(set(names))!=6 or len(config["limits_rad"])!=6:
        raise ValueError("Exactly six unique joints and six limits required")
    candidate=next((s for s in config["scenarios"] if s["id"]==scenario_id),None)
    if candidate is None: raise ValueError("Unknown scenario: "+scenario_id)
    if not candidate["points"]: raise ValueError("Empty trajectory")
    previous=-1.; previous_q=None
    for point in candidate["points"]:
        t=point["time_s"]; q=point["positions_rad"]
        if not math.isfinite(t) or t<0 or t<=previous: raise ValueError("Trajectory times must increase")
        if len(q)!=6: raise ValueError("Every point must command six joints")
        for value,(lo,hi) in zip(q,config["limits_rad"]):
            if not math.isfinite(value) or not lo<=value<=hi: raise ValueError("Joint position outside limits")
        if previous_q is not None and any(abs(a-b)/(t-previous)>config["velocity_limit_rad_s"]+1e-12 for a,b in zip(q,previous_q)):
            raise ValueError("Segment exceeds configured mock velocity limit")
        previous=t; previous_q=q
    return candidate


def duration_parts(seconds):
    if not math.isfinite(seconds) or seconds<0: raise ValueError("Invalid duration")
    return divmod(round(seconds*1_000_000_000),1_000_000_000)
