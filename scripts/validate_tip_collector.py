"""Audit saved T01 CAD evidence and deliverables. Does not run a CAD engine."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import math
import struct

from prepare_tip_collector import ROOT, SOURCE, CAD, write_json


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stl_check(path, reference):
    raw=path.read_bytes()
    count=struct.unpack_from("<I",raw,80)[0]
    if len(raw)!=84+50*count:
        raise ValueError("Unexpected binary STL size")
    vertices, edges, volume=[],Counter(),0.0
    for i in range(count):
        values=struct.unpack_from("<12fH",raw,84+50*i)
        a,b,c=[tuple(values[j:j+3]) for j in [3,6,9]]
        vertices.extend([a,b,c])
        for p,q in [(a,b),(b,c),(c,a)]:
            edges[tuple(sorted([p,q]))]+=1
        volume+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
    box=[[min(v[j] for v in vertices) for j in range(3)],
         [max(v[j] for v in vertices) for j in range(3)]]
    return dict(triangles=count,volume_mm3=volume,bbox_mm=box,
        two_triangles_per_edge=all(n==2 for n in edges.values()),
        passed=all(n==2 for n in edges.values()) and
        math.isclose(volume,reference["volume_mm3"],rel_tol=1e-6) and box==reference["bbox_mm"],
        note="Export is in assembly mm coordinates: floor underside at Z=8 mm. Place on print bed in slicer; no fabrication release.")


def main():
    raise SystemExit("Historical validator retired; use python scripts/build_tip_collector.py")
    spec=read(SOURCE)
    source_hash=digest(SOURCE)
    refs=read(CAD/"geometry-reference.json")
    evidence=read(CAD/"cad-check-evidence.json")
    envelopes=read(CAD/"envelope-checks.json")
    native=read(CAD/"TipCollector_T01.native.json")
    reopen=read(CAD/"reopen-check.json")
    metadata=native["metadata"]["org.solidcraftbot.tip-collector"]
    core={p["name"]:p for p in evidence["core_measurement"]["bodies"]}
    checks=[]
    for expected in refs["parts"]:
        actual=core[expected["name"]]
        error=abs(actual["volume_mm3"]-expected["volume_mm3"])/expected["volume_mm3"]
        bounds=max(abs(x-y) for row,key in zip(expected["bbox_mm"],["min","max"])
                   for x,y in zip(row,actual["bbox"][key]))
        checks.append(dict(name=expected["name"],expected_core_volume_mm3=expected["volume_mm3"],
            measured_core_volume_mm3=actual["volume_mm3"],relative_error=error,bbox_max_error_mm=bounds,
            passed=actual["closed"] and error<0.0002 and bounds<0.001))
    meshes=stl_check(CAD/"TipCollector_T01_bin.review.stl",next(p for p in refs["parts"] if p["name"]=="RemovableBin"))
    final=evidence["final_inspection"]
    interference=evidence["static_interference"]
    timeline_ok=not any(f.get("error") or f.get("warning") for f in final["timeline"])
    interference_ok=interference["count"]==0 and not interference["unchecked"] and not interference["truncated"]
    provenance_ok=all(v==source_hash for v in [refs["source_sha256"],envelopes["source_sha256"],
        metadata["source_sha256"],final["metadata"]["org.solidcraftbot.tip-collector"]["source_sha256"],
        reopen["metadata"]["org.solidcraftbot.tip-collector"]["source_sha256"]])
    images=[]
    for name in ["collector-iso.png","collector-top.png"]:
        raw=(CAD/name).read_bytes()
        w,h=struct.unpack(">II",raw[16:24])
        images.append(dict(path=name,width=w,height=h,passed=raw[:8]==b"\x89PNG\r\n\x1a\n" and w>=900 and h>=600))
    passed=all(c["passed"] for c in checks+images+evidence["marking_checks"])
    passed=passed and meshes["passed"] and envelopes["passed"] and timeline_ok and interference_ok
    passed=passed and provenance_ok and reopen["passed"] and evidence["groove_parameter_test"]["passed"]
    passed=passed and len(evidence["final_measurement"]["bodies"])==11 and all(b["closed"] for b in evidence["final_measurement"]["bodies"])
    artifacts=[SOURCE,ROOT/"scripts/prepare_tip_collector.py",Path(__file__).resolve(),ROOT/"docs/tip-collector-t01.md"]
    artifacts += [p for p in CAD.iterdir() if p.is_file() and p.name!="draft-validation.json"]
    report=dict(format="solidcraftbot.tip-collector-validation/1",date=spec["date"],revision="T01",
        passed=bool(passed),status="Review geometry only; no fabrication or robot-operation release",
        source_sha256=source_hash,body_count=11,core_volume_tolerance_relative=0.0002,
        core_geometry_checks=checks,marking_checks=evidence["marking_checks"],
        parameter_test=evidence["groove_parameter_test"],parameter_restored_mm=6,
        timeline_healthy=timeline_ok,static_interference=interference,
        synthetic_envelope_checks=envelopes,stl_check=meshes,images=images,
        visual_review="Isometric and top model renders inspected: all three open grooves, markings, bin and frame visible; no crop",
        reopen_check=reopen,qualified_article_profiles=[],
        robot_joints="No station joints; arm and its stand pose unchanged and untested in this task",
        full_robot_motion_envelope_checked=False,release_force_checked=False,
        limits=spec["scope"],
        artifact_sha256={str(p.relative_to(ROOT)).replace("\\","/"):digest(p) for p in sorted(artifacts)})
    write_json(CAD/"draft-validation.json",report)
    print(json.dumps(dict(passed=bool(passed),bodies=11,core_checks=len(checks),
        static_interferences=interference["count"],native_reopen_passed=reopen["passed"],
        qualified_article_profiles=0,report="cad/tip-collector-t01/draft-validation.json")))
    if not passed:
        raise SystemExit("T01 audit failed")


if __name__=="__main__":
    main()
