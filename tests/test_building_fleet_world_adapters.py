"""Keep BF01 physical inputs independent of browser-only overlays.

Small manifest/mesh fixtures exercise adapters only. They are never native
qualifications, completed fleet programs or browser demo outputs.
"""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from urllib.parse import urljoin

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import build_building_fleet_demo as browser
import build_building_walkthrough as viewer
import export_building_walkthrough_freecad as native
import run_building_fleet as cli
import walkthrough_world as world


class WorldAdapterTests(unittest.TestCase):
    def world_fixture(self,directory):
        root=Path(directory)
        pins={'scripts/walkthrough_world.py':native.digest(browser.ROOT/'scripts/walkthrough_world.py')}
        manifest={'format':'solidcraftbot.building-walkthrough/1',
                  'source_files_sha256':pins,'stops':[],'objects':[]}
        bundle={'format':native.FORMAT,'source_files_sha256':pins,'scenes':{'building':{'groups':[]}}}
        (root/'native-mesh.json').write_text(json.dumps(bundle))
        report=world.write(root,manifest,{})
        return report,manifest,bundle

    def test_checked_world_renders_without_browser_report_or_overlay(self):
        with tempfile.TemporaryDirectory(dir=browser.ROOT/'exports')as directory:
            report,manifest,bundle=self.world_fixture(directory)
            original={path:path.read_bytes()for path in (viewer.TEMPLATE,viewer.INTERACTION_SCRIPT)}
            before=copy.deepcopy(manifest)
            html,pins=browser.world_presentation(report)
            self.assertFalse((Path(directory)/'build-report.json').exists())
            encoded=re.search(r'<script id="walkthrough-data" type="application/json">(.*?)</script>',html,re.S)
            self.assertIsNotNone(encoded)
            payload=json.loads(encoded[1])
            self.assertEqual(payload,{**manifest,'scenes':bundle['scenes']})
            self.assertEqual(manifest,before)
            self.assertNotIn('camera_wall',payload)
            self.assertFalse(world.OVERLAY_SOURCES&set(manifest['source_files_sha256']))
            for name in ('scripts/build_building_walkthrough.py','scripts/building_walkthrough_viewer.html',
                         'scripts/walkthrough_interaction.js','scripts/templates/quintic_motion.js',
                         'scripts/walkthrough_robots.js','scripts/camera_monitor_wall.js','scripts/monitor_frustum.js',
                         'scripts/seminar_projection.js'):
                self.assertEqual(pins[name],native.digest(browser.ROOT/name))
            self.assertEqual(pins[str(report.relative_to(browser.ROOT))],native.digest(report))
            self.assertTrue(all(path.read_bytes()==raw for path,raw in original.items()))

    def test_presentation_rejects_browser_report_and_changed_world_artifact(self):
        with tempfile.TemporaryDirectory(dir=browser.ROOT/'exports')as directory:
            report,_,_=self.world_fixture(directory)
            with self.assertRaisesRegex(ValueError,'separate physical world'):
                browser.world_presentation(report.with_name('build-report.json'))
            mesh=Path(directory)/'native-mesh.json';mesh.write_text(mesh.read_text()+' ')
            with self.assertRaisesRegex(ValueError,'Changed walkthrough artifact'):
                browser.world_presentation(report)

    def test_renderer_source_change_during_embedding_fails_closed(self):
        for attribute in ('TEMPLATE','SEMINAR_SCRIPT'):
            with self.subTest(source=attribute),tempfile.TemporaryDirectory(dir=browser.ROOT/'exports')as directory:
                report,_,_=self.world_fixture(directory)
                source=Path(directory)/'temporary-renderer-source'
                source.write_text('__WALKTHROUGH_DATA__')
                def changed(template_text,payload):
                    source.write_text('changed after source fence')
                    return '{}'
                with patch.object(viewer,attribute,source),patch.object(viewer,'embed_html',side_effect=changed):
                    with self.assertRaisesRegex(ValueError,'Changed or missing checked input'):
                        browser.world_presentation(report)

    def test_pages_entry_and_return_preserve_separate_modes(self):
        normal=viewer.TEMPLATE.read_text(encoding='utf-8')
        self.assertEqual(browser.opt_in_html(normal),normal)
        self.assertNotIn('<script id="building-fleet-data"',normal)
        adapted=browser.opt_in_html(normal,{'format':'unqualified-adapter-fixture'})
        pattern=r'<a\b[^>]*\bid="walkthrough-fleet-link"[^>]*\bhref="([^"]+)"[^>]*>([^<]+)</a>'
        entry=re.findall(pattern,normal);back=re.findall(pattern,adapted)
        self.assertEqual(len(entry),1);self.assertEqual(len(back),1)
        root='https://smoe.github.io/DIYLabBot/'
        self.assertEqual(urljoin(root,entry[0][0]),root+'bf01/')
        self.assertEqual(urljoin(root+'bf01/',back[0][0]),root)
        self.assertIn('BF01',entry[0][1]);self.assertEqual(back[0][1],'Gebäuderundgang')
        self.assertIn('<script id="building-fleet-data"',adapted)
        changed=normal.replace('href="bf01/"','href="unexpected/"')
        with self.assertRaisesRegex(ValueError,'adapter hook changed'):
            browser.opt_in_html(changed,{'format':'unqualified-adapter-fixture'})

    def test_compile_binds_world_for_runtime_and_written_program(self):
        with tempfile.TemporaryDirectory(dir=browser.ROOT/'exports/building-fleet')as directory:
            base=Path(directory);world_report=base/world.REPORT;world_report.write_text('physical world fixture')
            camera=base/'camera.json';camera.write_text('camera fixture')
            # A presentation report deliberately exists with different bytes.
            (base/'build-report.json').write_text('unrelated overlay fixture')
            nav=NS(mesh=NS(export=base,world_report_path=world_report),_cache_pins=lambda:{})
            args=NS(output_dir=base/'run',camera_report=camera,resource_cache=None)
            incomplete={'format':'adapter-fixture-only','complete':False,'source_files_sha256':{},'artifacts':{}}
            calls=[]
            def compiled(*args,**kwargs):
                calls.append(kwargs['artifacts']);return copy.deepcopy(incomplete)
            with ExitStack()as stack:
                for owner,name,value in ((cli.model,'load',{'missions':{'seed':1}}),
                    (cli.model,'source_pins',{}),(cli.model,'protected_pins',{}),
                    (cli,'generator_pins',{'scripts/walkthrough_world.py':native.digest(browser.ROOT/'scripts/walkthrough_world.py')}),(cli,'checked_camera_report',None),
                    (cli,'navigation',nav),(cli,'prepare_program',(None,None)),(cli,'GeometryChecks',None)):
                    stack.enter_context(patch.object(owner,name,return_value=value))
                stack.enter_context(patch.object(cli,'compile_program',side_effect=compiled))
                stack.enter_context(patch.object(cli,'runtime_records',side_effect=RuntimeError('fixture-boundary')))
                with self.assertRaisesRegex(RuntimeError,'fixture-boundary'):
                    cli.compile_fleet(args)
            expected=cli.artifact(world_report)
            self.assertEqual(calls[0]['walkthrough_report'],expected)
            written=json.loads((base/'run/program.json').read_bytes())
            self.assertEqual(written['artifacts']['walkthrough_report'],expected)
            self.assertFalse(written['complete'])
            self.assertNotEqual(expected['sha256'],hashlib.sha256(b'unrelated overlay fixture').hexdigest())


if __name__=='__main__':unittest.main()
