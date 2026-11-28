"""Compose a checked Lab 3.003 preview with the opt-in live fleet."""

import hashlib
import json
import re

import build_building_walkthrough as browser
import building_fleet_progressive_presentation as geometry
import export_building_walkthrough_freecad as native
from build_lab3003_tr01_walkthrough import replace_mesh

LAB = 'Lab3003'


def checked_preview(preview, payload):
    directory = native.project_path(preview)
    paths = [native.project_path(directory / name) for name in
             ('index.html', 'preview-report.json', 'transfer-browser-check.json')]
    html, build_bytes, check_bytes = (path.read_bytes() for path in paths)
    sha = hashlib.sha256(html).hexdigest()
    build, check = json.loads(build_bytes), json.loads(check_bytes)
    if any(report.get('passed') is not True or report.get('html_sha256') != sha
           for report in (build, check)):
        raise ValueError('The laboratory preview must match its build and WebGL checks')
    match = re.search(rb'<script id="walkthrough-data" type="application/json">(.*?)</script>', html, re.S)
    if match is None:
        raise ValueError('Checked laboratory walkthrough data required')
    donor = json.loads(match.group(1))
    pins = browser.merge_pins(payload['source_files_sha256'], donor['source_files_sha256'])
    native.verify_pins(pins)
    for source, other in ((payload['scene_sources']['building'], donor['scene_sources']['building']),
                          (payload['equipment_source'], donor['equipment_source'])):
        if any(source[key] != other[key] for key in ('source', 'source_sha256')):
            raise ValueError('The laboratory and fleet must use the same building and equipment sources')
    cycle, lap = donor['lab3003_cf01_cycle'], donor['tr01_lap']
    motion = cycle['arm_motion']
    returns = cycle.get('return_samples', [])
    returned = check.get('returned', [])
    docked = check.get('lap', {})
    carriers = {row['id']: row['carrier_body_id'] for row in cycle['samples']}
    if (cycle.get('synthetic') is not True or cycle.get('hardware_qualified') is not False
            or cycle.get('arm_motion_checked') is not True or not cycle.get('docked_start')
            or len(returns) != 2 or len(carriers) != 2 or not lap.get('half_turn')
            or not lap.get('route_certificate_sha256')
            or build.get('arm_program_sha256') != motion['program_sha256']
            or build.get('collision_report_sha256') != motion['collision_report_sha256']
            or build.get('tr01_return_lap_report_sha256') != lap['route_certificate_sha256']
            or check.get('renderer') != 'webgl2' or check.get('console_errors') != []
            or [(row['id'], row['native_body_id']) for row in returned] !=
               [(row['id'], carriers[row['id']]) for row in returns]
            or docked.get('docked_s') != lap['duration_s'] or 'pivot_s' not in docked):
        raise ValueError('The verified synthetic full transfer, return and covered half-turn are required')
    proof_pins = {path.relative_to(native.ROOT).as_posix(): hashlib.sha256(raw).hexdigest()
                  for path, raw in zip(paths, (html, build_bytes, check_bytes))}
    return donor, browser.merge_pins(pins, proof_pins)


def by_id(rows):
    result = {row['id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate laboratory or building entity')
    return result


def replace_lab_rows(original, replacement):
    def belongs(row):
        return row['id'].startswith(LAB + '.')
    result = [row for row in original if not belongs(row)] + [row for row in replacement if belongs(row)]
    by_id(result)
    return result


def attach(payload, preview):
    """Replace only the laboratory display bodies in the checked building."""
    donor, pins = checked_preview(preview, payload)
    lab = by_id(payload['laboratories'])[LAB]
    checked = by_id(donor['laboratories'])[LAB]
    level = lab['level_id']
    if any(lab[key] != checked[key] for key in ('transform', 'level_id', 'area', 'interior_polygon_mm')):
        raise ValueError('The fleet and laboratory must share the exact 3.003 room frame')
    cycle, lap = donor['lab3003_cf01_cycle'], donor['tr01_lap']
    if (lap['laboratory_id'] != LAB or lap['level_id'] != level or lap['scene'] != 'building'
            or cycle['scene'] != 'building' or cycle['docked_start']['level_id'] != level
            or cycle['cover_body_id'] != lap['cover_body_id']):
        raise ValueError('The cycle and lap must use the same Lab 3.003 dock and cover')
    original, stock = payload['scenes']['building'], donor['scenes']['building']
    base_groups, checked_groups = by_id(original['groups']), by_id(stock['groups'])
    old_ids = {ident for ident, row in base_groups.items() if row.get('laboratory_id') == LAB}
    new_ids = {ident for ident, row in checked_groups.items() if row.get('laboratory_id') == LAB}
    keep_ids = base_groups.keys() - old_ids
    if (not old_ids or not new_ids or keep_ids & new_ids or set(lap['body_ids']) - new_ids
            or any(checked_groups[ident]['level_id'] != level for ident in new_ids)):
        raise ValueError('The overlay must bind unique checked 3.003 mesh bodies')
    scene = replace_mesh({**original, **geometry.packed(original, keep_ids)}, geometry.packed(stock, new_ids))
    objects = replace_lab_rows(payload['objects'], donor['objects'])
    object_by_id = by_id(objects)
    if any(set(row['moving_body_ids']) - (keep_ids | new_ids) for row in objects):
        raise ValueError('The overlay would remove an articulated body')
    for config in (lap, cycle['docked_start']):
        for ident, state in config['fixture_states'].items():
            obj = object_by_id.get(ident)
            if obj is None or obj.get('initial_state', obj['reference_state']) != state:
                raise ValueError('The shared world must start in the checked laboratory fixture state: ' + ident)
    stop_ids = {cycle['stop_id'], lap['stop_id']}
    donor_stops = by_id(donor['stops'])
    stops = [row for ident, row in donor_stops.items() if ident in stop_ids]
    if (len(stops) != 2 or stop_ids & by_id(payload['stops']).keys()
            or any(row['scene'] != 'building' or row['level_id'] != level for row in stops)):
        raise ValueError('The shared laboratory needs both unique checked viewpoints')
    isolation = {**payload['isolation'], 'body_ids': sorted(
        (set(payload['isolation']['body_ids']) - old_ids) | (set(donor['isolation']['body_ids']) & new_ids))}
    hidden = {**payload['hidden_body_ids'], 'building': sorted(
        (set(payload['hidden_body_ids']['building']) - old_ids) |
        (set(donor['hidden_body_ids']['building']) & new_ids))}
    wall = payload['camera_wall']
    source_wall = donor['camera_wall']
    cameras = replace_lab_rows(wall['cameras'], source_wall['cameras'])
    if any(row.get('mount_body_id') and row['mount_body_id'] not in keep_ids | new_ids for row in cameras):
        raise ValueError('The overlay would remove a physical camera mount')
    before, after = by_id(wall['cameras']), by_id(cameras)
    defaults = []
    for ident in wall['default_assignments']:
        if ident is not None and ident not in after:
            device = before[ident]['device_id']
            matches = [row['id'] for row in cameras if row['device_id'] == device
                       and row['availability'] == 'available']
            if len(matches) != 1:
                raise ValueError('The overlay would lose a default monitor assignment: ' + ident)
            ident = matches[0]
        defaults.append(ident)
    return {**payload, 'scenes': {'building': scene}, 'objects': objects,
            'robots': replace_lab_rows(payload['robots'], donor['robots']),
            'laboratories': [checked if row['id'] == LAB else row for row in payload['laboratories']],
            'isolation': isolation, 'stops': [*payload['stops'], *stops], 'hidden_body_ids': hidden,
            'camera_wall': {**wall, 'cameras': cameras, 'default_assignments': defaults},
            'source_files_sha256': pins, 'tr01_lap': lap, 'lab3003_cf01_cycle': cycle}


def viewer(template):
    """Bind the overlay to the worker only in the compact fleet viewer."""
    replacements = {
        '    const fixtureConfig=lapConfig||dockedStart;': """    const fixtureConfig=lapConfig||dockedStart;
    const labTransport=globalThis.__bf01EarlyTransport?.transport;
    if(!processThenLap||!labTransport?.reportLab3003Docked)throw Error('Missing live laboratory reservation transport');
    let labReservation=null;
    root.dataset.lab3003Release='reserved';
    function startReservedLab(now){
      const fleet=window.__buildingFleet;
      if(!fleet?.connected||fleet.frozen||fleet.time_s<=0||!progressiveGeometry?.levelReady(lapConfig.level_id)||
         !checkLapFixtures())return false;
      const state=labTransport.state;
      if(state.status!=='ready'||state.paused||state.lab3003_reserved!==true||
         !state.lab3003_reservation_id||!state.session_id)return false;
      if(!cf01.start(now,true))return false;
      labReservation={id:state.lab3003_reservation_id,session:state.session_id};
      return true;
    }
    function confirmLabDock(){
      if(!labReservation||root.dataset.lab3003Release!=='reserved'||!lap.arrived||!transportReady())return;
      root.dataset.lab3003Release='pending';
      requestRender();
      labTransport.reportLab3003Docked(labReservation.id).then(ack=>{
        if(ack.status!=='confirmed'||ack.session_id!==labReservation.session||
           ack.reservation_id!==labReservation.id||ack.lab3003_reserved!==false)throw Error('Unexpected laboratory release receipt');
        root.dataset.lab3003Release='confirmed';
        requestRender();
      }).catch(error=>{
        root.dataset.lab3003Release='failed';
        announcement.textContent='Laborbucht · Freigabe nicht bestätigt · '+error.message;
        requestRender();
      });
    }""",
        '      if(!cf01||document.hidden)return false;':
            """      if(!cf01||document.hidden)return false;
      if(cf01.snapshot.state==='ready')return startReservedLab(now);""",
        "        lapReset.disabled=state!=='docked';": '        lapReset.disabled=true;',
        '      const next=lapMessage||{ready:': '''      const releaseLabel={pending:'Andockung erkannt · Flottenfreigabe ausstehend',
        confirmed:'Wieder angedockt · Flottenfreigabe bestätigt',failed:'Andockung erkannt · Flottenfreigabe nicht bestätigt'};
      const next=releaseLabel[root.dataset.lab3003Release]||lapMessage||{ready:''',
        "        if(cf01?.active||(processThenLap&&lap.snapshot.state!=='docked'))return;":
            "        if(processThenLap||cf01?.active)return;",
        "        cf01Play.disabled=processThenLap&&station.state==='completed';":
            "        cf01Play.disabled=station.state==='ready'||station.state==='completed';",
        "        else if((!processThenLap||state==='ready')&&checkLapFixtures()){":
            "        else if(!processThenLap&&checkLapFixtures()){",
        '        const cf01Changed=advanceCF01(now);':
            '        const cf01Changed=advanceCF01(now);\n        confirmLabDock();',
    }
    for before, after in replacements.items():
        if template.count(before) != 1:
            raise ValueError('The shared laboratory viewer hook changed: ' + before)
        template = template.replace(before, after)
    return template
