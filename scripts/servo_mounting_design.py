"""Shared nominal servo screw stacks and locating-pin calculations; no CAD imports."""
import math

def fastener_stacks(source,plate_thickness_mm=None):
    label=source["part"].split("-")[1]
    design=source["assembly_design"]
    thickness=design["plate"]["nominal_thickness_mm"]
    if plate_thickness_mm is not None and abs(plate_thickness_mm-thickness)>1e-9:
        raise ValueError(f"{label} plate thickness changed: reselect fasteners and update the stack assumptions")
    dt=design["plate"]["thickness_tolerance_mm"]
    if thickness<=0 or dt<0:raise ValueError(f"Invalid {label} plate thickness")
    result={"status":"calculated_under_stated_assumptions_sample_pending","fasteners":{},"locating":{},"manufacturing_released":False}
    for section in ["housing","output"]:
        part=source[section]; screw=part["fastener_design"]; recess=part["plate_head_recess"]
        length=screw["length_mm"]; dl=screw["accepted_length_tolerance_mm"]
        depth=recess["depth_mm"]; dd=recess["depth_tolerance_mm"]
        washer=screw["washer_stack_mm"]
        unthreaded=part.get("vendor_counterbore_depth_mm",0)
        du=part.get("vendor_counterbore_depth_assumption_tolerance_mm",0)
        available=part["vendor_thread_depth_mm"]-screw["thread_depth_assumption_shortfall_mm"]
        grip=thickness-depth+washer
        overlap=length-grip-unthreaded
        low=(length-dl)-((thickness+dt)-(depth-dd)+washer)-(unthreaded+du)
        high=(length+dl)-((thickness-dt)-(depth+dd)+washer)-(unthreaded-du)
        bottom=available-high
        land=thickness-dt-depth-dd
        head_recess=depth-dd-screw["head_height_max_mm"]-washer
        if min(length,depth,available)<=0 or min(dl,dd,du)<0:raise ValueError("Invalid fastener stack")
        if low<screw["minimum_axial_overlap_mm"]-1e-9 or bottom<screw["minimum_tip_margin_mm"]-1e-9:
            raise ValueError(f"{label} "+section+": screw too short or bottoming margin insufficient")
        if land<recess["minimum_floor_mm"]-1e-9 or head_recess<0:
            raise ValueError(f"{label} "+section+": insufficient plate floor or proud screw head")
        if recess["diameter_mm"]<screw["head_diameter_max_mm"]+recess["minimum_diametral_head_clearance_mm"]-1e-9:
            raise ValueError(f"{label} screw head does not clear counterbore")
        result["fasteners"][section]={"designation":screw["designation"],"quantity":part["fastener_count"],
            "effective_plate_grip_mm":grip,"nominal_axial_thread_overlap_mm":overlap,
            "axial_thread_overlap_range_mm":[low,high],"assumed_available_thread_depth_min_mm":available,
            "minimum_tip_margin_mm":bottom,"minimum_plate_floor_mm":land,"minimum_head_recess_mm":head_recess,
            "minimum_measured_face_to_usable_thread_end_mm":(length+dl)-((thickness-dt)-(depth+dd)+washer)+screw["minimum_tip_margin_mm"],
            "thread_depth_reference":part["thread_depth_reference"],
            "full_thread_engagement_verified":False,"torque_nm":None}
    return result

def analyse(source,plate_thickness_mm=None):
    if "locating_pins" in source["housing"]:
        from x6_mounting_design import analyse as x6
        return x6(source,plate_thickness_mm)
    result=fastener_stacks(source,plate_thickness_mm)
    for name in ["housing","output"]:
        section=source[name]; pins=section["plate_locating_pins"]; bores=section["locating_bores"]
        centres=pins["selected_centres_mm"];span=math.dist(*centres)
        hmin,hmax=pins["head_diameter_limits_mm"]; bmin,bmax=bores["diameter_limits_mm"]
        rmin,rmax=pins["retention_bore_limits_mm"];smin,smax=pins["stem_diameter_limits_mm"]
        projection=pins["projection_mm"];dp=pins["projection_tolerance_mm"]
        tip=bores["depth_mm"]-bores["assumed_depth_shortfall_mm"]-projection-dp
        stem_bottom=pins["retention_depth_mm"]-pins["retention_depth_tolerance_mm"]-pins["stem_length_mm"]-pins["stem_length_tolerance_mm"]
        radial=(bmin-pins["relieved_radial_width_mm"]-pins["relieved_width_tolerance_mm"])/2
        tmin,tmax=pins["relieved_tangential_width_limits_mm"]
        thermal=span*abs(pins["assumed_plate_alpha_per_k"]-pins["assumed_motor_pitch_alpha_per_k"])*pins["assumed_temperature_change_k"]
        budget=pins["assumed_vendor_pitch_error_mm"]+pins["plate_pitch_error_allowance_mm"]+thermal
        worst_offset=budget+(bmax-hmin)/2
        clock=math.radians(pins["assumed_relief_clocking_error_deg"])
        vertices=[(-(pins["relieved_radial_width_mm"]+pins["relieved_width_tolerance_mm"])/2,0),(0,-tmax/2),
                  ((pins["relieved_radial_width_mm"]+pins["relieved_width_tolerance_mm"])/2,0),(0,tmax/2)]
        corner_clearance=bmin/2-max(math.hypot(x*math.cos(a)-y*math.sin(a)+offset,x*math.sin(a)+y*math.cos(a))
            for x,y in vertices for a in [-clock,clock] for offset in [-worst_offset,worst_offset])
        if hmax>bmin+1e-9:raise ValueError("Locating head interferes with vendor bore")
        if smin-rmax<pins["minimum_retention_interference_mm"]-1e-9 or smax-rmin>pins["maximum_retention_interference_mm"]+1e-9:raise ValueError("Pin retention interference outside assumption")
        if tip<pins["minimum_pin_tip_margin_mm"]-1e-9 or stem_bottom<.2:raise ValueError("Locating pin bottoms in blind bore")
        if radial<worst_offset or corner_clearance<0:raise ValueError("Relieved pin corners cannot accommodate pitch and thermal budget")
        angle=math.degrees(math.asin(((bmax-hmin)+(bmax-tmin))/2/span))
        result["locating"][name]={"scheme":"plate_retained_round_and_radially_relieved_pin","selected_centres_mm":centres,"span_mm":span,
            "vendor_bore_limits_mm":[bmin,bmax],"head_diameter_limits_mm":[hmin,hmax],"diametral_clearance_range_mm":[bmin-hmax,bmax-hmin],
            "retention_interference_range_mm":[smin-rmax,smax-rmin],"minimum_vendor_bore_tip_margin_mm":tip,"minimum_retention_bore_tip_margin_mm":stem_bottom,
            "relieved_tangential_width_limits_mm":[tmin,tmax],"radial_relief_allowance_mm":radial,"assumed_pitch_and_thermal_budget_mm":budget,
            "worst_assumed_offset_including_primary_pin_float_mm":worst_offset,"minimum_diamond_corner_clearance_mm":corner_clearance,
            "assumed_relief_clocking_error_deg":pins["assumed_relief_clocking_error_deg"],
            "assembly_angular_free_play_half_range_deg":angle,"illustrative_400mm_lever_error_mm":400*math.sin(math.radians(angle)),
            "pin_retention_strength_verified":False,"manufacturing_released":False}
    return result
