"""Drive each axis out and back in an isolated CLI session; check the solver."""
from pathlib import Path
import json
import subprocess

def check(spec,model_path,output_dir,cli):
    output_dir=Path(output_dir); commands=[]
    for joint in spec["joints"]:
        for value in [joint["home_deg"]+5,joint["home_deg"]]:
            commands.append({"command":"joint.drive","params":{"joint":joint["id"],"value":value}})
    commands.append({"command":"joint.inspect","params":{}})
    script=output_dir/"solidcraft-joints.commands.json"
    raw=output_dir/"solidcraft-joint-results.json"
    script.write_text(json.dumps({"commands":commands},indent=2)+"\n",encoding="utf-8")
    subprocess.run([cli,"run",str(script),"--in",str(model_path),"--results","--json-out",str(raw)],check=True)
    data=json.loads(raw.read_text(encoding="utf-8")); drives=data[:-1]; joints=data[-1]["joints"]
    passed=(len(drives)==12 and all(d.get("moved") and not d.get("reason") for d in drives)
            and len(joints)==6 and all(j["a"]["resolves"] and j["b"]["resolves"] and not j["errors"] and not j["conflicts"] for j in joints))
    report={"passed":passed,"method":"Each axis +5 degrees from home and back; isolated SolidCraft CLI",
            "drives":12,"joints":[{"name":j["name"],"errors":j["errors"],"conflicts":j["conflicts"],"origins_resolve":j["a"]["resolves"] and j["b"]["resolves"]} for j in joints],
            "raw_results":raw.name,"full_motion_envelope_checked":False}
    destination=output_dir/"solidcraft-joint-check.json"
    destination.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    if not passed:raise AssertionError("SolidCraft joint check failed: "+str(destination))
    return destination
