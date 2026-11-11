"""Byte-bound native evidence and equivalent-geometry reuse, without CAD."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_lab_transfer as build


class NativeBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.patch=patch.object(build,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.out=self.root/'out';self.cad=self.root/'cad';self.out.mkdir();self.cad.mkdir()
        for path in [self.root/'layout.json',self.out/'timeline.json',self.out/'samples.json',
                     self.cad/'scene.FCStd',self.cad/'fixed.step',self.cad/'moving.step',self.cad/'sample.step']:
            path.write_text('original '+path.name)
        self.contract={'geometry_source':'version-one','geometry_sources_sha256':self.pins([self.root/'layout.json'])}
        self.ctx={'out':str(self.out),'scene_file':str(self.cad/'scene.FCStd'),'sample_step':str(self.cad/'sample.step'),
                  'snapshots':[{'step':str(self.cad/'fixed.step')}],'dynamic':[{'step':str(self.cad/'moving.step')}],
                  'passed':True,'geometry_contract':self.contract}
        self.ctx['geometry_inputs_sha256']=self.pins([self.root/'layout.json'])
        self.ctx['geometry_artifacts_sha256']=self.pins(build.geometry_artifacts(self.ctx))
        self.ctx['native_input_sha256']=self.pins([self.out/'timeline.json',self.out/'samples.json'])
        self.report={'passed':True,'native_input_sha256':copy.deepcopy(self.ctx['native_input_sha256'])}
        self.native=self.out/'motion-validation.json';self.native.write_text(json.dumps(self.report))
        self.ctx['native_report_sha256']=build.robot.digest(self.native)
        self.path=self.out/'context.json';self.save()

    def pins(self,paths):return {str(p.relative_to(self.root)):build.robot.digest(p) for p in paths}
    def save(self):self.path.write_text(json.dumps(self.ctx))

    def test_same_qualified_cache_binds_actual_context_scene_and_all_steps(self):
        old,pins=build.checked_reuse(self.path,self.contract)
        self.assertEqual(old,self.ctx)
        for path in [self.path,self.native,*build.geometry_artifacts(self.ctx)]:
            self.assertEqual(pins[str(path.relative_to(self.root))],build.robot.digest(path))

    def test_changed_scene_or_step_cannot_reuse_copied_source_claims(self):
        for path in build.geometry_artifacts(self.ctx):
            original=path.read_bytes();path.write_bytes(b'changed native geometry')
            with self.subTest(path=path.name),self.assertRaises(ValueError):build.checked_reuse(self.path,self.contract)
            path.write_bytes(original)

    def test_missing_actual_cache_pin_and_changed_generator_contract_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'equivalent geometry sources'):
            build.checked_reuse(self.path,{'geometry_source':'new-generator'})
        del self.ctx['geometry_artifacts_sha256']['cad/moving.step'];self.save()
        with self.assertRaisesRegex(ValueError,'omits a scene or STEP'):build.checked_reuse(self.path,self.contract)

    def test_native_timeline_or_samples_mutation_invalidates_the_report(self):
        for name in ('timeline.json','samples.json'):
            path=self.out/name;original=path.read_bytes();path.write_text('new program with copied audits')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Native input changed'):
                build.verify_native_inputs(self.ctx,self.report)
            path.write_bytes(original)

    def test_unbound_historical_native_report_is_not_silently_adopted(self):
        for report in ({'passed':True},{'passed':True,'native_input_sha256':{'out/timeline.json':'0'*64}}):
            with self.assertRaisesRegex(ValueError,'not bound'):build.verify_native_inputs(self.ctx,report)

    def test_native_report_mutation_is_rejected_before_finish(self):
        changed=copy.deepcopy(self.report);changed['collisions']=[];self.native.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'Native report bytes changed'):
            build.verify_native_inputs(self.ctx,changed)

    def test_failed_native_audit_cannot_be_finalized_or_publish_current_outputs(self):
        self.ctx['cad']=str(self.cad)
        for failed in ('context','report'):
            ctx=copy.deepcopy(self.ctx);report=copy.deepcopy(self.report)
            (ctx if failed=='context' else report)['passed']=False
            self.native.write_text(json.dumps(report))
            with self.subTest(failed=failed),self.assertRaisesRegex(ValueError,'Only a passed native audit'):
                build.finish(ctx,None)

    def test_changed_geometry_input_or_native_report_is_rejected(self):
        original=(self.root/'layout.json').read_bytes();(self.root/'layout.json').write_text('changed layout')
        with self.assertRaises(ValueError):build.checked_reuse(self.path,self.contract)
        (self.root/'layout.json').write_bytes(original);self.native.write_text('{"passed":true}')
        with self.assertRaisesRegex(ValueError,'native report is missing or changed'):build.checked_reuse(self.path,self.contract)

    def test_start_end_contract_check_rejects_omitted_or_changed_construction_source(self):
        with patch.object(build,'geometry_contract',return_value=self.contract):
            build.verify_geometry_contract(self.ctx,{'selected':True},{'selected':True})
            missing=copy.deepcopy(self.ctx);missing['geometry_contract']['geometry_sources_sha256']={}
            with self.assertRaisesRegex(ValueError,'Complete geometry source pins'):
                build.verify_geometry_contract(missing,{'selected':True},{'selected':True})
            altered=copy.deepcopy(self.ctx);altered['geometry_contract']['geometry_source']='different-builder'
            with self.assertRaisesRegex(ValueError,'Geometry source contract changed'):
                build.verify_geometry_contract(altered,{'selected':True},{'selected':True})
            (self.root/'layout.json').write_text('changed construction helper')
            with self.assertRaisesRegex(ValueError,'Geometry source changed'):
                build.verify_geometry_contract(self.ctx,{'selected':True},{'selected':True})

    def test_reuse_cannot_drop_geometry_source_pins(self):
        del self.ctx['geometry_contract']['geometry_sources_sha256'];self.save()
        with self.assertRaisesRegex(ValueError,'complete geometry source pins'):
            build.checked_reuse(self.path,self.ctx['geometry_contract'])


class FurnitureDistanceTests(unittest.TestCase):
    a={'min':[0.,0.,0.],'max':[1.,1.,1.]}

    def test_at_or_above_five_mm_needs_no_exact_refinement(self):
        for gap in (5.,math.nextafter(5.,math.inf),20.):
            b={'min':[1.+gap,0.,0.],'max':[2.+gap,1.,1.]}
            def unexpected():self.fail('A proved 5 mm AABB separation must not call the native distance solver')
            lower,refined=build.furniture_distance_lower_bound(self.a,b,5.,unexpected)
            self.assertGreaterEqual(lower,5.);self.assertFalse(refined)

    def test_just_below_five_mm_is_refined_and_remains_a_failure(self):
        gap=4.999999;b={'min':[1.+gap,0.,0.],'max':[2.+gap,1.,1.]};calls=[]
        lower,refined=build.furniture_distance_lower_bound(self.a,b,5.,lambda:calls.append(True) or gap)
        self.assertTrue(refined);self.assertEqual(calls,[True]);self.assertLess(lower,5.)

    def test_overlapping_boxes_can_only_pass_with_the_actual_exact_gap(self):
        calls=[];lower,refined=build.furniture_distance_lower_bound(self.a,self.a,5.,lambda:calls.append(True) or 7.)
        self.assertTrue(refined);self.assertEqual(calls,[True]);self.assertEqual(lower,7.)

    def test_diagonal_three_four_gap_proves_exactly_five_mm(self):
        b={'min':[4.,5.,0.],'max':[5.,6.,1.]}
        lower,refined=build.furniture_distance_lower_bound(self.a,b,5.,lambda:self.fail('Unnecessary exact refinement'))
        self.assertEqual(lower,5.);self.assertFalse(refined)

    def test_invalid_exact_native_result_is_rejected(self):
        for value in (math.nan,-1.):
            with self.subTest(value=value),self.assertRaises(ValueError):
                build.furniture_distance_lower_bound(self.a,self.a,5.,lambda:value)


class PreviewClockTests(unittest.TestCase):
    def test_long_previews_preserve_canonical_seconds_inside_the_native_step_budget(self):
        for duration in (1.25,99.9999,100.,1248.6944343822122):
            clock=build.preview_clock(duration)
            self.assertGreaterEqual(clock['steps'],1);self.assertLessEqual(clock['steps'],100000)
            for fraction in (0.,.1234,.5,1.):
                time_s=duration*fraction;step=time_s/clock['seconds_per_step']
                self.assertLessEqual(step,clock['steps']+1e-9)
                self.assertAlmostEqual(step*clock['seconds_per_step'],time_s,places=10)
        self.assertEqual(build.preview_clock(1248.6944343822122)['steps'],100000)

    def test_invalid_preview_durations_are_rejected(self):
        for value in (0.,-1.,math.nan,math.inf):
            with self.subTest(value=value),self.assertRaises(ValueError):build.preview_clock(value)


if __name__=='__main__':unittest.main()
