"""Standalone native-mesh inspection replay; exact FK samples at model time."""
import argparse
import base64
import gzip
import hashlib
import json
import math
from pathlib import Path

import build_ps01_logistics as build
from ps01_logistics_validation import Program

s=build.s


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);args=parser.parse_args()
    dest=args.directory;scene=build.geometry.Scene();data=s.read(dest/'program.json');program=Program(data,scene)
    native=s.read(dest/'freecad-local-report.json');records={r['id']:r for r in native['records']}
    meshes=[];indices={};bodies=[];keys={};framespec={}
    for mesh in s.read(dest/'meshes.json'):
        record=records[mesh['id']]
        if record['kind']=='arm':key=record['group']
        elif record['kind']=='tool':key=record['group']+'.jaw'+str(record['jaw_sign'])
        elif record['kind'] in ('sample','vehicle'):key=record['group']+('.Cover' if record['source_body']=='LT01TransportCover' else '')
        else:key=record['id']
        if key not in keys:keys[key]=len(keys);framespec[key]=record
        geometry={'v':[[round(v,4) for v in point] for point in mesh['vertices']],'f':mesh['faces']}
        digest=hashlib.sha256(json.dumps(geometry,separators=(',',':')).encode()).hexdigest()
        if digest not in indices:indices[digest]=len(meshes);meshes.append(geometry)
        bodies.append({'id':mesh['id'],'mesh':indices[digest],'pose':keys[key],'color':mesh['appearance']['color'],
                       'opacity':mesh['appearance'].get('opacity',1),'cover':record['source_body']=='LT01TransportCover'})
    dynamic={key for key,record in framespec.items() if record['kind'] in ('arm','tool','sample','vehicle')}
    static={keys[key]:program.matrix(record,'load.approach',0) for key,record in framespec.items() if key not in dynamic}
    timeline=[];start=0.;phase_ranges=[]
    for phase,curve in program.curves.items():
        duration=curve.times[-1];count=math.ceil(duration*30)
        phase_ranges.append({'id':phase,'start_s':start,'duration_s':duration})
        for index in range(count+1):
            u=index/count
            timeline.append({'t':start+duration*u,'phase':phase,
                'poses':{keys[key]:[round(v,10) for row in program.matrix(framespec[key],phase,u) for v in row] for key in dynamic}})
        start+=duration
    payload={'meshes':meshes,'bodies':bodies,'static':{k:[v for row in m for v in row] for k,m in static.items()},
        'frames':timeline,'phases':phase_ranges,'duration_s':start,'playback_factor':1,
        'program_sha256':s.robot.digest(dest/'program.json'),
        'scope':'Native tessellations and sampled FK replay only. Manual cover/retention observations are assumed fixture events; their duration is unknown.'}
    packed=base64.b64encode(gzip.compress(json.dumps(payload,separators=(',',':')).encode())).decode()
    script=(s.ROOT/'scripts/templates/ps01_logistics_animation.js').read_text()
    html='''<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PS01 · TR01 Rackübergabe</title><style>
*{box-sizing:border-box}body{margin:0;background:#edf2f5;color:#163448;font:16px system-ui}main{max-width:1400px;margin:auto;padding:24px}h1{font-size:26px;margin:0 0 8px}p{line-height:1.5;margin:8px 0}canvas{width:100%;height:65vh;min-height:420px;background:#f7fafb;border:1px solid #ccdae3;border-radius:12px;touch-action:none}button,select{font:inherit;padding:8px 14px;border:1px solid #b0c2ce;border-radius:6px;background:white;color:#163448}nav{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}input{flex:1;min-width:220px}small{color:#506574}#phase{font-weight:600}#error{color:#9a2c31}</style>
<main><h1>Rackübergabe · PS01 → TR01 → RF02</h1>
<p>Bestehende Arme und Greifer, zwei geschlossene Proben und die belegte TR01-Nachbaraufnahme.</p>
<canvas aria-label="Drehbare 3D-Ansicht der Rackübergabe"></canvas>
<nav><button id="play">Abspielen</button><input id="time" type="range" min="0" step="0.01" value="0" aria-label="Modellzeit"><span id="clock"></span><select id="view" aria-label="Ansicht"><option value="all">Übersicht</option><option value="source">Abholung</option><option value="target">Annahme</option><option value="vehicle">Transporter</option></select></nav>
<p id="phase">Modell wird geladen …</p><p id="error" role="alert"></p>
<small>Wiedergabe 1× · Ziehen: drehen · Mausrad: zoomen. Haube und Rückhaltung sind manuell bestätigte Testereignisse; ihre Handhabung und Wartezeit werden nicht animiert. Keine Hardwareausführung oder Sicherheitsfreigabe; schneller-als-manuell ist ungeprüft.</small></main>
<script type="application/octet-stream" id="packed">'''+packed+'</script><script>'+script+'</script></html>'
    (dest/'animation.html').write_text(html)
    build.write(dest/'animation-report.json',{'format':'solidcraftbot.ps01-logistics-animation/1','program_sha256':payload['program_sha256'],
        'html_sha256':s.robot.digest(dest/'animation.html'),'duration_s':start,'playback_factor':1,'native_bodies':len(bodies),
        'mesh_definitions':len(meshes),'frames':len(timeline),'minimum_sample_hz':30,
        'feedback_wait_duration_s':None,'scope':payload['scope'],'collision_qualification':False})
    print({'animation':str(dest/'animation.html'),'duration_s':start,'bodies':len(bodies)},flush=True)


if __name__=='__main__':main()
