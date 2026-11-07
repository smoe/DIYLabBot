"""Historical migration support; direct generation is retired.

Generate review-only CAD commands and a SiLA FDL draft. No hardware control."""
from pathlib import Path
import hashlib
import json
import math
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "model/history/tube-station-c01.legacy.json"
CAD = ROOT / "cad/tube-station-c01"
INTERFACE = ROOT / "interfaces/tube-station-c01"
NS = "http://www.sila-standard.org"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def geometry(spec):
    """Portable primitive recipe with analytically calculated individual volumes."""
    d = spec["dimensions"]
    parts, cuts = [], []

    def box(name, size, center, group="Frame", color="#a5aebc", role="concept structure"):
        parts.append(dict(name=name, kind="box", size=size, center=center, group=group,
                          color=color, role=role, volume_mm3=math.prod(size)))

    def cyl(name, diameter, height, base, axis="Z", group="Frame", color="#a5aebc", role="concept structure"):
        parts.append(dict(name=name, kind="cylinder", diameter=diameter, height=height,
                          base=base, axis=axis, group=group, color=color, role=role,
                          volume_mm3=math.pi * (diameter / 2) ** 2 * height))

    def cut(name, target, kind, removed_volume, **args):
        cuts.append(dict(name=name, target=target, kind=kind, **args))
        next(p for p in parts if p["name"] == target)["volume_mm3"] -= removed_volume

    box("Base", [d["base_length"], d["base_width"], d["base_thickness"]], [0, 0, 4], color="#334155")
    box("IceReservoir", [160, 120, 52], [0, 0, 34], color="#e2e8f0")
    cut("ReservoirCavity", "IceReservoir", "box", 152*112*48, size=[152,112,50], center=[0,0,37])
    box("IceWaterReference", [150, 110, 35], [0, 0, 31.5], color="#76c9ec", role="coolant visualization only")
    cut("CoolantDisplacement", "IceWaterReference", "box", 36*36*3, size=[36,36,6], center=[0,0,49])
    box("ColdInsert", [36,36,48], [0,0,70], color="#38b5c4")
    cut("InsertBore", "ColdInsert", "cylinder", math.pi*6**2*48, diameter=12, height=50, base=[0,0,45], axis="Z")
    for sign, side in [(-1,"Left"),(1,"Right")]:
        box("FramePost"+side,[8,70,80],[sign*88,0,48])
        box("BearingSupport"+side,[8,18,15],[sign*28,7,98.5])
        cyl("BearingEnvelope"+side,14,8,[sign*28-4,7,101],axis="X",color="#64748b",role="unselected bearing envelope")
        cyl("MotorEnvelope"+side,24,28,[-64 if sign<0 else 36,7,101],axis="X",color="#475569",role="unselected geared motor envelope")
        box("RetainerEnvelope"+side,[8,12,8],[sign*11,0,98],color="#df9b37",role="retention mechanism envelope; capture and actuation TBD")
    for y, side in [(-15,"Front"),(15,"Rear")]:
        box("FrameBridge"+side,[180,6,8],[0,y,88])
    box("ControllerEnvelope",[30,38,28],[77,45,102],color="#475569",role="unselected controller envelope")
    box("ClampActuatorEnvelope",[20,14,16],[-40,-18,98],color="#df9b37",role="unselected local retainer actuator envelope")
    box("LidParkingGuideEnvelope",[4,3,4],[9,14,111],color="#c45a9f",role="open-lid guide envelope; retention contact TBD")
    cyl("BlockSensorEnvelope",3,20,[12,4,72],color="#db2777",role="proposed block sensor; no sample temperature claim")
    cyl("ReferenceTube",11,40,[0,0,60],color="#e7b6d6",role="generic tube reference, not purchase geometry")
    cut("TubeInterior","ReferenceTube","cylinder",math.pi*4.5**2*39,diameter=9,height=41,base=[0,0,61],axis="Z")
    cyl("ReferenceCollar",14,2,[0,0,98],color="#e7b6d6",role="generic collar reference")
    cut("CollarOpening","ReferenceCollar","cylinder",math.pi*5.5**2*2,diameter=11,height=4,base=[0,0,97],axis="Z")
    cyl("ReferenceCap",14,2,[0,0,100],group="ReferenceLid",color="#c45a9f",role="generic cap reference")
    box("ReferenceCapTab",[6,4,2],[0,-8,101],group="ReferenceLid",color="#c45a9f",role="generic tab reference")
    box("OpeningRail",[4,22,4],[-17,-2,99],group="Opener",color="#f29938")
    box("OpeningFinger",[20,3,2],[-7,-8.5,99],group="Opener",color="#f29938",role="external tab finger, contact shape TBD")
    box("ClosingRail",[4,20,4],[17,-1,105],group="Closer",color="#6ab67d")
    box("ClosingBridge",[20,5,3],[7,-2,104.5],group="Closer",color="#6ab67d")
    box("ClosingPadEnvelope",[6,5,1.2],[0,-2,102.8],group="Closer",color="#6ab67d",role="compliant pad envelope")
    return parts, cuts


def cad_commands(spec, parts, cuts):
    commands = []
    def add(command, **params):
        commands.append(dict(command=command, params=params))
    for part in parts:
        args = dict(name=part["name"], body_name=part["name"], operation="new")
        if part["kind"] == "box":
            args.update(zip(["length","width","height"],part["size"]))
            args["center"] = part["center"]
        else:
            args.update({k:part[k] for k in ["diameter","height","base","axis"]})
        add("solid."+part["kind"], **args)
        for cut in (c for c in cuts if c["target"] == part["name"]):
            args = dict(name=cut["name"], operation="cut", targets=[part["name"]])
            if cut["kind"] == "box":
                args.update(zip(["length","width","height"],cut["size"]))
                args["center"] = cut["center"]
            else:
                args.update({k:cut[k] for k in ["diameter","height","base","axis"]})
            add("solid."+cut["kind"], **args)
    for group in ["Frame","Opener","Closer","ReferenceLid"]:
        add("component.create",name=group,parent="root",activate=False,grounded=(group=="Frame"))
        add("component.move_bodies",bodies=[p["name"] for p in parts if p["group"]==group],component=group)
    for part in parts:
        add("appearance.assign",bodies=[part["name"]],color=part["color"],opacity=1)
    frame = dict(origin=[0,spec["dimensions"]["pivot_y"],spec["dimensions"]["pivot_z"]],z=[1,0,0],x=[0,1,0])
    limits = {"Opener":[-140,0],"Closer":[-150,3],"ReferenceLid":[-130,0]}
    for group in limits:
        add("joint.create",name=group,type="revolute",a=dict(occurrence="Frame",frame=frame),
            b=dict(occurrence=group,frame=frame),flip=True,values=[0],limits=[limits[group]],quiet=True)
    for group, angle in spec["poses_deg"]["pipetting"].items():
        add("joint.drive",joint=group,value=angle,quiet=True)
    add("browser.visibility",folder="joints",visible=False)
    return commands


def feature_definition():
    ET.register_namespace("", NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root = ET.Element("{"+NS+"}Feature", {"SiLA2Version":"1.1","FeatureVersion":"1.0", "MaturityLevel":"Draft",
        "Originator":"org.solidcraftbot","Category":"samplehandling", "Locale":"en-us",
        "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":NS+" https://gitlab.com/SiLA2/sila_base/raw/master/schema/FeatureDefinition.xsd"})
    def el(parent, tag, text=None):
        node = ET.SubElement(parent,"{"+NS+"}"+tag)
        if text is not None: node.text = str(text)
        return node
    def header(parent, ident, desc):
        el(parent,"Identifier",ident); el(parent,"DisplayName",ident); el(parent,"Description",desc)
    def value(parent, tag, ident, kind, desc):
        node=el(parent,tag); header(node,ident,desc); dt=el(node,"DataType")
        el(dt,"Basic",kind)
        return node
    header(root,"TubeStationControl","C01 proposal for a single cooled snap-cap tube station. No server is implemented. The originator is a provisional project namespace, not a registered standard feature. See docs/tube-station-c01.md for required preconditions and recovery semantics.")
    token=("ControlToken","String","Opaque coordination token scoped to the current BootId; not an authentication credential.")
    command_specs=[
        ("AcquireControl",False,[("ClientId","String","Human-readable controller identity.")],[("ControlToken","String","Exclusive control token; explicit release or local recovery required.")],"Atomically reserve the station for one orchestrator. Repeated acquisition does not replace an existing owner.",["OwnershipConflict","RecoveryRequired"]),
        ("ReleaseControl",False,[token],[],"Release ownership only when empty, motionless and without a robot access grant.",["InvalidControlToken","InvalidState"]),
        ("Heartbeat",False,[token],[],"Refresh the owner watchdog. Loss of heartbeats inhibits new motion and latches recovery; it never authorizes automatic closure or ownership transfer.",["InvalidControlToken"]),
        ("Initialize",True,[token,("ProfileId","String","Only a measured and qualified tube article profile may be selected."),("CoolingRequired","Boolean","When true, pipetting access additionally requires validated cooling readiness.")],[],"Home and park fingers and release the retainer only with an empty nest and independently clear workspace. Reset cooling readiness on configuration change.",["InvalidControlToken","UnknownProfile","InvalidState","WorkspaceNotClear","MotionFault","RecoveryRequired"]),
        ("BeginAccess",False,[token,("Purpose","String","Exactly Loading, Pipetting or Unloading.")],[("AccessToken","String","Unique token for one robot access grant.")],"Require measured standstill, parked fingers, Ready mode and no fault or other grant. Atomically inhibit all station actuation before granting robot entry. Loading requires empty/released; Pipetting requires secured/open and cooling ready if requested; Unloading requires verified closed/released. Exactly one grant may exist.",["InvalidControlToken","InvalidState","CoolingNotReady","RecoveryRequired"]),
        ("EndAccess",False,[token,("AccessToken","String","The active grant returned by BeginAccess.")],[],"Robot reports fully withdrawn. Revoke the grant only after an independent clearance input also confirms the workspace clear. A failed request leaves motion inhibited.",["InvalidControlToken","InvalidAccessToken","WorkspaceNotClear","InvalidState"]),
        ("OpenTube",True,[token],[],"With robot access ended and workspace independently clear: verify tube and orientation, secure it, lift and park the lid, park both fingers and verify the open position. Successful completion means these checks passed.",["InvalidControlToken","InvalidState","WorkspaceNotClear","TubeNotReady","MotionFault","VerificationFailed","RecoveryRequired"]),
        ("CloseTube",True,[token],[],"With robot access ended and workspace independently clear: close with force/displacement limits, verify latching, park fingers, then release retainer. Failure keeps tube retained. Verified latching does not claim a leak-tight seal.",["InvalidControlToken","InvalidState","WorkspaceNotClear","TubeNotReady","MotionFault","VerificationFailed","RecoveryRequired"]),
        ("StopMotion",False,[],[],"Priority controlled-stop request available to any authenticated client, even while a motion command is running. Latch RecoveryRequired and retain current access inhibition and tube support. This is not an emergency stop and does not certify that physical motion has already stopped.",[])
    ]
    for ident, observable, params, responses, desc, errors in command_specs:
        node=el(root,"Command"); header(node,ident,desc); el(node,"Observable","Yes" if observable else "No")
        for args in params: value(node,"Parameter",*args)
        for args in responses: value(node,"Response",*args)
        if errors:
            refs=el(node,"DefinedExecutionErrors")
            for error in errors: el(refs,"Identifier",error)
    prop=el(root,"Property"); header(prop,"Status","One coherent, versioned snapshot. Publish on state change and at the configured period. Sequence increases within BootId. All fields are project-defined, not standard SiLA states."); el(prop,"Observable","Yes")
    struct=el(el(prop,"DataType"),"Structure")
    fields=[
        ("BootId","String","New UUID after every server/controller restart; old control/access tokens become invalid."),
        ("Sequence","Integer","Monotonically increasing snapshot sequence within BootId."),
        ("ObservedAt","Timestamp","UTC time of this coherent snapshot; client also checks local receipt age."),
        ("Mode","String","Exactly NeedsInitialization, Initializing, Ready, Opening, Closing, Stopping or RecoveryRequired. Robot access is represented separately."),
        ("ProfileId","String","Selected qualified tube profile, or empty string."),
        ("TubePresent","Boolean","Presence sensor; not identity or orientation proof."),
        ("TubeSecured","Boolean","True only when retention is positively confirmed."),
        ("LidState","String","Exactly Unknown, ClosedVerified, OpenVerified or InTransit."),
        ("AccessPurpose","String","Exactly None, Loading, Pipetting or Unloading. Any active grant inhibits station actuation."),
        ("WorkspaceClear","Boolean","Independent local clearance input. False or stale inhibits motion; no clearance safety performance is claimed."),
        ("MotionStopped","Boolean","Measured standstill confirmation; not inferred from StopMotion RPC completion."),
        ("CoolingRequired","Boolean","The selected run requires cooling readiness for pipetting access."),
        ("BlockTemperature","Real","Degrees Celsius; meaningful only when BlockTemperatureValid is true. Not sample temperature."),
        ("BlockTemperatureValid","Boolean","False on failed or stale block sensing; numeric field must be ignored then."),
        ("CoolingReady","Boolean","True only with a qualified thermal profile, valid block sensing, required soak and valid cooling checks. No sample-temperature guarantee from this Boolean alone."),
        ("FaultCode","String","None or the current defined error identifier; unknown state requires recovery.")
    ]
    for args in fields: value(struct,"Element",*args)
    prop=el(root,"Property"); header(prop,"SupportedProfiles","Identifiers of implemented, experimentally qualified tube profiles. Empty for this unimplemented C01 draft."); el(prop,"Observable","No")
    el(el(el(prop,"DataType"),"List"),"DataType").append(ET.Element("{"+NS+"}Basic")); list(prop.iter("{"+NS+"}Basic"))[-1].text="String"
    all_errors={e for cmd in command_specs for e in cmd[-1]}
    explanations={
        "OwnershipConflict":"Another orchestrator owns the station; do not steal or auto-expire its access.",
        "InvalidControlToken":"Token missing, unknown, stale or from another boot.",
        "InvalidAccessToken":"Token does not match the active access grant.",
        "UnknownProfile":"Tube profile is absent or unqualified; nominal volume is insufficient.",
        "InvalidState":"Command preconditions failed; no new actuation is permitted.",
        "WorkspaceNotClear":"Robot clearance is false or stale; retain inhibition.",
        "CoolingNotReady":"Required cooling checks failed or are not yet complete.",
        "TubeNotReady":"Presence, orientation or retention verification failed.",
        "MotionFault":"Motion timeout, overload, following error or feedback failure; retain support and require recovery.",
        "VerificationFailed":"Open or latch verification failed; do not report success.",
        "RecoveryRequired":"Local inspection and controlled recovery are required before further actuation."
    }
    for ident in sorted(all_errors): header(el(root,"DefinedExecutionError"),ident,explanations[ident])
    ET.indent(root,space="  ")
    return ET.tostring(root,encoding="utf-8",xml_declaration=True)+b"\n"


def main():
    raise SystemExit("Historical generator retired; use python scripts/build_tube_station.py")


if __name__=="__main__": main()
