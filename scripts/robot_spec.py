"""Small CAD-independent robot/recipe/scenario model. No CAD imports or eval()."""
from pathlib import Path
import ast
import hashlib
import json
import math
import operator
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "model/robot.json"
OPS = {ast.Add:operator.add, ast.Sub:operator.sub, ast.Mult:operator.mul, ast.Div:operator.truediv}
# Font-independent bold outline glyphs. Coordinates have a cap height of 10.
GLYPHS={
    "U":[[[0,10],[2,10],[2,2],[4,2],[4,10],[6,10],[6,0],[0,0]]],
    "M":[[[0,0],[0,10],[2,10],[3,6],[4,10],[6,10],[6,0],[4,0],[4,6],[3,3],[2,6],[2,0]]],
    "R":[[[0,0],[0,10],[4,10],[6,8],[6,6],[4.5,4.5],[6,0],[3.8,0],[2,4.5],[2,0]],[[2,6],[4,6],[4,8],[2,8]]],
}


def expanded(spec):
    """Lower semantic features to portable construction operations."""
    import copy
    from robot_components import lower
    from robot_cameras import lower as lower_cameras
    result=lower_cameras(lower(spec)); p=parameters(spec)
    for link in result["links"]:
        operations=[]
        for op in link["recipe"]:
            if op["action"]!="label": operations.append(op); continue
            scale=evaluate(op["height"],p)/10
            if scale<=0 or evaluate(op["depth"],p)<=0: raise ValueError("Label height and depth must be positive")
            tracking=op.get("tracking",2)*scale
            width=len(op["text"])*6*scale+max(0,len(op["text"])-1)*tracking
            for i,char in enumerate(op["text"]):
                if char not in GLYPHS: raise ValueError("No portable glyph for "+char)
                name=op["id"]+"_"+char+"_"+str(i)
                offset=i*(6*scale+tracking)-width/2
                origin=["(%s) + (%s)"%(value,offset*axis) for value,axis in zip(op["origin"],op["u_axis"])]
                primitive={"kind":"polygon_prism","origin":origin,"u_axis":op["u_axis"],"v_axis":op["v_axis"],
                           "loops":[[[x*scale,y*scale] for x,y in loop] for loop in GLYPHS[char]],"depth":op["depth"]}
                operations.append({"id":name,"action":"create","body":name,"role":"marking","primitive":primitive})
                result["body_appearances"][name]={"color":op["color"],"opacity":1}
        link["recipe"]=operations
    return result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate(expression, parameters):
    if isinstance(expression, bool):
        raise ValueError("Boolean is not a quantity")
    if isinstance(expression, (int, float)):
        result = float(expression)
    else:
        def visit(node):
            if isinstance(node, ast.Expression): return visit(node.body)
            if isinstance(node, ast.Constant) and type(node.value) in (int,float): return float(node.value)
            if isinstance(node, ast.Name): return parameters[node.id]
            if isinstance(node, ast.BinOp) and type(node.op) in OPS: return OPS[type(node.op)](visit(node.left), visit(node.right))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd,ast.USub)): return visit(node.operand) * (-1 if isinstance(node.op,ast.USub) else 1)
            raise ValueError("Unsupported expression: " + str(expression))
        result = visit(ast.parse(expression, mode="eval"))
    if not math.isfinite(result): raise ValueError("Non-finite quantity")
    return result


def parameters(spec, overrides=None):
    definitions = spec["parameters"]
    overrides = overrides or {}
    if set(overrides) - set(definitions): raise ValueError("Unknown parameter override")
    pending = {name: overrides.get(name, p["expression"]) for name,p in definitions.items()}
    result = {}
    while pending:
        progress = False
        for name, expression in list(pending.items()):
            try: result[name] = evaluate(expression, result)
            except KeyError: continue
            del pending[name]
            progress = True
        if not progress: raise ValueError("Undefined or cyclic parameters: " + str(list(pending)))
    return result


def load(path=SPEC, parameter_overrides=None):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if parameter_overrides:
        # A scene may select a dimensional variant without duplicating the arm.
        parameters(spec, parameter_overrides)  # Reject unknown/cyclic quantities.
        for name,value in parameter_overrides.items():
            spec['parameters'][name]['expression']=str(value)
    if spec["format"] != "solidcraftbot.robot/1": raise ValueError("Unsupported model format")
    if spec["units"] != {"length":"mm","angle":"deg","time":"s"}: raise ValueError("Unsupported units")
    if "mobile_base" in spec:
        reference=spec["mobile_base"]
        if set(reference)!={"source"} or not re.fullmatch(r"model/[A-Za-z0-9_.-]+\.shared\.json",reference["source"]):
            raise ValueError("Invalid external mobile-base source reference")
        if not (ROOT/reference["source"]).is_file(): raise ValueError("Missing external mobile-base source")
    import copy
    source_spec=copy.deepcopy(spec)
    p = parameters(spec)
    spec = expanded(spec)
    link_ids = [link["id"] for link in spec["links"]]
    if len(set(link_ids)) != len(link_ids): raise ValueError("Duplicate link IDs")
    if len(link_ids) != 7 or len(spec["joints"]) != 6: raise ValueError("Project requires one six-axis arm")
    if sum(bool(link["grounded"]) for link in spec["links"]) != 1 or not spec["links"][0]["grounded"]: raise ValueError("Grounded root required")
    operation_ids, bodies = set(), set()
    for link in spec["links"]:
        local = set()
        for op in link["recipe"]:
            if op["id"] in operation_ids: raise ValueError("Duplicate operation ID")
            operation_ids.add(op["id"])
            if op["action"] == "create":
                if op["body"] in bodies: raise ValueError("Duplicate body ID")
                bodies.add(op["body"]); local.add(op["body"])
                if op["role"] not in {"structure","interface","placeholder_envelope","marking","vendor_housing","vendor_output","mount_plate","locating_pin","camera_envelope","camera_mount","viewing_cone"}: raise ValueError("Unknown body role")
            elif op["action"] in {"subtract","union","translate"}:
                if not op["targets"] or set(op["targets"]) - local: raise ValueError("Operation crosses link or references missing body")
            else: raise ValueError("Unsupported operation: " + op["action"])
            if op["action"] == "translate":
                for value in op["vector"]: evaluate(value,p)
            else:
                primitive = op["primitive"]
                if primitive["kind"]=="vendor_step":
                    for v in primitive["origin"]: evaluate(v,p)
                    continue
                dimensions = primitive["size"] if primitive["kind"] == "box" else [primitive["radius"],primitive["length"]] if primitive["kind"] in {"cylinder","cone"} else [primitive["depth"]] if primitive["kind"]=="polygon_prism" else None
                if dimensions is None: raise ValueError("Unsupported primitive")
                if any(evaluate(v,p) <= 0 for v in dimensions): raise ValueError("Non-positive primitive dimension")
                if primitive["kind"]=="cone" and evaluate(primitive["top_radius"],p)<0: raise ValueError("Negative cone top radius")
                if "axis" in primitive:
                    axis=primitive["axis"]
                    if len(axis)!=3 or abs(sum(v*v for v in axis)-1)>1e-9: raise ValueError("Primitive axis must be a unit vector")
                if primitive["kind"]=="box" and "axis" in primitive:
                    from robot_components import axes
                    axes(primitive)
                for v in primitive["origin"]: evaluate(v,p)
    for i,j in enumerate(spec["joints"]):
        if j["parent"] != link_ids[i] or j["child"] != link_ids[i+1] or j["kind"] != "revolute": raise ValueError("Version 1 supports a serial revolute chain")
        lo,hi = j["limits_deg"]
        if not lo <= j["home_deg"] <= hi: raise ValueError("Home outside limits")
        for v in j["frame"]["origin"]: evaluate(v,p)
        z,x = j["frame"]["axis"],j["frame"]["x"]
        if abs(sum(v*v for v in z)-1)>1e-9 or abs(sum(v*v for v in x)-1)>1e-9 or abs(sum(a*b for a,b in zip(x,z)))>1e-9: raise ValueError("Frame axes must be orthonormal")
    if "services" in spec:
        from robot_services import audit
        audit(spec)
    if "vendor_library" in spec:
        from robot_components import audit as component_audit
        component_audit(source_spec)
    return source_spec


def identity(): return [[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]]
def multiply(a,b): return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
def inverse(t):
    r=identity()
    for i in range(3):
        for j in range(3): r[i][j]=t[j][i]
        r[i][3]=-sum(t[j][i]*t[j][3] for j in range(3))
    return r
def transform(t,p): return [sum(t[i][j]*p[j] for j in range(3))+t[i][3] for i in range(3)]
def frame(joint,p):
    f=joint["frame"]; x,z=f["x"],f["axis"]
    y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]]
    m=identity()
    for i in range(3): m[i]=[x[i],y[i],z[i],evaluate(f["origin"][i],p)]
    return m


def home(spec): return [j["home_deg"] for j in spec["joints"]]


def forward(spec, angles=None, overrides=None):
    p=parameters(spec,overrides); q=home(spec) if angles is None else angles
    if len(q)!=6: raise ValueError("Six angles required")
    t=identity(); result={spec["links"][0]["id"]:t}
    for j,angle in zip(spec["joints"],q):
        if not math.isfinite(angle): raise ValueError("Non-finite angle")
        f=frame(j,p); r=identity(); c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
        r[0][0],r[0][1],r[1][0],r[1][1]=c,-s,s,c
        t=multiply(multiply(multiply(t,f),r),inverse(f)); result[j["child"]]=t
    return result


def sample_scenario(spec, scenario_id):
    scenario=next(s for s in spec["scenarios"] if s["id"]==scenario_id)
    if scenario["interpolation"]!="joint_linear": raise ValueError("Unsupported motion interpolation")
    ids=[j["id"] for j in spec["joints"]]; previous=None; time_s=0.; samples=[]
    for step in scenario["steps"]:
        if set(step["joints_deg"])!=set(ids): raise ValueError("Scenario must specify exactly six known axes")
        current=[float(step["joints_deg"][name]) for name in ids]
        if not math.isfinite(step["duration_s"]) or step["duration_s"]<0: raise ValueError("Invalid duration")
        for j,value in zip(spec["joints"],current):
            if not math.isfinite(value) or not j["limits_deg"][0]<=value<=j["limits_deg"][1]: raise ValueError(step["id"]+": joint limit "+j["id"])
        count=1 if previous is None else max(1,math.ceil(max(abs(a-b) for a,b in zip(previous,current))/scenario["checks"]["sampled_collision_step_deg"]))
        if previous is not None and step["duration_s"]==0 and previous!=current: raise ValueError("Nonzero motion requires duration")
        for i in range(1,count+1):
            u=i/count; q=current if previous is None else [a+(b-a)*u for a,b in zip(previous,current)]
            pose=forward(spec,q); point=transform(pose[spec["flange_reference"]["link"]],[evaluate(v,parameters(spec)) for v in spec["flange_reference"]["point"]])
            samples.append({"step":step["id"],"time_s":time_s+step["duration_s"]*u,"angles_deg":q,"flange_mm":point})
        previous=current; time_s+=step["duration_s"]
    return samples


def control_data(spec):
    p=parameters(spec)
    return {"joints":[{"name":j["id"],"values":[{"value":j["home_deg"],"limits":j["limits_deg"]}]} for j in spec["joints"]],
            "components":[{"name":l["id"],"id":l["id"]} for l in spec["links"]],
            "flange_reference_mm":[evaluate(v,p) for v in spec["flange_reference"]["point"]]}


def appearances(spec):
    spec=expanded(spec)
    return {"appearances":{"components":{l["id"]:l["appearance"] for l in spec["links"]},"bodies":spec["body_appearances"]}}


def solidcraft_commands(spec, root_offset=None):
    spec=expanded(spec)
    p=parameters(spec); steps=[]
    def add(command,**params): steps.append({"command":command,"params":params})
    for name, definition in spec["parameters"].items():
        add("parameters.add",name=name,expression=str(definition["expression"]),unit="mm")
    for link in spec["links"]:
        for op in link["recipe"]:
            if op["action"]=="translate":
                add("solid.move",bodies=op["targets"],translate=op["vector"]); continue
            primitive=op["primitive"]
            if primitive["kind"]=="vendor_step":
                matrix=frame({"frame":primitive},p)
                # Imported STEP bodies live in an oriented component. A later
                # body translation would use that local frame, not the arm frame.
                if root_offset is not None:
                    for i in range(3):matrix[i][3]+=root_offset[i]
                add("file.insert_step",path=str(ROOT/primitive["step"]),name=op["id"]+"_import",matrix=matrix)
                add("body.rename",body=primitive["import_body_name"],name=op["body"])
                continue
            args={"name":op["id"],"operation":{"create":"new","subtract":"cut","union":"join"}[op["action"]]}
            if op["action"]=="create": args["body_name"]=op["body"]
            else: args["targets"]=op["targets"]
            if primitive["kind"]=="polygon_prism":
                add("sketch.create",name=op["id"]+"_profile",plane={"origin":[evaluate(v,p) for v in primitive["origin"]],"x_dir":primitive["u_axis"],"y_dir":primitive["v_axis"]})
                for loop in primitive["loops"]: add("sketch.line",points=loop,closed=True)
                add("sketch.finish")
                add("solid.extrude",distance=primitive["depth"],**args)
                continue
            if primitive["kind"]=="box":
                args.update(zip(["length","width","height"],primitive["size"])); args["corner"]=[0,0,0] if "axis" in primitive else primitive["origin"]
            else: args.update(radius=primitive["radius"],height=primitive["length"],base=primitive["origin"],axis=primitive["axis"])
            if primitive["kind"]=="cone": args["top_radius"]=primitive["top_radius"]
            add("solid."+primitive["kind"],**args)
            if primitive["kind"]=="box" and "axis" in primitive:
                from robot_cameras import axis_angle
                axis,angle=axis_angle(primitive)
                if abs(angle)>1e-10: add("solid.move",bodies=[op["body"]],axis=axis,angle=str(angle)+" deg")
                add("solid.move",bodies=[op["body"]],translate=primitive["origin"])
    if root_offset is not None:
        add("solid.move", bodies=[op["body"] for link in spec["links"] for op in link["recipe"] if op["action"]=="create" and op["primitive"]["kind"]!="vendor_step"], translate=root_offset)
    for link in spec["links"]:
        bodies=[op["body"] for op in link["recipe"] if op["action"]=="create"]
        add("component.create",name=link["id"],parent="root",activate=False,grounded=link["grounded"])
        add("component.move_bodies",bodies=bodies,component=link["id"])
        add("appearance.assign",components=[link["id"]],color=link["appearance"]["color"],opacity=link["appearance"]["opacity"])
    for name,look in spec["body_appearances"].items(): add("appearance.assign",bodies=[name],color=look["color"],opacity=look["opacity"])
    for j in spec["joints"]:
        f=j["frame"]; point=[evaluate(v,p) for v in f["origin"]]
        if root_offset is not None: point=[a+b for a,b in zip(point,root_offset)]
        origin={"origin":point,"z":f["axis"],"x":f["x"]}
        add("joint.create",type="revolute",name=j["id"],a={"occurrence":j["parent"],"frame":origin},b={"occurrence":j["child"],"frame":origin},flip=True,values=[0],limits=[j["limits_deg"]],quiet=True)
    for j in spec["joints"]: add("joint.drive",joint=j["id"],value=j["home_deg"],quiet=True)
    add("browser.visibility",folder="joints",visible=False)
    return steps


if __name__=="__main__":
    spec=load(); out=ROOT/"exports/generated"; out.mkdir(parents=True,exist_ok=True)
    (out/"solidcraft.commands.json").write_text(json.dumps({"spec_sha256":digest(SPEC),"commands":solidcraft_commands(spec)},indent=2)+"\n",encoding="utf-8")
    (out/"scenario-trace.json").write_text(json.dumps({"spec_sha256":digest(SPEC),"samples":sample_scenario(spec,"base_sweep_return")},indent=2)+"\n",encoding="utf-8")
    print("Neutral model validated; SolidCraft recipe and scenario trace compiled")
