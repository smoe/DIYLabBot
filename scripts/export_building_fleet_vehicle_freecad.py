"""Pack the checked native TR01 camera-kit surfaces for BF01 instancing.

The existing native-face tessellator is reused; the nonphysical viewing cone is
excluded. Materials come from the kit's shared lowering, not a second geometry.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import export_building_walkthrough_freecad as mesh
import tr01_camera_model as kit

ROOT=Path(__file__).resolve().parents[1]


def checked_camera_report(path,root=ROOT):
    path=mesh.project_path(path,root)
    report=json.loads(path.read_text())
    if report.get('format')!='solidcraftbot.tr01-awareness-cross-cad/1' or report.get('passed') is not True:
        raise ValueError('Successful checked camera-kit native build required')
    pins=report.get('source_files_sha256',{})
    required={'model/tr01-awareness-camera.shared.json','model/tr01-awareness-camera.schema.json','model/sample-transport-tr01.shared.json','model/camera.schema.json','scripts/tr01_camera_model.py','scripts/build_tr01_awareness.py','scripts/build_tr01_awareness_freecad.py'}
    if not required<=set(pins):raise ValueError('Complete camera-kit construction source pins required')
    mesh.verify_pins(pins,root)
    files=report.get('files',{});hashes=report.get('artifact_sha256',{})
    if set(files)!=set(hashes) or not {'freecad','solidcraft'}<=set(files):raise ValueError('Complete independent CAD artifact pins required')
    mesh.verify_pins({files[k]:hashes[k]for k in files},root)
    source=kit.expanded(kit.load())
    if report['body_count']!=len(source['bodies']) or report['camera_frame']!=source['camera_frame']:
        raise ValueError('Camera-kit proof differs from current shared lowering')
    return report


def export(report_path,output,deflection_mm=.5,angular_deflection_rad=.35):
    for value,limit in [(deflection_mm,2),(angular_deflection_rad,.5)]:
        if type(value)not in (int,float)or not math.isfinite(value)or not 0<value<=limit:raise ValueError('Positive bounded native mesh tolerance required')
    path=mesh.project_path(report_path);report_hash=mesh.digest(path);report=checked_camera_report(path)
    import FreeCAD as App
    import MeshPart
    sys.path.insert(0,str(ROOT/'scripts/freecad'));import solidcraftbot_freecad as geo
    source=kit.expanded(kit.load());meta={b['id']:b for b in source['bodies']};builder=mesh.MeshBuilder();doc=App.openDocument(str(mesh.project_path(report['files']['freecad'])));faces=0
    try:
        objects=geo.features(doc)
        if {o.SourceBody for o in objects}!=set(meta):raise ValueError('Native camera-kit body coverage mismatch')
        for obj in sorted(objects,key=lambda o:o.SourceBody):
            body=meta[obj.SourceBody]
            if body['role']=='viewing_cone':continue
            shape=geo.world_shape(obj)
            if shape.isNull()or not shape.isValid()or not shape.Solids:raise ValueError('Invalid native vehicle body')
            points,triangles,normals=mesh.native_face_mesh(shape,deflection_mm,angular_deflection_rad,MeshPart);faces+=len(shape.Faces)
            style=dict(body['appearance']);color=style['color']
            if isinstance(color,str):color=[int(color[i:i+2],16)for i in (1,3,5)]
            style['color']=[v/255 for v in color]
            builder.add(obj.SourceBody,points,triangles,style,role=body['role'],normals=normals)
    finally:App.closeDocument(doc.Name)
    scene=builder.result();scene.update(coordinate_frame='tr01_local',units='mm',up_axis='Z',handedness='right',native_body_count=len(scene['groups']),native_face_count=faces,linear_tessellation_deflection_mm=deflection_mm,angular_tessellation_deflection_rad=angular_deflection_rad,camera_frame=source['camera_frame'])
    pins=dict(report['source_files_sha256']);pins[str(path.relative_to(ROOT))]=report_hash
    pins.update({report['files'][k]:v for k,v in report['artifact_sha256'].items()});pins[str(Path(__file__).relative_to(ROOT))]=mesh.digest(__file__);pins['scripts/export_building_walkthrough_freecad.py']=mesh.digest(ROOT/'scripts/export_building_walkthrough_freecad.py')
    checked_camera_report(path)
    if mesh.digest(path)!=report_hash:raise ValueError('Camera report changed during export')
    mesh.verify_pins(pins)
    result={'format':'solidcraftbot.building-fleet-vehicle-mesh/1','scene':scene,'source_files_sha256':pins,'camera_report':{'path':str(path.relative_to(ROOT)),'sha256':report_hash},'limitations':['Float32 native BRep tessellation for display; collision audit uses exact BReps.','Nonphysical viewing cone omitted; camera is synthetic presentation geometry.']}
    output=mesh.project_path(output);output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise FileExistsError(output)
    output.write_text(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n');print('Vehicle mesh: '+str(output),flush=True);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--camera-report',required=True);parser.add_argument('--out',required=True);parser.add_argument('--deflection-mm',type=float,default=.5);args=parser.parse_args();export(args.camera_report,args.out,args.deflection_mm)


if __name__=='__main__':
    import export_building_fleet_vehicle_freecad as adapter
    adapter.main()
