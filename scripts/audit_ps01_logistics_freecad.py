"""Inspect the independently constructed FreeCAD BReps along continuous paths."""
from pathlib import Path
import sys
import time
import FreeCAD as App
import Part
import build_ps01_logistics as build
import build_pipetting_station_freecad as native
from ps01_logistics_validation import Program,certify,transformed,bbox_distance

s=build.s


def main(directory,mode='continuous'):
    dest=Path(directory)
    execution_pins={**build.pins(),str(Path(__file__).resolve().relative_to(s.ROOT)):s.robot.digest(Path(__file__))}
    program_hash=s.robot.digest(dest/'program.json')
    scene=build.geometry.Scene();program=Program(s.read(dest/'program.json'),scene)
    report=s.read(dest/'freecad-local-report.json');source_records=report['records'];records=build.grouped(source_records)
    local_file=dest/'Logistics-local.FCStd'
    artifact=local_file if local_file.exists() else dest/'Logistics.FCStd';artifact_hash=s.robot.digest(artifact)
    doc=App.openDocument(str(artifact));local={}
    lookup={r['id']:r for r in source_records}
    for obj in native.motion.features(doc):
        record=lookup[obj.SourceBody];shape=native.motion.world_shape(obj)
        initial=record.get('saved_world_matrix',record['matrix'] if record['source_body']=='LT01TransportCover' else program.matrix(record,'load.approach',0))
        if not local_file.exists():shape.Placement=native.placement(s.robot.inverse(initial)).multiply(shape.Placement)
        local[record['id']]=shape
    App.closeDocument(doc.Name)
    pairs,excluded=program.collision_pairs(records);byid={r['id']:r for r in records};exact=[0];overlaps=[]
    start=time.monotonic();counter=[0];invariant_cache={}
    def provider(requests):
        frames=[]
        for phase,u,width in requests:
            posed={};boxes={};matrices={}
            for record in records:
                matrix=program.matrix(record,phase,u)
                boxes[record['id']]=transformed(record['local_bbox'],matrix)
                matrices[record['id']]=matrix
            cache={}
            def distance(a,b,posed=posed,cache=cache,phase=phase,u=u,matrices=matrices):
                key=tuple(sorted((a,b)))
                if key not in cache:
                    relative=s.robot.multiply(s.robot.inverse(matrices[a]),matrices[b])
                    invariant=(a,b,tuple(round(v,9) for row in relative for v in row))
                    if invariant in invariant_cache:
                        cache[key]=invariant_cache[invariant];return cache[key]
                    # Hierarchical native boxes avoid repeatedly copying and
                    # comparing every detailed motor face. Far sub-body pairs
                    # retain their conservative 5-mm lower bound; near pairs
                    # are measured on their original native BReps.
                    value=5.
                    for x in byid[a]['members']:
                        bx=transformed(lookup[x]['local_bbox'],matrices[a])
                        for y in byid[b]['members']:
                            by=transformed(lookup[y]['local_bbox'],matrices[b])
                            if bbox_distance(bx,by)>5:continue
                            for body,parent in ((x,a),(y,b)):
                                if body not in posed:
                                    shape=local[body].copy(False,False)
                                    shape.Placement=native.placement(matrices[parent]).multiply(shape.Placement);posed[body]=shape
                            exact[0]+=1;d=posed[x].distToShape(posed[y])[0];value=min(value,d)
                            if d<1e-6:
                                volume=posed[x].common(posed[y]).Volume
                                if volume>1e-4:
                                    overlaps.append({'phase':phase,'u':u,'a':x,'b':y,'volume_mm3':volume})
                                    raise ValueError('Native solid overlap: '+str(overlaps[-1]))
                    cache[key]=value
                    invariant_cache[invariant]=value
                return cache[key]
            frames.append({'boxes':boxes,'distance':distance,'fk_error_mm':0.})
            counter[0]+=1
        print({'poses':counter[0],'exact_distances':exact[0],'elapsed_s':round(time.monotonic()-start,1)},flush=True)
        return frames
    try:
        if mode=='continuous':result=certify(program,records,provider)
        else:
            failures=[]
            for phase in program.curves:
                for u in (0,.25,.5,.75,1):
                    frame=provider([(phase,u,0)])[0]
                    for pair in pairs:
                        a,b=pair['a'],pair['b'];lower=bbox_distance(frame['boxes'][a],frame['boxes'][b])
                        if lower>max(.01,pair['required_mm']):continue
                        distance=frame['distance'](a,b)
                        if distance+1e-7<pair['required_mm']:failures.append({**pair,'phase':phase,'u':u,'distance_mm':distance})
            result={'passed':not failures,'failures':failures,'scope':'Diagnostic discrete poses only'}
    except (ValueError,RuntimeError) as error:result={'passed':False,'error':str(error)}
    try:
        build.base.verify_pins(execution_pins)
        s.require(program_hash==s.robot.digest(dest/'program.json') and artifact_hash==s.robot.digest(artifact),
                  'Audit inputs changed during execution')
    except ValueError as error:result={'passed':False,'error':str(error)}
    result.update(backend='freecad',exact_distances=exact[0],overlaps=overlaps,elapsed_s=time.monotonic()-start,
                  artifact_sha256=artifact_hash,artifact_name=artifact.name,program_sha256=program_hash,
                  source_files_sha256=execution_pins)
    build.write(dest/('freecad-'+mode+'.json'),result)
    print({'passed':result['passed'],'report':str(dest/('freecad-'+mode+'.json'))},flush=True)
    return result


if __name__=='__main__':main(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else 'continuous')
