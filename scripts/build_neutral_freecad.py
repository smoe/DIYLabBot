"""Native FreeCAD structures and plates plus registered vendor STEP components."""
from pathlib import Path
import ast
import json
import re
import sys

import FreeCAD as App
import Part
import robot_spec as model
import robot_cameras

ROOT=model.ROOT
sys.path.insert(0,str(ROOT/"scripts/freecad"))
import solidcraftbot_freecad as motion


def native_expression(value):
    """Compile linear length expressions to FreeCAD quantities with explicit mm."""
    tree=ast.parse(str(value),mode="eval")
    def has_name(node): return any(isinstance(n,ast.Name) for n in ast.walk(node))
    def visit(node,length=True):
        if isinstance(node,ast.Expression): return visit(node.body,length)
        if isinstance(node,ast.Constant) and type(node.value) in (int,float): return "(%s%s)"%(node.value," mm" if length else "")
        if isinstance(node,ast.Name):
            if not length: raise ValueError("Length parameter used as a scalar")
            return "ModelParameters."+node.id
        if isinstance(node,ast.UnaryOp): return ("-" if isinstance(node.op,ast.USub) else "+")+visit(node.operand,length)
        if isinstance(node,ast.BinOp):
            if isinstance(node.op,(ast.Add,ast.Sub)):
                return "("+visit(node.left,length)+(" + " if isinstance(node.op,ast.Add) else " - ")+visit(node.right,length)+")"
            if isinstance(node.op,ast.Mult):
                if has_name(node.left) and has_name(node.right): raise ValueError("Nonlinear length products are outside version 1")
                left_length=length and has_name(node.left)
                right_length=length and not left_length
                return "("+visit(node.left,left_length)+" * "+visit(node.right,right_length)+")"
            if isinstance(node.op,ast.Div): return "("+visit(node.left,length)+" / "+visit(node.right,False)+")"
        raise ValueError("Unsupported expression")
    return visit(tree)


def app_placement(matrix): return App.Placement(App.Matrix(*[v for row in matrix for v in row]))


def set_origin(obj,origin):
    for axis,value in zip("xyz",origin): obj.setExpression("Placement.Base."+axis,native_expression(value))


def build(spec, output):
    output=Path(output)
    if output.exists(): raise FileExistsError("Existing generated model is preserved: "+str(output))
    values=model.parameters(spec)
    camera_specs=robot_cameras.cameras(spec)
    spec=model.expanded(spec)
    doc=App.newDocument(spec["id"])
    doc.Label=spec["id"]
    params=doc.addObject("App::FeaturePython","ModelParameters")
    params.Label="Shared model parameters (mm)"
    for name in spec["parameters"]:
        params.addProperty("App::PropertyLength",name,"Model")
        setattr(params,name,values[name])
    for name,definition in spec["parameters"].items():
        if any(isinstance(n,ast.Name) for n in ast.walk(ast.parse(str(definition["expression"]),mode="eval"))):
            params.setExpression(name,native_expression(definition["expression"]))
    controller=doc.addObject("App::FeaturePython","Controller")
    controller.Label="Achswinkel (Grad)"
    controller.addProperty("App::PropertyString","SpecSHA256","Source")
    controller.SpecSHA256=model.digest(model.SPEC)
    controller.setEditorMode("SpecSHA256",1)
    for i,joint in enumerate(spec["joints"],1):
        for suffix,value in [("",joint["home_deg"]),("Min",joint["limits_deg"][0]),("Max",joint["limits_deg"][1])]:
            name="J%d%s"%(i,suffix)
            controller.addProperty("App::PropertyAngle",name,"Axes" if not suffix else "Limits")
            setattr(controller,name,value)
            if suffix: controller.setEditorMode(name,1)
    controller.addProperty("App::PropertyVector","FlangeReference","Source")
    for axis,value in zip("xyz",spec["flange_reference"]["point"]): controller.setExpression("FlangeReference."+axis,native_expression(value))
    robot=doc.addObject("App::Part","Robot")
    groups={}
    for i,link in enumerate(spec["links"]):
        if i==0:
            group=doc.addObject("App::Part",link["id"]); robot.addObject(group)
        else:
            joint=spec["joints"][i-1]; f=model.frame(joint,values)
            anchor=doc.addObject("App::Part","J%d_Anchor"%i)
            groups[joint["parent"]].addObject(anchor)
            anchor.Placement=app_placement(f)
            set_origin(anchor,joint["frame"]["origin"])
            turn=doc.addObject("App::Part","J%d_Motion"%i); anchor.addObject(turn)
            lo,hi=joint["limits_deg"]
            turn.setExpression("Placement.Rotation.Angle","max(%s deg; min(%s deg; Controller.J%d))"%(lo,hi,i))
            group=doc.addObject("App::Part",link["id"]); turn.addObject(group)
            group.Placement=app_placement(model.inverse(f))
            origin=joint["frame"]["origin"]
            inverse_origin=[]
            for row in range(3):
                terms=["(%s) * (%s)"%(-f[col][row],origin[col]) for col in range(3) if abs(f[col][row])>1e-12]
                inverse_origin.append(" + ".join(terms) or 0)
            set_origin(group,inverse_origin)
        group.Label=link["id"]; groups[link["id"]]=group
        latest={}; roles={}
        for op in link["recipe"]:
            action=op["action"]
            if action=="translate":
                for index,target in enumerate(op["targets"]):
                    prior=latest[target]
                    shifted=doc.addObject("Part::Compound",op["id"]+"_move_"+str(index))
                    group.addObject(shifted); shifted.Links=[prior]; set_origin(shifted,op["vector"])
                    latest[target]=shifted
                doc.recompute(); continue
            primitive=op["primitive"]
            if primitive["kind"]=="vendor_step":
                path=ROOT/primitive["step"]
                if model.digest(path)!=primitive["sha256"]:raise ValueError("Vendor geometry changed")
                obj=doc.addObject("Part::Feature",op["id"]); group.addObject(obj)
                obj.Shape=Part.read(str(path)); obj.Placement=app_placement(model.frame({"frame":primitive},values))
                set_origin(obj,primitive["origin"])
                obj.addProperty("App::PropertyString","VendorPart","Source"); obj.VendorPart=primitive["part"]
                obj.addProperty("App::PropertyString","VendorSHA256","Source"); obj.VendorSHA256=primitive["sha256"]
                latest[op["body"]]=obj; roles[op["body"]]=op["role"]
                doc.recompute(); continue
            if primitive["kind"]=="polygon_prism":
                u,v=App.Vector(*primitive["u_axis"]),App.Vector(*primitive["v_axis"])
                faces=[]
                for loop in primitive["loops"]:
                    points=[u*x+v*y for x,y in loop]
                    faces.append(Part.Face(Part.makePolygon(points+[points[0]])))
                face=faces[0]
                for hole in faces[1:]: face=face.cut(hole)
                profile=doc.addObject("Part::Feature",op["id"]+"_profile")
                group.addObject(profile); profile.Shape=face; set_origin(profile,primitive["origin"])
                obj=doc.addObject("Part::Extrusion",op["id"])
                group.addObject(obj); obj.Base=profile; obj.Dir=u.cross(v); obj.Solid=True
                obj.setExpression("LengthFwd",native_expression(primitive["depth"]))
                if action=="create": latest[op["body"]]=obj; roles[op["body"]]=op["role"]
                else:
                    for index,target in enumerate(op["targets"]):
                        result=doc.addObject("Part::Cut" if action=="subtract" else "Part::Fuse",op["id"]+"_result_"+str(index))
                        group.addObject(result); result.Base=latest[target]; result.Tool=obj
                        result.Refine=True; latest[target]=result
                doc.recompute(); continue
            obj=doc.addObject({"box":"Part::Box","cylinder":"Part::Cylinder","cone":"Part::Cone"}[primitive["kind"]],op["id"])
            group.addObject(obj)
            if primitive["kind"]=="box":
                for name,value in zip(["Length","Width","Height"],primitive["size"]): obj.setExpression(name,native_expression(value))
                if "axis" in primitive:
                    obj.Placement=app_placement(model.frame({"frame":{**primitive,"origin":[0,0,0]}},values))
            else:
                obj.setExpression("Radius1" if primitive["kind"]=="cone" else "Radius",native_expression(primitive["radius"]))
                if primitive["kind"]=="cone": obj.setExpression("Radius2",native_expression(primitive["top_radius"]))
                obj.setExpression("Height",native_expression(primitive["length"]))
                obj.Placement=App.Placement(App.Vector(),App.Rotation(App.Vector(0,0,1),App.Vector(*primitive["axis"])))
            set_origin(obj,primitive["origin"])
            if action=="create": latest[op["body"]]=obj; roles[op["body"]]=op["role"]
            else:
                for index,target in enumerate(op["targets"]):
                    result=doc.addObject("Part::Cut" if action=="subtract" else "Part::Fuse",op["id"]+"_result_"+str(index))
                    group.addObject(result); result.Base=latest[target]; result.Tool=obj
                    result.Refine=True; latest[target]=result
            doc.recompute()
        for name,obj in latest.items():
            obj.Label=name
            for prop,value in [("SourceBody",name),("RigidLink",link["id"]),("ModelRole",roles[name])]:
                obj.addProperty("App::PropertyString",prop,"Model"); setattr(obj,prop,value); obj.setEditorMode(prop,1)
    for link,camera in camera_specs:
        optical=doc.addObject("App::Part",camera["id"]+"_optical")
        groups[link].addObject(optical)
        optical.Label=camera["id"]+" optical frame (UNCALIBRATED)"
        optical.Placement=app_placement(model.frame({"frame":camera["frame"]},values))
        set_origin(optical,camera["frame"]["origin"])
        optical.addProperty("App::PropertyBool","CalibrationVerified","Camera")
        optical.CalibrationVerified=False
        optical.addProperty("App::PropertyString","MountStatus","Camera")
        optical.MountStatus="provisional; not manufacturing released"
    doc.recompute()
    output.parent.mkdir(parents=True,exist_ok=True)
    doc.saveAs(str(output))
    return doc


def prepare_gui(doc,spec):
    if not App.GuiUp: return
    for obj in doc.Objects:
        if obj.isDerivedFrom("Part::Feature"):
            obj.ViewObject.Visibility="SourceBody" in obj.PropertiesList
    styles=model.appearances(spec)
    for obj in motion.features(doc):
        color,opacity=motion.source_color(styles,obj.SourceBody,obj.RigidLink)
        obj.ViewObject.ShapeColor=color; obj.ViewObject.Transparency=round(100*(1-opacity))
    motion.prepare_view(doc)


def check_servo_head_clearance(doc,spec):
    """Nominal head envelopes at home, including neighbours on the same rigid link."""
    from robot_components import library
    lib=library(spec); p=model.parameters(spec)
    physical=[(o.SourceBody,motion.world_shape(o)) for o in motion.features(doc) if o.ModelRole!="viewing_cone"]
    checks=[]
    for link in spec["links"]:
        for op in link["recipe"]:
            if op["action"]!="mount_plate":continue
            interface=lib["parts"][op["part"]]["interfaces"][op["section"]]
            screw=interface["fastener_design"]; recess=interface["plate_head_recess"]
            placement=motion.global_placement(doc.getObject(link["id"])).multiply(app_placement(model.frame({"frame":op["frame"]},p)))
            for index,(x,y) in enumerate(interface["hole_centres_mm"]):
                z=interface["z_mm"]+model.evaluate(op["thickness_mm"],p)-recess["depth_mm"]
                head=Part.makeCylinder(screw["head_diameter_max_mm"]/2,screw["head_height_max_mm"],App.Vector(x,y,z))
                head.Placement=placement.multiply(head.Placement)
                overlaps=[]
                for body,shape in physical:
                    if head.BoundBox.intersect(shape.BoundBox):
                        volume=head.common(shape).Volume
                        if volume>1e-4:overlaps.append({"body":body,"volume_mm3":volume})
                checks.append({"plate":op["body"],"part":op["part"],"screw_index":index,"overlaps":overlaps})
    return {"pose":"home_only","method":"BRep accepted maximum screw-head cylinders against all physical final bodies, including same-link neighbours",
            "checks":checks,"passed":len(checks)==70 and all(not c["overlaps"] for c in checks),
            "tool_access_and_assembly_sequence_verified":False}

def check_retained_pins(doc,spec):
    """Pin heads must clear vendor material; stem interference is intentional."""
    from robot_components import library
    lib=library(spec);features={o.SourceBody:o for o in motion.features(doc)};checks=[]
    for link in spec["links"]:
        for op in link["recipe"]:
            if op["action"]!="mount_plate":continue
            interface=lib["parts"][op["part"]]["interfaces"][op["section"]]
            if "plate_locating_pins" not in interface:continue
            plate=motion.world_shape(features[op["body"]]);vendor=motion.world_shape(features[op["actuator"]+"_"+op["section"]])
            for suffix in ["round","relieved"]:
                body=op["body"]+"_pin_"+suffix;pin=motion.world_shape(features[body])
                penetration=pin.common(vendor).Volume;retention=pin.common(plate).Volume
                checks.append({"pin":body,"vendor_material_overlap_mm3":penetration,"intentional_press_stem_overlap_mm3":retention,
                    "passed":penetration<1e-4 and retention>0})
    return {"pose":"home_only","checks":checks,"passed":len(checks)==20 and all(c["passed"] for c in checks),"retention_strength_verified":False}


def export_ros_geometry(spec,model_path,package_dir):
    """Export meshes in URDF joint frames, in metres, plus box collision proxies."""
    import MeshPart
    package_dir=Path(package_dir); mesh_dir=package_dir/"meshes"; mesh_dir.mkdir(parents=True,exist_ok=True)
    doc=App.openDocument(str(model_path))
    p=model.parameters(spec); frames={spec["links"][0]["id"]:model.identity()}
    frames.update({j["child"]:model.frame(j,p) for j in spec["joints"]})
    result={"spec_sha256":model.digest(model.SPEC),"units":"m","links":{}}
    for link in spec["links"]:
        inverse_frame=app_placement(model.inverse(frames[link["id"]]))
        shapes=[]; markings=[]; boxes=[]; vendor_visuals=[]; mesh_bodies=[]; camera_shapes=[]
        for obj in motion.features(doc):
            if obj.RigidLink!=link["id"]: continue
            raw=obj.Shape.copy(); bounds=raw.BoundBox
            center=App.Vector((bounds.XMin+bounds.XMax)/2,(bounds.YMin+bounds.YMax)/2,(bounds.ZMin+bounds.ZMax)/2)
            proxy_placement=inverse_frame.multiply(App.Placement(center,App.Rotation()))
            box={"body":obj.SourceBody,"xyz_m":[v/1000 for v in proxy_placement.Base],
                          "rotation_matrix":[list(row[:3]) for row in model.inverse(frames[link["id"]])[:3]],
                          "size_m":[bounds.XLength/1000,bounds.YLength/1000,bounds.ZLength/1000]}
            if obj.ModelRole!="viewing_cone": boxes.append(box)
            if obj.ModelRole.startswith("vendor_"):
                if obj.ModelRole=="vendor_housing":vendor_visuals.append({**box,"part":obj.VendorPart,"color":[80,92,105]})
                # Neither housing nor output is tessellated into a structural
                # mesh. One visible housing box per servo; collision boxes
                # still retain the independently moving output component.
                continue
            raw.Placement=inverse_frame.multiply(raw.Placement)
            if obj.ModelRole in {"camera_envelope","camera_mount","viewing_cone"}:
                color,opacity=motion.source_color(model.appearances(spec),obj.SourceBody,link["id"])
                camera_shapes.append((obj,raw,color,opacity))
                continue
            (markings if obj.ModelRole=="marking" else shapes).append(raw)
            if obj.ModelRole!="marking":mesh_bodies.append(obj.SourceBody)
        def write_mesh(shapes,name):
            mesh=MeshPart.meshFromShape(Shape=Part.makeCompound(shapes),LinearDeflection=0.2,AngularDeflection=0.3,Relative=False)
            scale=App.Matrix(); scale.A11=scale.A22=scale.A33=0.001; mesh.transform(scale)
            path=mesh_dir/(name+".stl"); mesh.write(str(path))
            return {"mesh":path.name,"facets":mesh.CountFacets}
        result["links"][link["id"]]=write_mesh(shapes,link["id"])
        result["links"][link["id"]]["collision_boxes"]=boxes
        result["links"][link["id"]]["servo_visual_boxes"]=vendor_visuals
        result["links"][link["id"]]["mesh_bodies"]=mesh_bodies
        result["links"][link["id"]]["camera_visuals"]=[
            {**write_mesh([shape],obj.SourceBody),"body":obj.SourceBody,"role":obj.ModelRole,
             "color":[round(v*255) for v in color],"opacity":opacity}
            for obj,shape,color,opacity in camera_shapes]
        if markings:
            marking=write_mesh(markings,link["id"]+"_marking")
            marking["color"]=[15,45,75]
            result["links"][link["id"]]["marking"]=marking
    (package_dir/"config/geometry.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    App.closeDocument(doc.Name)


def validate(doc,spec,output,report_path=None):
    baseline=json.loads((ROOT/"model/baseline.json").read_text(encoding="utf-8"))
    baseline_match=baseline["spec_sha256"]==model.digest(model.SPEC)
    refs=json.loads((ROOT/"exports/Laborarm_6R_Konzept_A01.freecad-source.json").read_text(encoding="utf-8")) if baseline_match else {"bodies":[]}
    expected_bodies={b["name"]:b for b in refs["bodies"]}
    report={"spec_sha256":model.digest(model.SPEC),"backend":"Native structure and motor plates; registered vendor housing/output STEP","freecad_version":App.Version(),
            "units":spec["units"],"baseline_comparison":baseline_match,"geometry":[],"poses":[],"parameter_change":{},"scenarios":[],"full_motion_envelope_checked":False,
            "cameras":robot_cameras.audit(spec),"excluded_collision_roles":["viewing_cone"]}
    for obj in motion.features(doc):
        ref=expected_bodies.get(obj.SourceBody)
        shape=obj.Shape
        center=App.Vector()
        for solid in shape.Solids: center=center.add(solid.CenterOfMass.multiply(solid.Volume / shape.Volume))
        world_center=motion.global_placement(doc.getObject(obj.RigidLink)).multVec(center)
        report["geometry"].append({"body":obj.SourceBody,"rigid_link":obj.RigidLink,"role":obj.ModelRole,"valid":shape.isValid(),"solids":len(shape.Solids),
                                  "world_center_of_mass_mm":list(world_center),
                                  "center_of_mass_mm":list(center),"volume_mm3":shape.Volume,
                                  "com_error_mm":(center-App.Vector(*ref["center_of_mass"])).Length if ref else None,
                                  "relative_volume_error":abs(shape.Volume-ref["volume_mm3"])/ref["volume_mm3"] if ref else None})
    poses=[model.home(spec)]
    for axis in range(6):
        q=model.home(spec); q[axis]+=5; poses.append(q)
    def pose_error(q,overrides=None):
        motion.set_angles(doc,q); expected=model.forward(spec,q,overrides); error=0.
        for name,t in expected.items():
            actual=motion.global_placement(doc.getObject(name))
            for point in [[0,0,0],[17,0,0],[0,23,0],[0,0,31]]:
                error=max(error,(actual.multVec(App.Vector(*point))-App.Vector(*model.transform(t,point))).Length)
        for link,camera in robot_cameras.cameras(spec):
            camera_parameters=model.parameters(spec,overrides)
            target=model.multiply(expected[link],model.frame({"frame":camera["frame"]},camera_parameters))
            actual=motion.global_placement(doc.getObject(camera["id"]+"_optical"))
            for point in [[0,0,0],[11,0,0],[0,13,0],[0,0,17]]:
                error=max(error,(actual.multVec(App.Vector(*point))-App.Vector(*model.transform(target,point))).Length)
            cone=doc.getObject(camera["id"]+"_view_CONE")
            apex=motion.global_placement(cone).multVec(App.Vector(0,0,model.evaluate(camera["view"]["range_mm"],camera_parameters)))
            error=max(error,(apex-App.Vector(*model.transform(target,[0,0,0]))).Length)
        return error
    collision_cache={}
    for q in poses:
        error=pose_error(q)
        collisions=motion.check_collisions(doc,collision_cache)
        report["poses"].append({"angles_deg":q,"max_probe_error_mm":error,"overlaps":collisions["overlaps"]})
    variant_upper=model.parameters(spec)["upper_len"]+20
    doc.ModelParameters.upper_len=variant_upper; doc.recompute()
    report["parameter_change"]={"upper_len_mm":variant_upper,"max_probe_error_mm":pose_error(model.home(spec),{"upper_len":variant_upper}),
                                "elbow_anchor_z_mm":doc.J3_Anchor.Placement.Base.z,
                                "wrist_anchor_z_mm":doc.J5_Anchor.Placement.Base.z}
    variant_values=model.parameters(spec,{"upper_len":variant_upper})
    placements=[]
    for link in model.expanded(spec)["links"]:
        for op in link["recipe"]:
            if op["action"]=="create" and op["primitive"]["kind"]=="vendor_step":
                obj=next(o for o in motion.features(doc) if o.SourceBody==op["body"])
                expected=[model.evaluate(v,variant_values) for v in op["primitive"]["origin"]]
                placements.append({"body":op["body"],"origin_error_mm":(obj.Placement.Base-App.Vector(*expected)).Length})
    report["parameter_change"]["vendor_placements"]=placements
    doc.ModelParameters.upper_len=model.parameters(spec)["upper_len"]; doc.recompute()
    camera_variants=[]
    if robot_cameras.cameras(spec):
        for parameter,increment in [("cam_tip_offset_x",10),("cam_tip_range",20),("cam_tip_body_w",5)]:
            original=model.parameters(spec)[parameter]
            setattr(doc.ModelParameters,parameter,original+increment); doc.recompute()
            camera_variants.append({"parameter":parameter,"value_mm":original+increment,
                "max_camera_and_link_probe_error_mm":pose_error(model.home(spec),{parameter:original+increment})})
            setattr(doc.ModelParameters,parameter,original); doc.recompute()
    report["camera_parameter_changes"]=camera_variants
    collision_cache.clear()
    for scenario in spec["scenarios"]:
        results=[]
        for sample in model.sample_scenario(spec,scenario["id"]):
            motion.set_angles(doc,sample["angles_deg"])
            collisions=motion.check_collisions(doc,collision_cache)
            results.append({"step":sample["step"],"time_s":sample["time_s"],"overlaps":collisions["overlaps"]})
        report["scenarios"].append({"id":scenario["id"],"samples":results,"continuous_collision_checked":False})
    motion.set_angles(doc,model.home(spec)); doc.recompute(); doc.save()
    report["screw_head_clearance"]=check_servo_head_clearance(doc,spec)
    x6_checks=[c for c in report["screw_head_clearance"]["checks"] if c["part"]=="RMD-X6-P20-60-E"]
    report["x6_screw_head_clearance"]={**report["screw_head_clearance"],"checks":x6_checks,"passed":len(x6_checks)==22 and all(not c["overlaps"] for c in x6_checks)}
    report["retained_pin_clearance"]=check_retained_pins(doc,spec)
    expected_count=sum(op["action"]=="create" for link in model.expanded(spec)["links"] for op in link["recipe"])
    report["passed"]=(len(report["geometry"])==expected_count and all(x["valid"] and x["solids"]==1 and (x["com_error_mm"] is None or x["com_error_mm"]<0.01) and (x["relative_volume_error"] is None or x["relative_volume_error"]<0.001) for x in report["geometry"])
                       and all(x["max_probe_error_mm"]<1e-6 and not x["overlaps"] for x in report["poses"])
                       and report["parameter_change"]["max_probe_error_mm"]<1e-6
                       and all(x["origin_error_mm"]<1e-6 for x in placements)
                       and all(x["max_camera_and_link_probe_error_mm"]<1e-6 for x in camera_variants)
                       and all(not sample["overlaps"] for scenario in report["scenarios"] for sample in scenario["samples"])
                       and report["screw_head_clearance"]["passed"] and report["retained_pin_clearance"]["passed"])
    report["model_sha256"]=model.digest(output)
    report_path=Path(report_path) if report_path else ROOT/"docs/neutral-freecad-validation.json"
    report_path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    if not report["passed"]: raise AssertionError("See "+str(report_path))
    return report


def run(output=None,report_path=None):
    spec=model.load(); output=Path(output) if output else ROOT/"cad/generated"/(spec["id"]+".FCStd")
    doc=App.openDocument(str(output)) if output.exists() else build(spec,output)
    if doc.Controller.SpecSHA256!=model.digest(model.SPEC):
        raise ValueError("Generated file belongs to another specification; use a new output path")
    result=validate(doc,spec,output,report_path)
    print("Neutral FreeCAD build/validation:",result["passed"],flush=True)
    App.closeDocument(doc.Name)


if __name__=="__main__":
    # Keep application initialization away from the __main__ CAD namespace.
    import build_neutral_freecad
    import sys
    build_neutral_freecad.run(*sys.argv[1:])
