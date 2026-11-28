"""Checks for the optional checked laboratory overlay and its viewer gates."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import building_fleet_lab3003 as lab
import export_building_walkthrough_freecad as native


class LabOverlayTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(temp.cleanup)
        self.preview = Path(temp.name)
        self.source = self.preview / 'world-source.json'
        self.source.write_text('{}\n')
        name = self.source.relative_to(ROOT).as_posix()
        sha = native.digest(self.source)
        ref = {'source': name, 'source_sha256': sha}
        room = {'id': lab.LAB, 'level_id': 'OG3', 'area': 'R3_003',
                'transform': [[1, 0], [0, 1]], 'interior_polygon_mm': [[0, 0], [1, 1], [1, 0]]}
        stop = {'id': 'camera-wall', 'level_id': 'EG', 'scene': 'building'}
        fixture = {'id': 'Lab3003.fixture', 'reference_state': 'open', 'moving_body_ids': ['fixture']}
        camera = {'id': 'Lab3003.TR01.Overview', 'device_id': 'Lab3003.TR01', 'availability': 'available'}
        hall_camera = {'id': 'hall.camera', 'device_id': 'hall', 'mount_body_id': 'hall'}
        self.base = {'source_files_sha256': {name: sha}, 'scene_sources': {'building': ref},
                     'equipment_source': ref, 'laboratories': [room],
                     'scenes': {'building': self.scene('hall', 'fixture', 'stock')},
                     'objects': [fixture], 'robots': [], 'isolation': {'body_ids': ['hall', 'fixture', 'stock']},
                     'stops': [stop], 'hidden_body_ids': {'building': ['hall', 'stock'], 'other': ['marker']},
                     'camera_wall': {'cameras': [camera, hall_camera],
                                     'default_assignments': [camera['id'], hall_camera['id'], None]}}
        self.donor = copy.deepcopy(self.base)
        self.donor['scenes']['building'] = self.scene('hall', 'fixture', 'cover', 'tube1', 'tube2')
        self.donor['isolation']['body_ids'] = ['fixture', 'cover', 'tube1', 'tube2']
        self.donor['hidden_body_ids'] = {'building': ['tube1']}
        self.donor['camera_wall']['cameras'][0].update(id='Lab3003.TR01.Awareness', mount_body_id='cover')
        self.donor['stops'] += [{**stop, 'id': ident, 'level_id': 'OG3'} for ident in ('lap', 'cycle')]
        self.donor['tr01_lap'] = {'stop_id': 'lap', 'duration_s': 2, 'half_turn': {'delta_rad': 3.14},
                                 'cover_body_id': 'cover', 'body_ids': ['cover', 'tube1', 'tube2'],
                                 'route_certificate_sha256': 'c'*64,
                                 'laboratory_id': lab.LAB, 'level_id': 'OG3', 'scene': 'building',
                                 'fixture_states': {fixture['id']: 'open'}}
        self.donor['lab3003_cf01_cycle'] = {
            'stop_id': 'cycle', 'cover_body_id': 'cover', 'scene': 'building',
            'synthetic': True, 'hardware_qualified': False, 'arm_motion_checked': True,
            'arm_motion': {'program_sha256': 'a'*64, 'collision_report_sha256': 'b'*64},
            'docked_start': {'level_id': 'OG3', 'fixture_states': {fixture['id']: 'open'}},
            'samples': [{'id': ident, 'carrier_body_id': ident} for ident in ('tube1', 'tube2')],
            'return_samples': [{'id': ident} for ident in ('tube2', 'tube1')]}
        self.check = {'renderer': 'webgl2', 'console_errors': [], 'lap': {'pivot_s': 1, 'docked_s': 2},
                      'returned': [{'id': ident, 'native_body_id': ident} for ident in ('tube2', 'tube1')]}

    @staticmethod
    def scene(*ids):
        builder = native.MeshBuilder()
        for ident in ids:
            builder.add(ident, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)],
                        {'color': [0.5, 0.5, 0.5], 'opacity': 1.0},
                        level_id='EG' if ident == 'hall' else 'OG3', role='fixture')
            if ident != 'hall':
                builder.groups[-1]['laboratory_id'] = lab.LAB
        return builder.result()

    def record_preview(self, **changes):
        html = '<script id="walkthrough-data" type="application/json">' + json.dumps(self.donor) + '</script>'
        (self.preview / 'index.html').write_text(html)
        sha = hashlib.sha256(html.encode()).hexdigest()
        build = {'passed': True, 'html_sha256': sha, 'arm_program_sha256': 'a'*64,
                 'collision_report_sha256': 'b'*64, 'tr01_return_lap_report_sha256': 'c'*64, **changes}
        (self.preview / 'preview-report.json').write_text(json.dumps(build))
        (self.preview / 'transfer-browser-check.json').write_text(
            json.dumps({'passed': True, 'html_sha256': sha, **self.check}))

    def test_overlay_replaces_only_lab_and_preserves_camera_assignments(self):
        self.record_preview()
        before = copy.deepcopy(self.base)
        result = lab.attach(self.base, self.preview)
        self.assertEqual(self.base, before)
        self.assertEqual(set(lab.by_id(result['scenes']['building']['groups'])),
                         {'hall', 'fixture', 'cover', 'tube1', 'tube2'})
        self.assertEqual(result['hidden_body_ids'], {'building': ['hall', 'tube1'], 'other': ['marker']})
        self.assertEqual(result['camera_wall']['default_assignments'],
                         ['Lab3003.TR01.Awareness', 'hall.camera', None])
        self.assertEqual([stop['id'] for stop in result['stops']], ['camera-wall', 'lap', 'cycle'])
        self.assertEqual(len(result['source_files_sha256']), 4)
        native.verify_pins(result['source_files_sha256'])

    def test_rejects_stale_shared_source_and_conflicting_frame(self):
        self.record_preview()
        self.source.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Changed or missing checked input'):
            lab.attach(self.base, self.preview)
        self.source.write_text('{}\n')
        self.donor['laboratories'][0]['area'] = 'different'
        self.record_preview()
        with self.assertRaisesRegex(ValueError, 'exact 3.003 room frame'):
            lab.attach(self.base, self.preview)

    def test_rejects_wrong_browser_return_and_route_receipt(self):
        self.check['returned'].reverse()
        self.record_preview()
        with self.assertRaisesRegex(ValueError, 'verified synthetic full transfer'):
            lab.attach(self.base, self.preview)
        self.check['returned'].reverse()
        self.record_preview(tr01_return_lap_report_sha256='d'*64)
        with self.assertRaisesRegex(ValueError, 'verified synthetic full transfer'):
            lab.attach(self.base, self.preview)
        self.record_preview()
        (self.preview / 'index.html').write_text('different')
        with self.assertRaisesRegex(ValueError, 'match its build and WebGL checks'):
            lab.attach(self.base, self.preview)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for the viewer hook')
    def test_viewer_waits_for_ready_geometry_and_for_worker_receipt(self):
        template = (ROOT / 'scripts/building_walkthrough_viewer.html').read_text()
        viewer = lab.viewer(template)
        snippet = viewer[viewer.index('    const labTransport='):viewer.index('    const createCF01=')]
        result = subprocess.run(['node', '-'], input="""const assert = require('node:assert/strict');
const root={dataset:{}}, announcement={}, processThenLap=true, lapConfig={level_id:'OG3'};
const requestRender=()=>{};
let resolve, emissions=[], geometry=false, fixtures=true, ready=false;
const lap={arrived:false}, transportReady=()=>ready;
const progressiveGeometry={levelReady:level=>level==='OG3'&&geometry};
const window={__buildingFleet:{connected:false,frozen:false,time_s:0}};
const checkLapFixtures=()=>fixtures;
const cf01={start:(now,docked)=>{assert.equal(docked,true);emissions.push(now);return true;}};
const worker={state:{status:'ready',paused:false,lab3003_reserved:true,
                    lab3003_reservation_id:'reservation',session_id:'session'},
              reportLab3003Docked:id=>{emissions.push(id);return new Promise(r=>resolve=r);}};
globalThis.__bf01EarlyTransport={transport:worker};
""" + snippet + """
(async()=>{
  assert.equal(startReservedLab(1),false);
  Object.assign(window.__buildingFleet,{connected:true,time_s:2});
  assert.equal(startReservedLab(2),false);
  geometry=true;fixtures=false;
  assert.equal(startReservedLab(3),false);
  fixtures=true;worker.state.lab3003_reserved=false;
  assert.equal(startReservedLab(4),false);
  worker.state.lab3003_reserved=true;
  assert.equal(startReservedLab(5),true);
  confirmLabDock();assert.equal(root.dataset.lab3003Release,'reserved');
  lap.arrived=true;confirmLabDock();assert.equal(root.dataset.lab3003Release,'reserved');
  ready=true;confirmLabDock();confirmLabDock();
  assert.equal(root.dataset.lab3003Release,'pending');
  assert.deepEqual(emissions,[5,'reservation']);
  resolve({status:'confirmed',session_id:'session',reservation_id:'reservation',lab3003_reserved:false});
  await new Promise(setImmediate);
  assert.equal(root.dataset.lab3003Release,'confirmed');
})().catch(error=>{console.error(error);process.exitCode=1;});
""", text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
