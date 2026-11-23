"""Lossless, opt-in visual chunks from the checked BF01 native world."""
import base64
import copy
import gzip
import hashlib
import json
import re
from pathlib import Path
import shutil
import struct

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.walkthrough-progressive-geometry/1'
CHUNK = 'solidcraftbot.walkthrough-geometry-chunk/1'
SCRIPT = ROOT / 'scripts/walkthrough_progressive_geometry.js'
WORKER = ROOT / 'scripts/walkthrough_geometry_worker.mjs'


def encoded(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def packed(scene, selected):
    """Retain exact source float32 bytes and triangle order for selected bodies."""
    positions = base64.b64decode(scene['positions_base64'], validate=True)
    normals = base64.b64decode(scene['normals_base64'], validate=True)
    indices = base64.b64decode(scene['indices_base64'], validate=True)
    if (len(positions) != scene['vertex_count'] * 12 or len(normals) != len(positions)
            or len(indices) != scene['index_count'] * 4):
        raise ValueError('Exact native scene buffer sizes required')
    vertices = {}
    out_positions, out_normals, out_indices = bytearray(), bytearray(), bytearray()
    groups = []
    for group in scene['groups']:
        if group['id'] not in selected:
            continue
        current = copy.deepcopy(group)
        current['index_start'] = len(out_indices) // 4
        for offset in range(group['index_start'] * 4,
                            (group['index_start'] + group['index_count']) * 4, 4):
            index = struct.unpack_from('<I', indices, offset)[0]
            if index >= scene['vertex_count']:
                raise ValueError('Native triangle index outside its source vertices')
            if index not in vertices:
                vertices[index] = len(vertices)
                out_positions.extend(positions[index * 12:index * 12 + 12])
                out_normals.extend(normals[index * 12:index * 12 + 12])
            out_indices.extend(struct.pack('<I', vertices[index]))
        groups.append(current)
    return {'positions_base64': base64.b64encode(out_positions).decode(),
            'normals_base64': base64.b64encode(out_normals).decode(),
            'indices_base64': base64.b64encode(out_indices).decode(),
            'vertex_count': len(vertices), 'index_count': len(out_indices) // 4,
            'groups': groups}


def derive(payload, output, *, world_report_sha256):
    """Create one exact initial EG scene and deferred, hash-pinned floor chunks."""
    output = Path(output)
    if set(payload.get('scenes', {})) != {'building'}:
        raise ValueError('One checked shared building scene required')
    scene = payload['scenes']['building']
    groups = scene['groups']
    if len({g['id'] for g in groups}) != len(groups):
        raise ValueError('Unique native body identifiers required')
    expected = 0
    for group in sorted(groups, key=lambda g: g['index_start']):
        if (group['index_start'] != expected or group['index_count'] < 0
                or group['index_count'] % 3):
            raise ValueError('Source groups must partition every native triangle')
        expected += group['index_count']
    if expected != scene['index_count']:
        raise ValueError('Source groups omit native triangles')
    levels = [row['id'] for row in payload['levels']]
    if ('EG' not in levels or any(not isinstance(level, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', level) for level in levels)
            or any(g['level_id'] not in [None, *levels] for g in groups)):
        raise ValueError('Known source levels and initial EG required')
    source_hash = digest(encoded(scene))
    script_hash = digest(SCRIPT.read_bytes())
    prefix = 'geometry/' + source_hash[:16] + '-' + script_hash[:12]
    asset_dir = output / prefix
    asset_dir.mkdir(parents=True, exist_ok=True)
    initial_ids = {g['id'] for g in groups if g['level_id'] in (None, 'EG')}
    initial = packed(scene, initial_ids)
    initial_groups = {g['id']: g for g in initial['groups']}
    initial['groups'] = []
    for source in groups:
        if source['id'] in initial_groups:
            initial['groups'].append(initial_groups[source['id']])
        else:
            pending = copy.deepcopy(source)
            pending['pending_geometry'] = True
            pending['pending_index_count'] = source['index_count']
            pending['index_count'] = 0
            pending['index_start'] = initial['index_count']
            initial['groups'].append(pending)
    initial_scene = {**copy.deepcopy(scene), **initial}
    chunks = []
    all_ids = set(initial_ids)
    for level in levels:
        if level == 'EG':
            continue
        selected = {g['id'] for g in groups if g['level_id'] == level}
        if not selected:
            continue
        if all_ids & selected:
            raise ValueError('A native body cannot occur in two visual chunks')
        all_ids.update(selected)
        chunk = {'format': CHUNK, 'scene_id': 'building', 'level_id': level,
                 'source_scene_sha256': source_hash, **packed(scene, selected)}
        raw = encoded(chunk)
        compressed = gzip.compress(raw, mtime=0)
        name = level + '.json.gz'
        (asset_dir / name).write_bytes(compressed)
        chunks.append({'level_id': level, 'url': prefix + '/' + name,
                       'sha256': digest(compressed), 'bytes': len(compressed),
                       'decoded_bytes': len(raw), 'encoding': 'gzip',
                       'group_count': len(selected), 'index_count': chunk['index_count']})
    if all_ids != {g['id'] for g in groups}:
        raise ValueError('Progressive partitions omit a native body')
    assets = {}
    for source, name in ((SCRIPT, 'geometry.js'), (WORKER, 'worker.mjs')):
        shutil.copyfile(source, asset_dir / name)
        assets[name] = {'url': prefix + '/' + name,
                        'sha256': digest(source.read_bytes()), 'bytes': source.stat().st_size}
    descriptor = {'format': FORMAT, 'scene_id': 'building',
                  'source_scene_sha256': source_hash,
                  'world_report_sha256': world_report_sha256,
                  'initial_levels': ['EG'], 'shared_geometry_loaded': True,
                  'full_group_count': len(groups), 'full_index_count': scene['index_count'],
                  'initial_loaded_groups': len(initial_ids),
                  'chunks': chunks, 'assets': assets,
                  'scope': 'Exact native visual subsets; unloaded level entry waits for verified geometry. Live fleet physics uses its independent complete source-bound geometry.'}
    value = {**copy.deepcopy(payload), 'scenes': {'building': initial_scene},
             'progressive_geometry': descriptor}
    if 'stops' in payload:
        initial_stop = next((stop for stop in payload['stops'] if stop['id'] == 'camera-wall' and stop.get('level_id') == 'EG'), None)
        if initial_stop is None:
            raise ValueError('Source-derived EG camera-wall viewpoint required')
        value['default_stop'] = value['default_stop_id'] = initial_stop['id']
    return value


def attach(html):
    """Opt-in hooks leave the ordinary standalone viewer unchanged."""
    viewer_start = "(() => {\n  'use strict';\n  const root=document.getElementById('building-walkthrough')"
    if html.count(viewer_start) != 1:
        raise ValueError('Progressive native viewer initialization anchor changed')
    html = html.replace(viewer_start, viewer_start.replace('(() => {', '(async () => {'))
    gate_anchor = "  try {\n    const data=JSON.parse(document.getElementById('walkthrough-data').textContent);"
    gate = r'''  try {
    const early=globalThis.__bf01EarlyTransport;
    if(early){
      if(!early.transport?.ready||typeof early.transport.ready.then!=='function')throw Error('Live simulation readiness is unavailable');
      loading.textContent='Live-Patrouille wird gestartet …';root.dataset.initialization='waiting_for_live_engine';
      const first=await early.transport.ready;
      if(first?.status!=='ready')throw Error('Die Live-Patrouille konnte nicht gestartet werden.');
      root.dataset.initialization='preparing_native_view';
    }
    const data=JSON.parse(document.getElementById('walkthrough-data').textContent);'''
    if html.count(gate_anchor) != 1:
        raise ValueError('Progressive source decode initialization anchor changed')
    html = html.replace(gate_anchor, gate)
    replacements = {
        '  let gl=null,frameRequest=null;': '  let gl=null,frameRequest=null,progressiveGeometry=null;',
        "      uploadBuffer(gl.ELEMENT_ARRAY_BUFFER,combined);": "      const elementBuffer=uploadBuffer(gl.ELEMENT_ARRAY_BUFFER,combined);",
        'const result={collider,picker:complete?null:': 'const result={elementBuffer,collider,picker:complete?null:',
        'nativeGroups:source.groups.length,opacityOverrides': 'nativeGroups:source.groups.filter(g=>g.index_count).length,opacityOverrides',
        '      const delta=[dx*speed*seconds,dy*speed*seconds,z*verticalSpeed*seconds];': '      const delta=[dx*speed*seconds,dy*speed*seconds,z*verticalSpeed*seconds];\n      if(progressiveGeometry&&!progressiveGeometry.allowMove(eye,delta))return;',
        '    function setStop(id){': "    function setStop(id){\n      const pendingStop=stops.find(s=>s.id===id);if(progressiveGeometry&&!progressiveGeometry.levelReady(pendingStop?.level_id)){progressiveGeometry.requestView(pendingStop.level_id,()=>setStop(id));return {status:'loading_geometry'};}",
        '    function viewObject(id){': "    function viewObject(id){\n      const pendingObject=objectStates.get(id);if(progressiveGeometry&&!progressiveGeometry.levelReady(pendingObject?.config.level_id)){progressiveGeometry.requestView(pendingObject.config.level_id,()=>viewObject(id));return {status:'loading_geometry'};}",
        "    levelSelect.addEventListener('change',()=>{": "    levelSelect.addEventListener('change',()=>{if(progressiveGeometry&&!progressiveGeometry.levelReady(levelSelect.value)){const pendingLevel=levelSelect.value;levelSelect.value=selectedLevel;progressiveGeometry.requestView(pendingLevel,()=>{levelSelect.value=pendingLevel;levelSelect.dispatchEvent(new Event('change'));});return;}",
    }
    for before, after in replacements.items():
        if html.count(before) != 1:
            raise ValueError('Progressive viewer hook changed: ' + before)
        html = html.replace(before, after)
    anchor = '    window.__buildingWalkthrough=Object.freeze({'
    if html.count(anchor) != 1:
        raise ValueError('Progressive viewer bridge anchor changed')
    hook = r'''
    progressiveGeometry=WalkthroughProgressiveGeometry.attach({data,stage:stageNode,root,
      currentLevel:()=>selectedLevel,announce:text=>announcement.textContent=text,
      apply:next=>{
        for(const [key,scene]of [...sceneCache])if(key.startsWith('building:')){gl.deleteVertexArray(scene.vao);gl.deleteBuffer(scene.elementBuffer);sceneCache.delete(key);}
        const mesh=meshCache.get('building');if(mesh){gl.deleteBuffer(mesh.positionBuffer);gl.deleteBuffer(mesh.normalBuffer);meshCache.delete('building');}
        data.scenes.building=next;requestRender();
      }});
    window.__walkthroughProgressiveGeometry=progressiveGeometry;
'''
    html = html.replace(anchor, hook + anchor)
    html = html.replace('      get sceneStats(){', '      get visualGeometry(){return progressiveGeometry?.snapshot??null;},\n      get sceneStats(){', 1)
    before = "      const positions=decode(source.positions_base64,'float',source.vertex_count*3,'positions'),normals=decode(source.normals_base64,'float',source.vertex_count*3,'normals'),indices=decode(source.indices_base64,'uint',source.index_count,'indices');"
    after = "      const packed=source.geometry_buffers;const positions=packed?new Float32Array(packed.positions):decode(source.positions_base64,'float',source.vertex_count*3,'positions'),normals=packed?packed.normals:decode(source.normals_base64,'float',source.vertex_count*3,'normals'),indices=packed?packed.indices:decode(source.indices_base64,'uint',source.index_count,'indices');"
    if html.count(before) != 1:
        raise ValueError('Progressive native buffer hook changed')
    html = html.replace(before, after)
    script = SCRIPT.read_text().replace('</script', '<\\/script')
    return html.replace('</head>', '<script>' + script + '</script></head>')
