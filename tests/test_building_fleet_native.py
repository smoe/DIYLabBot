"""Pinned native-vehicle inputs must fail closed before loading any CAD runtime."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import export_building_fleet_vehicle_freecad as exporter
import tr01_camera_model as kit


class NativeVehicleInputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        names=['model/tr01-awareness-camera.shared.json','model/tr01-awareness-camera.schema.json','model/sample-transport-tr01.shared.json','model/camera.schema.json','scripts/tr01_camera_model.py','scripts/build_tr01_awareness.py','scripts/build_tr01_awareness_freecad.py']
        pins={}
        for name in names:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p);pins[name]=kit.digest(p)
        # Synthetic bytes deliberately are not executed. This fixture checks the
        # proof-consumer's integrity boundary, not a fabricated native CAD pass.
        for n in ['freecad','solidcraft']:(self.root/n).write_bytes(('synthetic-'+n).encode())
        source=kit.expanded(kit.load())
        self.report={'format':'solidcraftbot.tr01-awareness-cross-cad/1','passed':True,'source_files_sha256':pins,'files':{'freecad':'freecad','solidcraft':'solidcraft'},'artifact_sha256':{n:kit.digest(self.root/n)for n in ['freecad','solidcraft']},'body_count':len(source['bodies']),'camera_frame':source['camera_frame']}
        self.path=self.root/'proof.json';self.write()

    def write(self):self.path.write_text(json.dumps(self.report))

    def test_fixture_integrity_without_loading_cad(self):
        before=sys.modules.get('FreeCAD')
        self.assertEqual(exporter.checked_camera_report(self.path,self.root)['body_count'],35)
        self.assertIs(sys.modules.get('FreeCAD'),before)

    def test_failed_stale_or_incomplete_proof_rejected(self):
        changes=[lambda d:d.update(passed=False),lambda d:d.update(format='other'),lambda d:d.update(body_count=34),lambda d:d['source_files_sha256'].pop('model/sample-transport-tr01.shared.json'),lambda d:d['files'].pop('solidcraft'),lambda d:d['camera_frame'].update(origin_mm=[0,0,0])]
        original=copy.deepcopy(self.report)
        for change in changes:
            with self.subTest(change=change):
                self.report=copy.deepcopy(original);change(self.report);self.write()
                with self.assertRaises(ValueError):exporter.checked_camera_report(self.path,self.root)

    def test_changed_source_and_artifact_bytes_rejected(self):
        for name in ['model/tr01-awareness-camera.shared.json','freecad']:
            with self.subTest(name=name):
                p=self.root/name;before=p.read_bytes();p.write_bytes(before+b'changed')
                with self.assertRaises(ValueError):exporter.checked_camera_report(self.path,self.root)
                p.write_bytes(before)

    def test_external_paths_and_nonfinite_tolerances_rejected(self):
        self.report['files']['freecad']='../outside';self.write()
        with self.assertRaises(ValueError):exporter.checked_camera_report(self.path,self.root)
        for value in [0,-1,True,float('nan'),float('inf'),3]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):exporter.export('unused','unused',deflection_mm=value)


if __name__=='__main__':unittest.main()
