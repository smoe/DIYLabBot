"""Prove byte-identical local BReps before reusing an earlier geometry audit."""
import hashlib
from pathlib import Path
import sys

import FreeCAD as App
import build_ps01_logistics as build
import build_pipetting_station_freecad as native


def fingerprints(directory):
    path=directory/'Logistics-local.FCStd'
    doc=App.openDocument(str(path))
    try:
        result={}
        for obj in native.motion.features(doc):
            shape=native.motion.world_shape(obj)
            build.s.require(shape.isValid(),'Invalid native BRep: '+obj.SourceBody)
            result[obj.SourceBody]=hashlib.sha256(shape.exportBrepToString().encode()).hexdigest()
        return result
    finally:
        App.closeDocument(doc.Name)


def main(previous,current):
    old,new=Path(previous).resolve(),Path(current).resolve()
    # The new model must be built with current source pins. The old source
    # report is historical; it is never rewritten to pretend a rebuild.
    build.base.verify_pins(build.s.read(new/'context.json')['source_files_sha256'])
    first,second=fingerprints(old),fingerprints(new)
    report={'passed':first==second,'method':'Exact SHA-256 of every serialized native local BRep, including placement',
        'previous_directory':str(old),'current_directory':str(new),'body_count':len(second),
        'previous_artifact_sha256':build.s.robot.digest(old/'Logistics-local.FCStd'),
        'current_artifact_sha256':build.s.robot.digest(new/'Logistics-local.FCStd'),
        'bodies_sha256':second,'differing_bodies':[key for key in sorted(set(first)|set(second)) if first.get(key)!=second.get(key)],
        'programs_identical':build.s.read(old/'program.json')==build.s.read(new/'program.json'),
        'previous_program_sha256':build.s.robot.digest(old/'program.json'),
        'current_program_sha256':build.s.robot.digest(new/'program.json'),
        'verifier_sha256':build.s.robot.digest(Path(__file__))}
    report['passed']=report['passed'] and report['programs_identical']
    build.write(new/'brep-equivalence.json',report)
    print({'passed':report['passed'],'bodies':len(second),'differing_bodies':report['differing_bodies']},flush=True)
    return report


if __name__=='__main__':main(*sys.argv[1:])
