"""Register and simplify downloaded vendor geometry using FreeCAD core only.

The canonical part frame is the output face, +Z pointing out of the servo.
Exterior case pieces and the output flange are identified geometrically,
not by unstable face/solid indices. Originals remain untouched.
"""
import FreeCAD as App
import Part
from pathlib import Path
import hashlib
import json
import math
import re
from servo_mounting_design import analyse
from robot_components import exterior_sections

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {
    "RMD-X2-P28-7-E": {"radius":22, "boss":15.5, "front":-2, "depth":63.5,
        "matrix":[[1,0,0,0],[0,0,1,0],[0,-1,0,-15.5],[0,0,0,1]],
        "housing_pcd":38, "output_pcd":25, "housing_count":4, "output_count":4,
        "interface_spec":"model/x2-mounting-interface.json", "evidence_revision":"interface-check-fit-v1.json"},
    "RMD-X4-P36-36-E-L": {"radius":27.5, "boss":17.5, "front":-3, "depth":61,
        "matrix":[[1,0,0,0],[0,-1,0,0],[0,0,-1,-28.5],[0,0,0,1]],
        "housing_pcd":48, "output_pcd":26, "housing_count":6, "output_count":6,
        "interface_spec":"model/x4-mounting-interface.json", "evidence_revision":"interface-check-fit-v1.json"},
    "RMD-X6-P20-60-E": {"radius":40, "boss":26.5, "front":-3, "depth":67.5,
        "matrix":[[1,0,0,0],[0,0,-1,0],[0,1,0,-67.5],[0,0,0,1]],
        "interface_spec":"model/x6-mounting-interface.json", "derivative_revision":"registered-v2"}
}

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def leaves(shape):
    if shape.ShapeType == "Compound":
        for child in shape.childShapes(): yield from leaves(child)
    else: yield shape

def prepare():
    manifest=json.loads((ROOT/"cad/vendor/myactuator/manifest.json").read_text(encoding="utf-8"))
    check=json.loads((ROOT/"cad/vendor/myactuator/geometry-check.json").read_text())
    library={"format":"solidcraftbot.servo-library/1", "units":"mm", "frame":"output face; +Z outwards",
             "status":"registered_concept_interfaces_not_for_manufacture", "parts":{}}
    for record in manifest["models"]:
        name=record["part"]; cfg=dict(CONFIG[name]); report=next(r for r in check["models"] if r["part"]==name)
        interface_spec=None
        if "interface_spec" in cfg:
            interface_spec=json.loads((ROOT/cfg["interface_spec"]).read_text(encoding="utf-8"))
            if interface_spec["part"]!=name or interface_spec["units"]!="mm":raise ValueError("Wrong interface specification")
            if sha(ROOT/interface_spec["drawing"])!=interface_spec["drawing_sha256"]:raise ValueError("Changed interface drawing")
            for section in ["housing","output"]:
                entry=interface_spec[section]
                cfg[section+"_pcd"]=entry["bolt_circle_mm"]
                cfg[section+"_count"]=entry["fastener_count"]
                cfg[section+"_thread"]=entry["vendor_thread"]
                cfg[section+"_hole_radius"]=entry.get("vendor_counterbore_diameter_mm",entry["cad_thread_core_diameter_mm"])/2
        source=ROOT/report["cad_reference"]
        if sha(source)!=report["cad_reference_sha256"]: raise ValueError("Changed reference: "+name)
        original=Part.read(str(source)); original.transformShape(App.Matrix(*[v for row in cfg["matrix"] for v in row]),True)
        solids=[]
        for shape in leaves(original):
            if shape.ShapeType=="Shell" and shape.isClosed(): shape=Part.makeSolid(shape)
            if shape.ShapeType=="Solid" and shape.isValid(): solids.append(shape)
        measurements=[]
        for i,solid in enumerate(solids):
            b=solid.BoundBox
            measurements.append({"name":i,"bbox":{"min":[b.XMin,b.YMin,b.ZMin],"max":[b.XMax,b.YMax,b.ZMax]},
                                 "volume_mm3":solid.Volume,"center_of_mass":list(solid.CenterOfMass),"closed":solid.isClosed()})
        partition=exterior_sections({"part":name,"nominal_radius_mm":cfg["radius"],"output_boss_radius_mm":cfg["boss"],
            "interfaces":{"housing":{"z_mm":cfg["front"],**({"locating_pins":interface_spec["housing"]["locating_pins"]}
            if interface_spec and "locating_pins" in interface_spec["housing"] else {})}}},measurements)
        case=[solids[i] for i in partition["housing"]];pins=[solids[i] for i in partition["pins"]];output=[solids[i] for i in partition["output"]]
        if pins:pin_spec=interface_spec["housing"]["locating_pins"]
        housing=case[0].multiFuse(case[1:]).removeSplitter() if len(case)>1 else case[0]
        if not housing.isValid() or len(housing.Solids)!=1: raise ValueError("Housing union needs review: "+name)
        folder=source.parent/cfg.get("derivative_revision","registered-v1"); folder.mkdir(exist_ok=True)
        part={"part":name,"bundle_revision":record["revision"],"source":report["cad_reference"],
              "source_sha256":sha(source),"vendor_to_output_frame":cfg["matrix"],"nominal_radius_mm":cfg["radius"],
              "output_boss_radius_mm":cfg["boss"],"depth_mm":cfg["depth"],"interfaces":{},"sections":{},
              "physical_sample_verified":False,"manufacturing_released":False,
              "simplification":"Exterior case pieces fused; internal boards, gearing and fasteners omitted; vendor output flange separate",
              "closed_shells_promoted_to_solids":sum(s.ShapeType=="Shell" and s.isClosed() for s in leaves(original))}
        if interface_spec:
            part["interface_spec"]={"path":cfg["interface_spec"],"sha256":sha(ROOT/cfg["interface_spec"])}
            if pins:part["simplification"]+="; two exterior locating sleeves retained on housing"
            part["assembly_design_analysis"]=analyse(interface_spec)
        evidence={"part":name,"source_sha256":sha(source),"method":"Drawing leader assignment checked against coaxial STEP cylindrical faces and locating sleeve solids", "interfaces":{}}
        for section,shape in [("housing",housing),("output",output[0])]:
            path=folder/(section+".step")
            if not path.exists():
                doc=App.newDocument("VendorExport"); obj=doc.addObject("Part::Feature","VendorPiece"); obj.Label="VendorPiece"; obj.Shape=shape
                Part.export([obj],str(path)); App.closeDocument(doc.Name)
            read=Part.read(str(path)); b=read.BoundBox
            if not read.isValid() or len(read.Solids)!=1: raise ValueError("Invalid reference section")
            if abs(read.Volume-shape.Volume)>max(0.001,shape.Volume*1e-5): raise ValueError("Section changed on export")
            product=re.search(r"PRODUCT\('([^']+)'",path.read_text(encoding="latin-1"))
            part["sections"][section]={"step":path.relative_to(ROOT).as_posix(),"sha256":sha(path),"solids":1,"import_body_name":product.group(1),
                "bbox_mm":{"min":[b.XMin,b.YMin,b.ZMin],"max":[b.XMax,b.YMax,b.ZMax]},"faces":len(read.Faces),"volume_mm3":read.Volume}
            z=cfg["front"] if section=="housing" else 0
            pcd=cfg[section+"_pcd"]; radius=cfg[section+"_hole_radius"]
            holes=set()
            # CAD cylinder centres confirm in-plane clocking against the drawing.
            for face in shape.Faces:
                surf=face.Surface
                if isinstance(surf,Part.Cylinder) and abs(surf.Axis.z)>.999 and abs(surf.Radius-radius)<0.01:
                    c=surf.Center
                    if abs(math.hypot(c.x,c.y)-pcd/2)<0.02 and abs(face.BoundBox.ZMax-z)<0.02:
                        holes.add((round(c.x,3),round(c.y,3)))
            if len(holes)!=cfg[section+"_count"]: raise ValueError("Review bolt pattern: %s %s %s"%(name,section,len(holes)))
            part["interfaces"][section]={"z_mm":z,"bolt_circle_mm":pcd,"hole_centres_mm":sorted(holes),
                "vendor_thread":cfg[section+"_thread"],"plate_clearance_diameter_mm":interface_spec[section]["plate_clearance_diameter_mm"] if interface_spec else 3.4,
                "status":"drawing_and_CAD_registered_sample_pending",
                "pilot_fit":None,"fastener_engagement_mm":None,"dowel_fit":None}
            if interface_spec:
                definition=interface_spec[section]; cores=set()
                for face in shape.Faces:
                    surf=face.Surface
                    if isinstance(surf,Part.Cylinder) and abs(surf.Axis.z)>.999 and abs(surf.Radius*2-definition["cad_thread_core_diameter_mm"])<0.01:
                        c=surf.Center; xy=(round(c.x,3),round(c.y,3))
                        if xy in holes:cores.add(xy)
                if cores!=holes:raise ValueError("Thread-core and bolt-pattern centres disagree")
                part["interfaces"][section].update(vendor_thread_depth_mm=definition["vendor_thread_depth_mm"],
                    drawing_pattern_resolved=True,cad_thread_core_diameter_mm=definition["cad_thread_core_diameter_mm"],
                    fastener_design=definition["fastener_design"],plate_head_recess=definition["plate_head_recess"],
                    fastener_stack_analysis=part["assembly_design_analysis"]["fasteners"][section],
                    thread_depth_reference=definition["thread_depth_reference"])
                evidence["interfaces"][section]={"fastener_count":len(holes),"bolt_circle_mm":pcd,"vendor_thread":definition["vendor_thread"],
                    "cad_pattern_bore_diameter_mm":2*radius,"cad_thread_core_diameter_mm":definition["cad_thread_core_diameter_mm"],
                    "matched_thread_core_count":len(cores),"hole_centres_mm":sorted(holes)}
                evidence["interfaces"][section]["cad_thread_core_z_ranges_mm"]=sorted({(round(face.BoundBox.ZMin,4),round(face.BoundBox.ZMax,4)) for face in shape.Faces
                    if isinstance(face.Surface,Part.Cylinder) and abs(face.Surface.Axis.z)>.999
                    and abs(face.Surface.Radius*2-definition["cad_thread_core_diameter_mm"])<.01
                    and (round(face.Surface.Center.x,3),round(face.Surface.Center.y,3)) in holes})
                if section=="housing" and "locating_pins" in definition:
                    centres=sorted((round(pin.CenterOfMass.x,3),round(pin.CenterOfMass.y,3)) for pin in pins)
                    part["interfaces"][section].update(locating_hole_centres_mm=centres,
                        plate_locating_bore_diameter_mm=pin_spec["plate_nominal_bore_diameter_mm"],locating_pins=pin_spec,
                        vendor_counterbore_diameter_mm=definition["vendor_counterbore_diameter_mm"],vendor_counterbore_depth_mm=definition["vendor_counterbore_depth_mm"])
                    evidence["locating_pins"]=[{"centre_mm":[round(pin.CenterOfMass.x,3),round(pin.CenterOfMass.y,3)],
                        "outside_diameter_mm":pin.BoundBox.XLength,"length_mm":pin.BoundBox.ZLength,
                        "z_min_mm":pin.BoundBox.ZMin,"z_max_mm":pin.BoundBox.ZMax,"volume_mm3":pin.Volume} for pin in pins]
                if "locating_bores" in definition:
                    bores=definition["locating_bores"]
                    centres=sorted({(round(f.Surface.Center.x,6),round(f.Surface.Center.y,6)) for f in shape.Faces
                        if isinstance(f.Surface,Part.Cylinder) and abs(f.Surface.Axis.z)>.999
                        and abs(f.Surface.Radius-1.5)<.01 and abs(f.BoundBox.ZMax-z)<.02
                        and abs(2*math.hypot(f.Surface.Center.x,f.Surface.Center.y)-bores["bolt_circle_mm"])<.02})
                    expected=sorted(map(tuple,bores["expected_centres_mm"]))
                    if centres!=expected or len(centres)!=bores["count"]:raise ValueError("Locating bore registration changed: "+name)
                    part["interfaces"][section].update(locating_bores=bores,plate_locating_pins=definition["plate_locating_pins"])
                    evidence["interfaces"][section]["locating_bores"]={"centres_mm":centres,"drawing_depth_mm":bores["depth_mm"],
                        "cad_z_ranges_mm":sorted({(round(f.BoundBox.ZMin,4),round(f.BoundBox.ZMax,4)) for f in shape.Faces
                            if isinstance(f.Surface,Part.Cylinder) and abs(f.Surface.Axis.z)>.999 and abs(f.Surface.Radius-1.5)<.01
                            and (round(f.Surface.Center.x,6),round(f.Surface.Center.y,6)) in centres}),"physical_fit_verified":False}
        part["drawing"]=next(f["path"] for f in record["files"] if f["kind"]=="pdf")
        if interface_spec:
            evidence.update(passed=True,drawing=interface_spec["drawing"],drawing_sha256=interface_spec["drawing_sha256"],
                            interface_spec=part["interface_spec"],assembly_design_analysis=part["assembly_design_analysis"],manufacturing_released=False)
            evidence_path=folder/"interface-check-fit-v1.json";evidence_path.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
            part["interface_check"]={"path":evidence_path.relative_to(ROOT).as_posix(),"sha256":sha(evidence_path)}
        library["parts"][name]=part
        print(name,"registered",{k:v["faces"] for k,v in part["sections"].items()},flush=True)
    destination=ROOT/"cad/vendor/myactuator/component-library.json"
    destination.write_text(json.dumps(library,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    import prepare_servo_components
    prepare_servo_components.prepare()
