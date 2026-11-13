"""Render the source-derived handoff preview as a self-contained inline fragment."""
import argparse,base64,gzip,json,struct,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def central_shelf_bounds():
    import lab_room_model as room
    source=room.load();parameters=room.parameters(source);expanded=room.expanded(source,parameters)
    bodies={body['id'] for body in expanded['bodies'] if body['component']=='IslandShelf'}
    result=[]
    for operation in expanded['operations']:
        if operation['body'] not in bodies or operation['action']!='create':continue
        shape=room.numeric_shape(operation['shape'],parameters)
        if shape['kind']!='box':raise ValueError('Unsupported central shelf display boundary')
        result.append({'body':operation['body'],'min':shape['origin'],
                       'max':[a+b for a,b in zip(shape['origin'],shape['size'])]})
    return result

def compact_mesh(encoded,shelf_bounds=(),native_shell=None):
    raw=gzip.decompress(base64.b64decode(encoded));count,groups=struct.unpack_from('<II',raw)
    remap=[];seen={};unique=[]
    for i in range(count):
        xyz=struct.unpack_from('<hhh',raw,8+i*6)
        if xyz not in seen:seen[xyz]=len(unique);unique.append(xyz)
        remap.append(seen[xyz])
    classified={}
    offset=8+count*6
    for i in range(groups):
        kind,length=struct.unpack_from('<II',raw,offset);offset+=8
        indices=struct.unpack_from('<'+'I'*length,raw,offset);offset+=length*4
        if kind==1 and native_shell is not None:continue
        for j in range(0,length,3):
            triangle=[remap[k] for k in indices[j:j+3]];target=kind
            if kind==2 and any(all(bounds['min'][axis]-.26<=unique[k][axis]/4<=bounds['max'][axis]+.26
                                   for k in triangle for axis in range(3)) for bounds in shelf_bounds):target=11
            classified.setdefault(target,[]).extend(triangle)
    if native_shell is not None:
        for part in native_shell['parts']:
            mapping=[]
            for point in part['vertices_qmm']:
                xyz=tuple(point)
                if xyz not in seen:seen[xyz]=len(unique);unique.append(xyz)
                mapping.append(seen[xyz])
            classified.setdefault(part['kind'],[]).extend(mapping[k] for face in part['triangles'] for k in face)
    payload=struct.pack('<II',len(unique),len(classified))+b''.join(struct.pack('<hhh',*p) for p in unique)
    for kind,indices in classified.items():
        payload+=struct.pack('<II',kind,len(indices))+struct.pack('<'+'I'*len(indices),*indices)
    return base64.b64encode(gzip.compress(payload,9)).decode()
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);args=parser.parse_args()
    report=json.loads((ROOT/'cad/tr01-workcell/shared-build-report.json').read_text())
    digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    # Presentation-only revisions consume the pinned, checked geometry.
    # Their current versions are bound separately in the preview receipt.
    presentation={'scripts/tr01_workcell_player.html','scripts/render_tr01_workcell.py'}
    for path,expected in report['source_files_sha256'].items():
        if path in presentation:continue
        if digest(ROOT/path)!=expected:raise ValueError('Preview source changed: '+path)
    preview=ROOT/report['files']['preview_data']
    if digest(preview)!=report['artifact_sha256']['preview_data']:raise ValueError('Preview artifact changed')
    data=json.loads(preview.read_text())
    shell_path=ROOT/'exports/tr01-workcell/daylight-shell.json'
    shell=json.loads(shell_path.read_text())
    for path,expected in shell['source_files_sha256'].items():
        if digest(ROOT/path)!=expected:raise ValueError('Daylight shell source changed: '+path)
    bounds=central_shelf_bounds()
    data['mesh']=compact_mesh(data['mesh'],bounds,shell)
    data['central_shelf_bodies']=[item['body'] for item in bounds]
    import l01_daylight
    data['daylight']=l01_daylight.derive()
    import l01_opposing_traffic
    data['traffic']=l01_opposing_traffic.validated_result()
    if not data['traffic']['all_arrived'] or min(data['traffic']['clearance'][key] for key in ('car_car_clearance_lower_mm','car_person_clearance_lower_mm'))<data['traffic']['settings']['controller']['clearance_mm']:raise ValueError('Incomplete or unsafe local-traffic fixture')
    encoded=base64.b64encode(gzip.compress(json.dumps(data,separators=(',',':')).encode(),9)).decode()
    daylight_view=ROOT/'scripts/l01_daylight_view.js'
    fragment=(ROOT/'scripts/tr01_workcell_player.html').read_text().replace('__DATA__',encoded).replace('__DAYLIGHT_SHADER_AND_ENGINE__',daylight_view.read_text()).replace('__LOCAL_TRAFFIC_VIEW__',(ROOT/'scripts/l01_local_traffic_view.js').read_text())
    if len(fragment.encode())>=1000000:raise ValueError('Inline size budget exceeded')
    args.output.write_text(fragment)
    receipt={'workcell_revision':report['revision'],'source_sha256':report['source_sha256'],'fragment_sha256':digest(args.output),
             'template_sha256':digest(ROOT/'scripts/tr01_workcell_player.html'),'renderer_sha256':digest(__file__),'bytes':len(fragment.encode())}
    receipt['local_traffic_source_files_sha256']={**data['traffic']['source_files_sha256'],'scripts/l01_local_traffic_view.js':digest(ROOT/'scripts/l01_local_traffic_view.js')}
    receipt['local_traffic_native_pose_coverage']=data['traffic']['native_pose_coverage']
    receipt['presentation_only_revision']=False
    receipt['native_geometry_reused_without_changes']=True
    receipt['original_handoff_motion_reused_without_changes']=True
    receipt['local_traffic_motion_has_new_native_proof']=True
    receipt['daylight_source_files_sha256']={**data['daylight']['source_files_sha256'],str(daylight_view.relative_to(ROOT)):digest(daylight_view)}
    receipt['daylight_source_files_sha256'].update({str(shell_path.relative_to(ROOT)):digest(shell_path),**shell['source_files_sha256']})
    (ROOT/'exports/tr01-workcell/preview-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(len(fragment.encode()),args.output)
if __name__=='__main__':main()
