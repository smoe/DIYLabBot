"""Add the checked water mode to an existing audited L01 inline animation."""
import argparse
import base64
import gzip
import hashlib
import json
import re
import struct
from pathlib import Path
import water_practice_l01 as m


def display_mesh(encoded):
    """2 mm vertex clustering for arm display only; retain tips and vessels.

    Native collision solids and motion coefficients are never simplified.
    """
    raw=gzip.decompress(base64.b64decode(encoded));count,group_count=struct.unpack_from('<II',raw)
    source=[struct.unpack_from('<hhh',raw,8+i*6) for i in range(count)]
    offset=8+count*6;vertices=[];seen={};groups=[]
    for _ in range(group_count):
        kind,length=struct.unpack_from('<II',raw,offset);offset+=8
        ids=struct.unpack_from('<'+'I'*length,raw,offset);offset+=length*4
        simplify=kind==481 or 400<=kind<460 and kind%20<7
        values=[]
        for i in ids:
            point=tuple(round(v/8)*8 for v in source[i]) if simplify else source[i]
            if point not in seen:seen[point]=len(vertices);vertices.append(point)
            values.append(seen[point])
        faces=[values[i:i+3] for i in range(0,len(values),3) if len(set(values[i:i+3]))==3]
        unique=list(dict.fromkeys(tuple(face) for face in faces));groups.append((kind,[i for face in unique for i in face]))
    payload=struct.pack('<II',len(vertices),len(groups))+b''.join(struct.pack('<hhh',*v) for v in vertices)
    for kind,ids in groups:payload+=struct.pack('<II',kind,len(ids))+struct.pack('<'+'I'*len(ids),*ids)
    return base64.b64encode(gzip.compress(payload,9)).decode()


def merge_mesh(a,b):
    def decode(encoded):
        raw=gzip.decompress(base64.b64decode(encoded));n,g=struct.unpack_from('<II',raw);offset=8+n*6;groups=[]
        for _ in range(g):
            kind,length=struct.unpack_from('<II',raw,offset);offset+=8
            ids=struct.unpack_from('<'+'I'*length,raw,offset);offset+=4*length;groups.append((kind,ids))
        return n,raw[8:8+n*6],groups
    n,vertices,groups=decode(a);count,more,extra=decode(b)
    payload=struct.pack('<II',n+count,len(groups)+len(extra))+vertices+more
    for kind,ids in groups+[(k,[i+n for i in v]) for k,v in extra]:
        payload+=struct.pack('<II',kind,len(ids))+struct.pack('<'+'I'*len(ids),*ids)
    return base64.b64encode(gzip.compress(payload,9)).decode()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('--base-fragment',type=Path,required=True);p.add_argument('--base-receipt',type=Path,required=True);p.add_argument('--fixture-report',type=Path,required=True)
    args=p.parse_args();program=m.read(m.OUT/'program.json');checksum=program.pop('program_sha256')
    if hashlib.sha256(json.dumps(program,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=checksum:raise ValueError('Changed water program')
    for name,sha in program['source_files_sha256'].items():
        if m.digest(m.ROOT/name)!=sha:raise ValueError('Changed motion source: '+name)
    if not program['proof']['passed']:raise ValueError('Native water proof required')
    tool_proof=m.read(m.OUT/'tool-arm-proof.json')
    paths_sha=hashlib.sha256(json.dumps(program['paths'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if not tool_proof['passed'] or tool_proof['paths_sha256']!=paths_sha or tool_proof['arm_artifact_sha256']!=program['native_context']['current_arm_artifact_sha256']:raise ValueError('Current pipettor/arm proof required')
    for name,sha in tool_proof['source_files_sha256'].items():
        if m.digest(m.ROOT/name)!=sha:raise ValueError('Changed pipettor proof source: '+name)
    fixture_report=m.read(args.fixture_report)
    if m.digest(args.fixture_report)!=program['fixture_report_sha256']:raise ValueError('Changed water fixture report')
    receipt=m.read(args.base_receipt)
    if receipt['workcell_revision']!=program['native_context']['revision']:raise ValueError('Different native L01 scene revision')
    if m.digest(args.base_fragment)!=receipt['fragment_sha256']:raise ValueError('Changed base L01 animation')
    if not receipt['local_traffic_motion_has_new_native_proof']:raise ValueError('Audited L01 base required')
    fragment=args.base_fragment.read_text()
    match=re.search(r'(<script type="application/json" id="tr01-workcell-data">)(.*?)(</script>)',fragment)
    data=json.loads(gzip.decompress(base64.b64decode(json.loads(match[2]))))
    if set(data['actors'])!=set(program['actors']):raise ValueError('L01 actors changed')
    for actor,d in data['actors'].items():
        for key in ('base','frames','links','flange_link'):
            if d[key]!=program['actors'][actor][key]:raise ValueError('Base arm frames differ')
    from render_tr01_workcell import compact_mesh
    data['mesh']=compact_mesh(merge_mesh(data['mesh'],display_mesh(program['mesh'])))
    water={k:v for k,v in program.items() if k not in ('mesh','source_files_sha256','native_context','proof')}
    for path in water['paths'].values():
        path['curves']={k:{'duration':c['duration_s'],'points':[[p['time_s'],p[m.F[0]],p[m.F[1]],p[m.F[2]]] for p in c['points']]} for k,c in path['curves'].items()}
    water['fixture']=m.read(m.ROOT/'model/water-transfer-practice.fixture.json')
    water['display_bindings']=fixture_report['trace'][0]['state']['definition']['water_inventory']['paths']
    water['binding_scope']='display_projection_not_runtime_location'
    for path,binding in water['display_bindings'].items():
        if binding['initial_volume_ul']!=water['fixture']['initial_volume_ul'] or binding['transfer_volume_ul']!=water['fixture']['transfer_volume_ul']:raise ValueError('Fixture quantities differ')
    water['trace_events']=[{k:event[k] for k in ('kind','sequence','sha256')} for event in fixture_report['trace']]
    data['water']=water
    # Keep actual PVA and controller status untouched; omit only unused scan
    # diagnostics and duplicate poses from display frames to fit inline limits.
    for frame in data['traffic']['frames']:
        frame['vehicles']=[{k:v[k] for k in ('id','station','mode','velocity_mm_s')} for v in frame['vehicles']]
    encoded=json.dumps(base64.b64encode(gzip.compress(json.dumps(data,separators=(',',':')).encode(),9)).decode())
    fragment=fragment[:match.start(2)]+encoded+fragment[match.end(2):]
    # A single explicit extension point; reject incompatible base templates.
    anchor='new ResizeObserver(render).observe(canvas);'
    if fragment.count(anchor)!=1:raise ValueError('Unsupported L01 player extension point')
    view=m.ROOT/'scripts/water_practice_l01_view.js'
    fragment=fragment.replace(anchor,view.read_text()+'\n'+anchor)
    fragment=fragment.replace('</style>','#tr01-workcell-playback [hidden]{display:none!important}\n</style>',1)
    material_anchor='alpha=g.displayKind===8?'
    if fragment.count(material_anchor)!=1:raise ValueError('Unsupported L01 material extension point')
    fragment=fragment.replace(material_anchor,'alpha=waterActive&&g.kind===480?.25:g.displayKind===8?')
    fragment=fragment.replace('Synthetische L01-Animation mit Gangmittelfahrten','Wasserübung mit drei Pipettierarmen, vier Zugaben und Wiederanlauf ohne erneute Zugabe; L01-Animation mit Gangmittelfahrten')
    fragment=fragment.replace('Bewegungszeit · Bestätigungs- und Prozesszeiten offen','Modellzeit und Wiedergabefaktor getrennt · Prozesszeiten unqualifiziert')
    fragment=fragment.replace('Autodemo: synthetische Freigabefolge','Wasserübung: Konzeptpipetten vormontiert · Mengen aus Softwarefixture · keine Dosierqualifikation · E4 unverändert · Autodemo: synthetische Freigabefolge')
    # Keep all prior modes available. Water is selected by default, paused for
    # reduced-motion users; its playback factor defaults to actual model time.
    if len(fragment.encode())>=1_000_000:raise ValueError('Inline size budget exceeded: '+str(len(fragment.encode())))
    args.output.write_text(fragment)
    write={'format':'solidcraftbot.water-practice-l01-preview/1','fragment_sha256':m.digest(args.output),
        'base_fragment_sha256':receipt['fragment_sha256'],'water_program_sha256':checksum,'bytes':len(fragment.encode()),
        'source_files_sha256':{**program['source_files_sha256'],str(view.relative_to(m.ROOT)):m.digest(view),'scripts/render_tr01_workcell.py':m.digest(m.ROOT/'scripts/render_tr01_workcell.py'),
                              str(Path(__file__).relative_to(m.ROOT)):m.digest(__file__)},
        'display_arm_vertex_grid_mm':2,'native_solids_simplified':False,
        'native_proof':program['proof'],'tool_arm_proof_sha256':m.digest(m.OUT/'tool-arm-proof.json'),'tool_arm_proof':tool_proof,'fixture_report_sha256':program['fixture_report_sha256'],'e4_decisions_changed':False}
    (m.OUT/'preview-receipt.json').write_text(json.dumps(write,indent=2)+'\n');print(args.output,len(fragment.encode()))


if __name__=='__main__':main()
