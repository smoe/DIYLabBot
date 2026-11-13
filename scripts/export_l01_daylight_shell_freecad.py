"""Export the checked native wall openings/glazing without display boxes."""
import FreeCAD as App
import sys,json
from pathlib import Path
import tr01_floor_motion as model
ROOT=model.ROOT
sys.path.insert(0,str(ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo

def main():
    report_path=ROOT/'cad/lab-layout-l01/shared-build-report.json';report=json.loads(report_path.read_text())
    if not report['passed']:raise ValueError('Checked L01 layout required')
    model.verify(report['source_files_sha256']);path=ROOT/report['files']['freecad']
    if model.robot.digest(path)!=report['artifact_sha256']['freecad']:raise ValueError('Native layout changed')
    doc=App.openDocument(str(path));parts=[]
    for obj in geo.features(doc):
        name=getattr(obj,'OriginalBody',obj.SourceBody)
        if getattr(obj,'LayoutInstance','')!='Room' or not ('Wall' in name or 'Glazing' in name):continue
        pts,faces=geo.world_shape(obj).tessellate(8.)
        parts.append({'body':name,'kind':13 if 'Glazing' in name else 1,'vertices_qmm':[[round(float(v)*4) for v in p] for p in pts],'triangles':[list(f) for f in faces]})
    if not any(p['body']=='FacadeWall' for p in parts) or sum(p['kind']==13 for p in parts)!=3:raise ValueError('Native facade and all three glazing bodies required')
    output={'format':'solidcraftbot.daylight-shell-mesh/1','source_files_sha256':{**report['source_files_sha256'],str(report_path.relative_to(ROOT)):model.robot.digest(report_path),str(path.relative_to(ROOT)):model.robot.digest(path),str(Path(__file__).relative_to(ROOT)):model.robot.digest(__file__)},'parts':parts,'scope':'Full native room wall/glazing tessellation; quarter-mm display coordinates; no new CAD geometry'}
    target=ROOT/'exports/tr01-workcell/daylight-shell.json';target.write_text(json.dumps(output,separators=(',',':'))+'\n');print(len(parts),'native shell bodies',sum(len(p['triangles']) for p in parts),'triangles')
if __name__=='__main__':
    import export_l01_daylight_shell_freecad as adapter
    adapter.main()
