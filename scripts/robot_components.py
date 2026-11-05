"""Portable vendor-component and motor-plate lowering. No CAD dependencies."""
from pathlib import Path
import copy
import hashlib
import json
import math

ROOT=Path(__file__).resolve().parents[1]

def library(spec):
    ref=spec["vendor_library"]
    path=(ROOT/ref["path"]).resolve()
    if not path.is_relative_to(ROOT/"cad/vendor"): raise ValueError("Vendor library must remain inside project")
    if hashlib.sha256(path.read_bytes()).hexdigest()!=ref["sha256"]: raise ValueError("Vendor library revision changed")
    result=json.loads(path.read_text(encoding="utf-8"))
    if result["format"]!="solidcraftbot.servo-library/1" or result["units"]!="mm": raise ValueError("Unsupported servo library")
    for part in result["parts"].values():
        if "interface_spec" in part:
            source=(ROOT/part["interface_spec"]["path"]).resolve()
            if not source.is_relative_to(ROOT/"model") or hashlib.sha256(source.read_bytes()).hexdigest()!=part["interface_spec"]["sha256"]:
                raise ValueError("Vendor interface specification missing or changed")
        if "interface_check" in part:
            evidence=(ROOT/part["interface_check"]["path"]).resolve()
            if not evidence.is_relative_to(ROOT/"cad/vendor") or hashlib.sha256(evidence.read_bytes()).hexdigest()!=part["interface_check"]["sha256"]:
                raise ValueError("Vendor interface geometry evidence missing or changed")
        for section in part["sections"].values():
            path=(ROOT/section["step"]).resolve()
            if not path.is_relative_to(ROOT/"cad/vendor") or hashlib.sha256(path.read_bytes()).hexdigest()!=section["sha256"]:
                raise ValueError("Vendor STEP missing or changed")
    return result

def axes(frame):
    x,z=frame["x"],frame["axis"]
    if len(x)!=3 or len(z)!=3 or abs(sum(a*a for a in x)-1)>1e-9 or abs(sum(a*a for a in z)-1)>1e-9 or abs(sum(a*b for a,b in zip(x,z)))>1e-9:
        raise ValueError("Component frame must be orthonormal")
    y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]]
    return x,y,z

def offset(frame,point):
    x,y,z=axes(frame)
    return ["(%s) + (%s)"%(v," + ".join("(%s) * (%s)"%(a,b) for a,b in zip([x[i],y[i],z[i]],point) if a) or "0") for i,v in enumerate(frame["origin"])]

def lower_retained_pins(op,interface,operations,appearances):
    """Own press stems and round/relieved heads in the vendor's blind locating bores."""
    pins=interface.get("plate_locating_pins")
    if not pins:return
    centres=pins["selected_centres_mm"];z=interface["z_mm"];frame=op["frame"]
    dx,dy=centres[1][0]-centres[0][0],centres[1][1]-centres[0][1]
    span=math.hypot(dx,dy);ux,uy=dx/span,dy/span
    for i,(x,y) in enumerate(centres):
        if not op["clearance_radius_mm"]+pins["retention_bore_nominal_diameter_mm"]/2<math.hypot(x,y)<op["outer_radius_mm"]-pins["retention_bore_nominal_diameter_mm"]/2:
            raise ValueError("Pin retention bore outside plate material")
        body=op["id"]+"_pin_"+("round" if i==0 else "relieved")
        def cylinder(name,radius,origin,length,action,target):
            item={"id":name,"action":action,"primitive":{"kind":"cylinder","origin":origin,"axis":frame["axis"],"radius":radius,"length":length}}
            item.update({"body":target,"role":"locating_pin"} if action=="create" else {"targets":[target]})
            operations.append(item)
        cylinder(body+"_retention_bore",pins["retention_bore_nominal_diameter_mm"]/2,offset(frame,[x,y,z]),pins["retention_depth_mm"],"subtract",op["body"])
        cylinder(body,pins["stem_nominal_diameter_mm"]/2,offset(frame,[x,y,z]),pins["stem_length_mm"],"create",body)
        if i==0:
            cylinder(body+"_head",pins["head_nominal_diameter_mm"]/2,offset(frame,[x,y,z-pins["projection_mm"]]),pins["projection_mm"],"union",body)
        else:
            radial=pins["relieved_radial_width_mm"]/2;tangent=pins["relieved_tangential_width_mm"]/2
            loop=[[a*ux-b*uy,a*uy+b*ux] for a,b in [(-radial,0),(0,-tangent),(radial,0),(0,tangent)]]
            operations.append({"id":body+"_head","action":"union","targets":[body],"primitive":{
                "kind":"polygon_prism","origin":offset(frame,[x,y,z-pins["projection_mm"]]),"u_axis":axes(frame)[0],"v_axis":axes(frame)[1],
                "loops":[loop],"depth":pins["projection_mm"]}})
        appearances[body]={"color":[190,200,210],"opacity":1}

def lower(spec):
    if "vendor_library" not in spec:return copy.deepcopy(spec)
    from robot_spec import evaluate,parameters
    from servo_mounting_design import analyse
    result=copy.deepcopy(spec); lib=library(spec); values=parameters(spec)
    for link in result["links"]:
        operations=[]
        for op in link["recipe"]:
            action=op["action"]
            if action not in {"vendor_component","mount_plate"}:operations.append(op);continue
            part=lib["parts"][op["part"]]; section=op["section"]
            if section not in {"housing","output"}:raise ValueError("Unknown servo section")
            axes(op["frame"])
            if action=="vendor_component":
                data=part["sections"][section]
                operations.append({"id":op["id"],"action":"create","body":op["body"],"role":"vendor_"+section,
                    "primitive":{"kind":"vendor_step","origin":op["frame"]["origin"],"axis":op["frame"]["axis"],"x":op["frame"]["x"],
                                 **data,"part":op["part"],"section":section}})
                result["body_appearances"][op["body"]]={"color":[80,92,105] if section=="housing" else [180,188,195],"opacity":1}
            else:
                interface=part["interfaces"][section]; z=interface["z_mm"]; thickness=op["thickness_mm"]
                if evaluate(thickness,values)<=0 or op["outer_radius_mm"]<=op["clearance_radius_mm"]:
                    raise ValueError("Invalid motor plate dimensions")
                if "assembly_design_analysis" in part:
                    analyse(json.loads((ROOT/part["interface_spec"]["path"]).read_text(encoding="utf-8")),evaluate(thickness,values))
                base=offset(op["frame"],[0,0,z])
                def cylinder(name,radius,origin,action="create",length=thickness):
                    item={"id":name,"action":action,"primitive":{"kind":"cylinder","origin":origin,"axis":op["frame"]["axis"],"radius":radius,"length":length}}
                    item.update({"body":op["body"],"role":"mount_plate"} if action=="create" else {"targets":[op["body"]]})
                    operations.append(item)
                cylinder(op["id"],op["outer_radius_mm"],base)
                cylinder(op["id"]+"_clearance",op["clearance_radius_mm"],base,"subtract")
                for index,(x,y) in enumerate(interface["hole_centres_mm"]):
                    if (x*x+y*y)**.5+interface["plate_clearance_diameter_mm"]/2>=op["outer_radius_mm"]:raise ValueError("Bolt hole outside plate")
                    cylinder(op["id"]+"_bolt_"+str(index),interface["plate_clearance_diameter_mm"]/2,offset(op["frame"],[x,y,z]),"subtract")
                    if "plate_head_recess" in interface:
                        recess=interface["plate_head_recess"]; r=recess["diameter_mm"]/2
                        if not op["clearance_radius_mm"]+r<math.hypot(x,y)<op["outer_radius_mm"]-r:raise ValueError("Screw head recess outside motor plate material")
                        cylinder(op["id"]+"_head_recess_"+str(index),r,offset(op["frame"],[x,y,"(%s) + (%s) - (%s)"%(z,thickness,recess["depth_mm"])]),"subtract",recess["depth_mm"])
                fit=interface.get("locating_pins",{}).get("plate_fit")
                centres=interface.get("locating_hole_centres_mm",[])
                if fit and len(centres)!=2:raise ValueError("X6 fit needs exactly two registered sleeves")
                for index,(x,y) in enumerate(interface.get("locating_hole_centres_mm",[])):
                    radius=(fit["round_bore_limits_mm"][0] if fit else interface["plate_locating_bore_diameter_mm"])/2
                    if not op["clearance_radius_mm"]+radius<(x*x+y*y)**.5<op["outer_radius_mm"]-radius:raise ValueError("Locating bore outside motor plate material")
                    name=op["id"]+"_locating_"+str(index)
                    if not fit or index==0:
                        cylinder(name,radius,offset(op["frame"],[x,y,z]),"subtract")
                    else:
                        if fit["scheme"]!="one_round_bore_one_radial_relief_slot":raise ValueError("Unsupported locating scheme")
                        width=fit["slot_width_limits_mm"][0]; radius=width/2
                        half=(fit["slot_total_length_mm"]-width)/2
                        dx,dy=x-centres[0][0],y-centres[0][1]; span=math.hypot(dx,dy); ux,uy=dx/span,dy/span
                        if half<=0 or math.hypot(x,y)+radius+half>=op["outer_radius_mm"]:raise ValueError("Invalid radial slot")
                        for k,sign in enumerate([-1,1]):
                            cylinder(name+"_end"+str(k),radius,offset(op["frame"],[x+sign*half*ux,y+sign*half*uy,z]),"subtract")
                        loop=[[a*ux-b*uy,a*uy+b*ux] for a,b in [(-half,-radius),(half,-radius),(half,radius),(-half,radius)]]
                        operations.append({"id":name+"_middle","action":"subtract","targets":[op["body"]],"primitive":{
                            "kind":"polygon_prism","origin":offset(op["frame"],[x,y,z]),"u_axis":axes(op["frame"])[0],
                            "v_axis":axes(op["frame"])[1],"loops":[loop],"depth":thickness}})
                lower_retained_pins(op,interface,operations,result["body_appearances"])
                result["body_appearances"][op["body"]]={"color":[220,168,65],"opacity":1}
        link["recipe"]=operations
    return result

def audit(spec):
    lib=library(spec); joints={j["id"]:j for j in spec["joints"]}; found={}
    for link in spec["links"]:
        for op in link["recipe"]:
            if op["action"] in {"vendor_component","mount_plate"}:
                found.setdefault(op["actuator"],[]).append((link["id"],op))
    results=[]
    for actuator in spec["services"]["actuators"]:
        joint=joints[actuator["joint"]]; ops=found.pop(actuator["id"],[])
        expected={(a,s) for a in ("vendor_component","mount_plate") for s in ("housing","output")}
        if len(ops)!=4 or {(o["action"],o["section"]) for _,o in ops}!=expected: raise ValueError("Each actuator needs housing/output and both plates")
        for link,op in ops:
            if op["part"]!=actuator["part"] or link!=joint["parent" if op["section"]=="housing" else "child"]:
                raise ValueError("Servo housing/output assignment disagrees with joint")
            if op["frame"]!=ops[0][1]["frame"]:raise ValueError("Housing/output and plates require a common registered installation frame")
            if op["action"]=="mount_plate" and op.get("manufacturing_released") is not False:raise ValueError("Concept motor plates are not manufacturing released")
        if actuator["mounted_link"]!=joint["parent"]:raise ValueError("Housing must remain on parent link")
        results.append({"actuator":actuator["id"],"joint":joint["id"],"part":actuator["part"],
            "housing_link":joint["parent"],"output_link":joint["child"],"manufacturing_released":False,
            "interfaces":lib["parts"][actuator["part"]]["interfaces"]})
        if "assembly_design_analysis" in lib["parts"][actuator["part"]]:
            results[-1]["assembly_design_analysis"]=lib["parts"][actuator["part"]]["assembly_design_analysis"]
    if found:raise ValueError("Unknown actuator in component recipe")
    return {"passed":True,"actuators":results,"qualification":"Geometric concept integration; no load/precision/manufacturing release"}
