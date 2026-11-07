"""Historical migration support; direct generation is retired.

Generate T01 portable CAD recipe and independent geometric review references.

Run generated commands using SolidCraft MCP in an empty design. This script
does not replace an open CAD document or move a robot.
"""
from pathlib import Path
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "model/history/tip-collector-t01.legacy.json"
CAD = ROOT / "cad/tip-collector-t01"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare(spec):
    d = spec["dimensions"]
    commands, refs = [], {}

    def add(command, **params):
        commands.append({"command": command, "params": params})

    for name, value in d.items():
        add("parameters.add", name=name, expression=f"{value} mm", unit="mm")
    for name, expression in {
        "fork_z": "base_t+bin_h+rim_to_fork",
        "post_h": "bin_h+rim_to_fork-beam_t",
    }.items():
        add("parameters.add", name=name, expression=expression, unit="mm")
    for g in spec["grooves"]:
        add("parameters.add", name="groove_"+g["id"], expression=f'{g["width_mm"]} mm', unit="mm")
    add("document.metadata.set", values={"org.solidcraftbot.tip-collector": {
        "revision": spec["revision"], "source": "model/history/tip-collector-t01.legacy.json",
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "status": spec["status"], "grooves_are_unqualified": True}})

    def box(name, size, center, volume, bbox, color, group="Frame"):
        add("solid.box", name=name, body_name=name, length=size[0], width=size[1],
            height=size[2], center=center, operation="new")
        refs[name] = {"name": name, "group": group, "volume_mm3": volume,
                      "bbox_mm": bbox, "color": color}

    def hole(name, diameter, height, base, targets, removed_each):
        add("solid.cylinder", name=name, diameter=diameter, height=height,
            base=base, operation="cut", targets=targets)
        for target, volume in zip(targets, removed_each):
            refs[target]["volume_mm3"] -= volume

    b, h, fz, t = d["base_t"], d["bin_h"], d["base_t"]+d["bin_h"]+d["rim_to_fork"], d["fork_t"]
    box("MountBase", ["base_x","base_y","base_t"], [0,0,"base_t/2"],
        d["base_x"]*d["base_y"]*b, [[-120,-92,0],[120,92,b]], "#334155")
    for x in [-108,108]:
        for y in [-80,80]:
            hole(f"TableHole_{x}_{y}","table_hole_d","base_t+2",[x,y,-1],["MountBase"],
                 [math.pi*(d["table_hole_d"]/2)**2*b])
    for side, sign in [("Left",-1),("Right",1)]:
        x = sign*d["post_center_x"]
        ph = h+d["rim_to_fork"]-d["beam_t"]
        box("Post"+side,["post_x","post_y","post_h"],
            [f"{sign}*post_center_x","beam_center_y","base_t+post_h/2"],
            d["post_x"]*d["post_y"]*ph, [[x-6,24,b],[x+6,60,b+ph]],"#8f9ead")
        for y in [34,50]:
            hole(f"PostTopPilot_{side}_{y}",4.2,13,[x,y,fz-20],["Post"+side],
                 [math.pi*2.1**2*12])
            hole(f"PostBottomPilot_{side}_{y}",4.2,13,[x,y,b-1],["Post"+side],
                 [math.pi*2.1**2*12])
            hole(f"PostBaseClearance_{side}_{y}",5.5,b+2,[x,y,-1],["MountBase"],
                 [math.pi*2.75**2*b])
    box("RearBeam",["beam_x","beam_y","beam_t"],[0,"beam_center_y","fork_z-beam_t/2"],
        d["beam_x"]*d["beam_y"]*d["beam_t"],[[-116,30,fz-8],[116,54,fz]],"#8f9ead")
    for x in [-106,106]:
        for y in [34,50]:
            hole(f"BeamPostClearance_{x}_{y}",5.5,10,[x,y,fz-9],["RearBeam"],
                 [math.pi*2.75**2*8])

    # Bin datum is fixed by rails/rear stop; it can be withdrawn towards -Y.
    for side, sign in [("Left",-1),("Right",1)]:
        x = sign*95
        box("BinGuide"+side,[4,148,6],[x,0,b+3],4*148*6,
            [[x-2,-74,b],[x+2,74,b+6]],"#697b91")
    box("BinRearStop",[184,4,6],[0,75,b+3],184*4*6,[[-92,73,b],[92,77,b+6]],"#697b91")
    box("RemovableBin",["bin_x","bin_y","bin_h"],[0,0,"base_t+bin_h/2"],
        d["bin_x"]*d["bin_y"]*h,[[-92,-72,b],[92,72,b+h]],"#dfe8ed",group="Bin")
    add("solid.box",name="BinCavity",length="bin_x-2*bin_wall",width="bin_y-2*bin_wall",
        height="bin_h-bin_wall+1",center=[0,0,"base_t+bin_wall+(bin_h-bin_wall+1)/2"],
        operation="cut",targets=["RemovableBin"])
    refs["RemovableBin"]["volume_mm3"] -= (d["bin_x"]-2*d["bin_wall"])*(d["bin_y"]-2*d["bin_wall"])*(h-d["bin_wall"])
    stage_one = len(commands)

    for g in spec["grooves"]:
        x, w, ident = g["x_mm"],g["width_mm"],g["id"]
        name, gp = f"Fork_{ident}_{w}mm", "groove_"+ident
        box(name,["fork_x","fork_rear_y-fork_front_y","fork_t"],
            [x,"(fork_rear_y+fork_front_y)/2","fork_z+fork_t/2"],
            d["fork_x"]*(d["fork_rear_y"]-d["fork_front_y"])*t,
            [[x-24,-42,fz],[x+24,54,fz+t]],g["color"],group="Insert"+ident)
        add("sketch.create",name="GrooveSketch"+ident,plane="XY",offset="fork_z-1")
        add("sketch.line",points=[
            [f"{x}-mouth_width/2","fork_front_y-1"],
            [f"{x}+mouth_width/2","fork_front_y-1"],
            [f"{x}+mouth_width/2","fork_front_y"],
            [f"{x}+{gp}/2","taper_end_y"],
            [f"{x}+{gp}/2","slot_end_y"]],infer=False)
        add("sketch.arc.three_point",start="l4.end",end=[f"{x}-{gp}/2","slot_end_y"],
            through=[x,f"slot_end_y+{gp}/2"])
        add("sketch.line",points=["a1.end",[f"{x}-{gp}/2","taper_end_y"],
            [f"{x}-mouth_width/2","fork_front_y"],"l1.start"],infer=False)
        add("sketch.finish")
        add("solid.extrude",name="GrooveCut"+ident,sketch="GrooveSketch"+ident,
            distance="fork_t+2",operation="cut",targets=[name])
        slot_area = (d["taper_end_y"]-d["fork_front_y"])*(d["mouth_width"]+w)/2 + (d["slot_end_y"]-d["taper_end_y"])*w + math.pi*w*w/8
        refs[name]["volume_mm3"] -= slot_area*t
        for sign in [-1,1]:
            hole("InsertFix"+ident+str(sign),"insert_hole_d","beam_t+fork_t+2",
                 [f"{x}+{sign}*insert_hole_dx","beam_center_y","fork_z-beam_t-1"],
                 [name,"RearBeam"],[math.pi*(d["insert_hole_d"]/2)**2*t,
                                      math.pi*(d["insert_hole_d"]/2)**2*d["beam_t"]])
    stage_two = len(commands)

    # Shallow identity markings, checked separately from the core analytic volumes.
    for g in spec["grooves"]:
        ident, w = g["id"], g["width_mm"]
        add("sketch.create",name="MarkSketch"+ident,plane="XY",offset="fork_z+fork_t-0.3")
        add("sketch.text",text=f'{g["target_pipette_capacity_ul"]} uL',at=[g["x_mm"],18],
            height=5,align="center")
        add("sketch.finish")
        add("solid.extrude",name="CapacityMark"+ident,sketch="MarkSketch"+ident,
            distance=0.6,operation="cut",targets=[f"Fork_{ident}_{w}mm"])

    for group in ["Frame","Bin","InsertS","InsertM","InsertL"]:
        add("component.create",name=group,parent="root",activate=False,grounded=True)
        add("component.move_bodies",bodies=[n for n,r in refs.items() if r["group"]==group],component=group)
    for name, ref in refs.items():
        add("appearance.assign",bodies=[name],color=ref["color"],opacity=1)
    return commands,refs,[stage_one,stage_two,len(commands)]


def envelope_checks(spec):
    d,e = spec["dimensions"],spec["illustrative_envelopes"]
    floor_z = d["base_t"]+d["bin_wall"]
    fork_z = d["base_t"]+d["bin_h"]+d["rim_to_fork"]
    checks=[]
    def record(name, condition, **details):
        checks.append(dict(name=name,passed=bool(condition),**details))
    record("collar below fork",e["collar_top_z_mm"]<fork_z,gap_mm=fork_z-e["collar_top_z_mm"])
    tip_bottom=e["collar_top_z_mm"]-e["maximum_tip_length_below_collar_mm"]
    record("tip clears empty bin floor",tip_bottom>floor_z,clearance_mm=tip_bottom-floor_z)
    record("tip clears illustrative waste envelope",tip_bottom>e["initial_bin_fill_limit_z_mm"],
           clearance_mm=tip_bottom-e["initial_bin_fill_limit_z_mm"])
    for g in spec["grooves"]:
        ident,w=g["id"],g["width_mm"]
        collar=e["tip_collar_diameter_mm"][ident]
        shaft=e["shaft_diameter_mm"][ident]
        record("synthetic shaft running clearance "+ident,shaft<w,radial_clearance_mm=(w-shaft)/2)
        record("synthetic collar capture "+ident,collar>w,radial_overlap_mm=(collar-w)/2)
        for y in [e["approach_y_mm"],e["capture_y_mm"]]:
            record(f"synthetic collar within bin opening {ident} y={y}",
                   abs(g["x_mm"])+collar/2<d["bin_x"]/2-d["bin_wall"] and
                   abs(y)+collar/2<d["bin_y"]/2-d["bin_wall"])
    record("bin front withdrawal under forks",d["rim_to_fork"]>0,vertical_gap_mm=d["rim_to_fork"])
    # A profile/force sensor must be supplied before this draft becomes executable.
    return {"scope":"Analytic envelope checks for invented test cylinders only; not robot or pipette qualification",
            "checks":checks,"passed":all(c["passed"] for c in checks),
            "qualified_profiles":[],"robot_path_checked":False,"force_checked":False}


def main():
    raise SystemExit("Historical generator retired; use python scripts/build_tip_collector.py")


if __name__ == "__main__":
    main()
