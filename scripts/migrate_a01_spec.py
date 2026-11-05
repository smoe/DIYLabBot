"""One-time migration. Generators themselves never read SolidCraft or STEP files."""
from pathlib import Path
import hashlib
import json
import math
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
source_path = ROOT / "cad/Laborarm_6R_Konzept_A01.solidcraft"
if not source_path.exists():
    raise SystemExit("The original CAD files were retired at the owner's request. Edit model/robot.json; generators use that source directly.")
source = json.loads(zipfile.ZipFile(source_path).read("document.json"))


def expression(value):
    if isinstance(value, str):
        return re.sub(r"\s+mm\b", "", value)
    return 0 if abs(value) < 1e-10 else value


links = []
body_links = {}
for component in source["components"]:
    link = {"id": component["name"], "grounded": component["id"] == 1,
            "appearance": source["appearances"]["components"][str(component["id"])], "recipe": []}
    for f in source["features"]:
        if f.get("operation") == "new_body" and f.get("component") == component["id"]:
            body_links[f["body_names"][0]] = link["id"]
    links.append(link)
by_id = {link["id"]: link for link in links}
components = {c["id"]: c["name"] for c in source["components"]}
for f in source["features"]:
    if f["type"] == "move":
        target_link_ids = {body_links[b] for b in f["bodies"]}
        assert len(target_link_ids) == 1
        operation = {"id": "op_%03d" % f["id"], "action": "translate", "targets": f["bodies"],
                     "vector": [expression(v) for v in f["translate"]]}
        link_id = target_link_ids.pop()
    else:
        link_id = components[f["component"]]
        primitive = ({"kind": "box", "origin": [expression(v) for v in f["corner"]],
                      "size": [expression(f[k]) for k in ["length", "width", "height"]]}
                     if f["type"] == "box" else
                     {"kind": "cylinder", "origin": [expression(v) for v in f["base"]],
                      "axis": [expression(v) for v in f["axis"]],
                      "radius": expression(f["radius"]), "length": expression(f["height"])})
        operation = {"id": "op_%03d" % f["id"], "action": {"new_body":"create", "cut":"subtract", "join":"union"}[f["operation"]],
                     "primitive": primitive}
        if f["operation"] == "new_body":
            name = f["body_names"][0]
            operation["body"] = name
            operation["role"] = "placeholder_envelope" if "envelope" in name.lower() else "interface" if name == "Bare_tool_flange" else "structure"
        else:
            operation["targets"] = f["participants"]
    by_id[link_id]["recipe"].append(operation)

origins = [[0,0,60], [0,52,"shoulder_z"], [0,34,"elbow_z"],
           [0,0,"roll_z + 24"], [0,32,"wrist_z"], [0,0,"flange_z + 10"]]
axes = [[0,0,1],[0,1,0],[0,1,0],[0,0,1],[0,1,0],[0,0,1]]
xs = [[1,0,0],[0,0,-1],[0,0,-1],[0,1,0],[0,0,-1],[0,1,0]]
joints = []
for i, j in enumerate(source["assembly"]["joints"]):
    joints.append({"id": j["name"], "kind": "revolute", "parent": links[i]["id"], "child": links[i+1]["id"],
                   "frame": {"origin": origins[i], "axis": axes[i], "x": xs[i]},
                   "home_deg": round(math.degrees(j["values"][0]), 10),
                   "limits_deg": [round(math.degrees(v), 10) for v in j["limits"][0]]})
home = {j["id"]: j["home_deg"] for j in joints}
sweep = dict(home)
sweep[joints[0]["id"]] += 5
model = {"format": "solidcraftbot.robot/1", "id": "Laborarm_6R_A01_Neutral",
         "units": {"length": "mm", "angle": "deg", "time": "s"},
         "status": "concept_not_for_manufacture", "parameters": {p["name"]: {"unit":"mm", "expression":expression(p["expr"])} for p in source["params"]},
         "links": links, "joints": joints, "body_appearances": source["appearances"]["bodies"],
         "flange_reference": {"link":"L6_BareFlange", "point":[0,0,"flange_z + 15"]},
         "profiles": {"motion": {"collision_geometry":"recipe_solids", "tooth_contact":False, "fluid_physics":False,
                                  "notes":"Current recipes reproduce A01 concept solids. Drive bodies remain unselected envelopes."}},
         "scenarios": [{"id":"base_sweep_return", "profile":"motion", "interpolation":"joint_linear",
                        "steps":[{"id":"home", "duration_s":0, "joints_deg":home},
                                 {"id":"sweep", "duration_s":2, "joints_deg":sweep},
                                 {"id":"return", "duration_s":2, "joints_deg":home}],
                        "checks":{"joint_limits":True,"sampled_collision_step_deg":1,"full_motion_envelope":False}}],
         "provenance": {"migrated_from":"cad/Laborarm_6R_Konzept_A01.solidcraft", "sha256":hashlib.sha256(source_path.read_bytes()).hexdigest()},
         "limitations":["No selected drives, load rating, stiffness or safety claim", "No pipette adapter; generic flange only",
                         "No tooth contact or fluid simulation", "Sampled collision checking is not continuous collision checking"]}
destination = ROOT / "model/robot.json"
destination.parent.mkdir(parents=True, exist_ok=True)
if destination.exists():
    raise FileExistsError("Canonical model already exists; migration will not replace it")
destination.write_text(json.dumps(model, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
print(destination)
