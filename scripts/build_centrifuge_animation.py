"""Derive a native SolidCraft study/GIF and FreeCAD playback from the CF01 protocol."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import centrifuge_model as model
import centrifuge_protocol as protocol


def prepare():
    spec=model.load(); p=model.parameters(spec); data=protocol.load()
    baseline=json.loads((model.ROOT/'cad/centrifuge-cf01/shared-build-report.json').read_text())
    if not baseline['passed'] or baseline['source_sha256']!=model.digest(model.SOURCE): raise ValueError('Current checked geometry required')
    for key in ('solidcraft','freecad'):
        path=model.ROOT/baseline['cases'][0]['files'][key]
        if model.digest(path)!=baseline['cases'][0]['artifact_sha256'][key]: raise ValueError('Geometry artifact changed')
    stem='centrifuge-cf01-cycle-'+model.digest(protocol.SOURCE)[:12]; revision=stem; n=1
    while (model.ROOT/'exports/generated'/revision).exists(): n+=1; revision=stem+'-r'+str(n)
    out=model.ROOT/'exports/generated'/revision; cad=model.ROOT/'cad/generated'/revision; renders=model.ROOT/'renders'/revision
    for d in [out,cad,renders]: d.mkdir(parents=True)
    keys=protocol.frames(spec,p,data); source=model.expanded(spec,p)
    sampled=[protocol.at_time(keys,i*data['animation']['duration_s']/132) for i in range(133)]
    for sample in sampled: model.validate_pose(source,sample['values'])
    study=protocol.motion_commands(spec,p,data)
    commands=study+[
        {'command':'motion.export','params':{'study':'CF01RobotAccess','samples':133,'path':str(out/'native-motion.json')}},
        {'command':'motion.export_animation','params':{'study':'CF01RobotAccess','samples':88,'fps':6,
             'path':str(renders/'robot-access-cycle.gif'),'width':1000,'height':760,'grid':False,'axes':False,
             'camera':{'target':[0,0,260],'yaw':-0.95,'pitch':0.3,'distance':950}}}]
    model.write(out/'animation.commands.json',{'commands':commands})
    model.write(out/'timeline.json',{'geometry_sha256':model.digest(model.SOURCE),'protocol_sha256':model.digest(protocol.SOURCE),
        'units':data['units'],'keyframes':keys,'samples':sampled,'notes':data['animation']['notes'],'gif_playback_factor':2.25})
    fc=cad/'Centrifuge_CF01.FCStd'; shutil.copy2(model.ROOT/baseline['cases'][0]['files']['freecad'],fc)
    # The CAD-independent timeline is embedded verbatim; no geometry is reconstructed here.
    macro=(model.ROOT/'scripts/templates/centrifuge_playback.FCMacro').read_text().replace('__DOCUMENT__',repr(str(fc))).replace('__KEYS__',repr(keys))
    (cad/'CF01_RobotAccess.FCMacro').write_text(macro,encoding='utf-8')
    context={'revision':revision,'out':str(out),'cad':str(cad),'renders':str(renders),
        'baseline_solidcraft':str(model.ROOT/baseline['cases'][0]['files']['solidcraft']),
        'baseline_report_sha256':model.digest(model.ROOT/'cad/centrifuge-cf01/shared-build-report.json'),
        'geometry_source_sha256':model.digest(model.SOURCE),'protocol_source_sha256':model.digest(protocol.SOURCE)}
    model.write(model.ROOT/'tmp/cf01-animation-context.json',context)
    return context


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--prepare-only',action='store_true'); args=parser.parse_args()
    context=prepare(); print(json.dumps(context),flush=True)
    if args.prepare_only:return
    out=Path(context['out']); cad=Path(context['cad'])
    subprocess.run([shutil.which('solidcraft-cli') or 'solidcraft-cli','run',str(out/'animation.commands.json'),
        '--in',context['baseline_solidcraft'],'--save',str(cad/'Centrifuge_CF01_Animated.sc'),'--quiet'],cwd=model.ROOT,check=True)
    print('Native CF01 animation exported',flush=True)


if __name__=='__main__':main()
