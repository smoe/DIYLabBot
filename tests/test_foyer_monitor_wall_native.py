"""Fail-closed native audit helpers, using explicitly synthetic measurements."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import check_foyer_monitor_wall_native as audit
import build_foyer_monitor_wall_native as builder


class NativeScopeTests(unittest.TestCase):
    def fixture(self):
        wall = {'level_id':'EG','area':'R0_019','wall':'W052',
                'wall_body_id':'EG__Wall_W052','body_ids':[],'monitors':[]}
        geometry = []; operations = []
        for index in range(9):
            identity = 'Monitor'+str(index)
            bodies = [identity+'_'+part for part in ('Case','Screen','Mount')]
            wall['monitors'].append({'id':identity,'body_ids':bodies,
                'case_body_id':bodies[0],'screen_body_id':bodies[1],
                'screen_frame':{'origin_mm':[index*20+5,2,5], 'x_axis':[1,0,0],
                    'y_axis':[0,0,1],'normal':[0,-1,0],'width_mm':10,'height_mm':10}})
            wall['body_ids'].extend(bodies)
            for offset,name in enumerate(bodies):
                lo = [index*20,offset*2,0]; hi = [index*20+10,offset*2+1,10]
                geometry.append({'body':name,'bbox':{'min':lo,'max':hi}})
                operations.append({'body':name,'action':'create','shape':{
                    'kind':'box','origin':lo,'size':[10,1,10]}})
        return wall,geometry,operations

    def test_nine_complete_instances_use_all_native_body_ids(self):
        wall,geometry,operations = self.fixture()
        names = [row['body'] for row in geometry]+[wall['wall_body_id']]
        self.assertEqual(len(audit.validate_scope(wall,names)),9)
        geometry.append({'body':wall['wall_body_id'],'bbox':{'min':[-1,-1,-1],'max':[1,1,1]}})
        self.assertTrue(all(row['passed'] for row in audit.geometry_checks(wall,geometry,operations)))

    def test_duplicate_missing_or_wrong_facing_instances_fail(self):
        wall,geometry,_ = self.fixture(); names = [row['body']for row in geometry]+[wall['wall_body_id']]
        for change in (
            lambda w:w['monitors'].pop(),
            lambda w:w['monitors'][1].update(id=w['monitors'][0]['id']),
            lambda w:w['monitors'][0]['screen_frame'].update(normal=[0,1,0]),
            lambda w:w['monitors'][0]['screen_frame'].update(width_mm=float('nan')),
            lambda w:w.update(area='Other'),
        ):
            broken = copy.deepcopy(wall);change(broken)
            with self.subTest(change=change),self.assertRaises(ValueError):
                audit.validate_scope(broken,names)
        with self.assertRaises(ValueError):audit.validate_scope(wall,names[:-1])

    def test_measurement_drift_fails_without_loading_cad(self):
        wall,geometry,operations = self.fixture()
        geometry.append({'body':wall['wall_body_id'],'bbox':{'min':[-1,-1,-1],'max':[1,1,1]}})
        geometry[0]['bbox']['max'][0] += .1
        checks = audit.geometry_checks(wall,geometry,operations)
        self.assertFalse(checks[0]['passed'])
        self.assertGreater(checks[0]['maximum_bbox_error_mm'],.09)

    def test_screen_frame_and_mounting_gaps_fail_without_loading_cad(self):
        wall,geometry,operations = self.fixture()
        geometry.append({'body':wall['wall_body_id'],'bbox':{'min':[-1,-1,-1],'max':[1,1,1]}})
        wall['monitors'][0]['screen_frame']['origin_mm'][1] += .1
        checks = audit.geometry_checks(wall,geometry,operations)
        self.assertTrue(any(not row['passed']for row in checks if row.get('category') == 'actual_native_screen_front'))
        nearest = {m['body_ids'][2]:{'body':wall['wall_body_id'],'distance_mm':0}for m in wall['monitors']}
        self.assertTrue(all(row['passed']for row in audit.mounting_checks(wall,nearest)))
        nearest[wall['monitors'][0]['body_ids'][2]]['distance_mm'] = 1
        self.assertFalse(audit.mounting_checks(wall,nearest)[0]['passed'])


class NativeClearanceReplyTests(unittest.TestCase):
    def reply(self):
        return {'overlaps':[],'near':[],'unchecked':[],'pairs_checked':1,'truncated':False,'bodies':1,
                'nearest':{'Screen':[{'body':'Wall','distance_mm':30.}]}}

    def test_complete_exact_reply_is_accepted(self):
        reply = self.reply()
        self.assertIs(audit.check_clearance_result(reply,['Screen']),reply)
        # The kernel can prune every overlapping-pair candidate and still
        # return an exact positive nearest distance for each selected body.
        reply['pairs_checked'] = 0
        self.assertIs(audit.check_clearance_result(reply,['Screen']),reply)

    def test_unchecked_missing_and_mesh_only_replies_are_rejected(self):
        for change in (
            lambda r:r.update(unchecked=[{'a':'Screen','b':'Wall','reason':'budget exceeded'}]),
            lambda r:r.update(pairs_checked=-1),
            lambda r:r.update(truncated=True),
            lambda r:r.update(bodies=0),
            lambda r:r.update(nearest={}),
            lambda r:r['nearest']['Screen'][0].update(distance_mm=-1),
            lambda r:r.update(near=[{'a':'Screen','b':'Wall','exact':False}]),
            lambda r:r.update(overlaps=[{'a':'Screen','b':'Wall','volume_mm3':1}]),
            lambda r:r.update(overlaps=[{'a':'Screen','b':'Wall','volume_mm3':float('nan')}]),
        ):
            reply = self.reply();change(reply)
            with self.subTest(change=change),self.assertRaises(ValueError):
                audit.check_clearance_result(reply,['Screen'])

    def test_aabb_bound_is_only_a_nonnegative_lower_bound(self):
        self.assertEqual(audit.box_distance({'min':[0,0,0],'max':[1,1,1]},
                                            {'min':[3,1,1],'max':[4,2,2]}),2)


class SourceNeighbourhoodTests(unittest.TestCase):
    def source(self):
        rows = [('Screen',[0,0,0]),('Host',[0,5,0]),('Near',[20,0,0]),('Far',[5000,0,0])]
        source = {'bodies':[{'id':name}for name,_ in rows],
                  'operations':[{'id':name,'body':name,'action':'create','shape':{
                      'kind':'box','origin':point,'size':[10,1,10]}}for name,point in rows]}
        return source,{'body_ids':['Screen'],'wall_body_id':'Host'}

    def test_source_selection_contains_neighbours_and_certifies_pruned_distance(self):
        source,wall = self.source()
        chosen,selection = builder.select_scope(source,wall,radius=100)
        self.assertEqual({row['id']for row in chosen['bodies']},{'Screen','Host','Near'})
        self.assertEqual(selection['excluded_body_lower_bounds_mm'],{'Far':4990.})
        self.assertFalse(any(row['body']=='Far'for row in chosen['operations']))

    def test_cuts_cannot_make_source_bounds_larger_but_positive_additions_can(self):
        source,wall = self.source()
        far_tool = {'id':'FarCut','body':'Near','action':'cut',
                    'shape':{'kind':'box','origin':[-9999,0,0],'size':[10000,1,10]}}
        source['operations'].append(far_tool)
        self.assertEqual(builder.source_bounds(source)['Near']['min'][0],20)
        source['operations'][-1]['action'] = 'fuse'
        self.assertEqual(builder.source_bounds(source)['Near']['min'][0],-9999)

    def test_invalid_radius_and_missing_creation_fail_closed(self):
        source,wall = self.source()
        for radius in (0,-1,True,float('nan'),float('inf')):
            with self.subTest(radius=radius),self.assertRaises(ValueError):
                builder.select_scope(source,wall,radius)
        source['operations'].pop()
        with self.assertRaises(ValueError):builder.select_scope(source,wall)


class RoomSignNeighbourhoodTests(unittest.TestCase):
    def bundle(self, origin=(100,200,300)):
        return {'kind':'cylinder_bundle','combine':'union','coordinate_frame':'glyph_local_mm',
            'cylinders':[
                {'origin':[0,0,0],'axis':[1,0,0],'radius':.5,'height':4},
                {'origin':[0,0,0],'axis':[0,1,0],'radius':.5,'height':3}],
            'glyph_spans':[{'start':0,'count':1,'offset_mm':[10,20,0]},
                           {'start':1,'count':1,'offset_mm':[15,20,0]}],
            'frame':{'origin':list(origin),'x':[0,1,0],'y':[0,0,1],'z':[1,0,0]}}

    def ink(self, source, name, shape):
        source['bodies'].append({'id':name,'component':'RoomSigns','role':'room_sign_ink',
            'geometry_semantics':'disconnected_surface_annotation',
            'appearance':{'color':'#192e3a','opacity':1}})
        source['operations'].append({'id':name,'body':name,'action':'create','shape':shape})

    def test_bundle_bounds_include_glyph_offsets_and_the_full_world_frame(self):
        source={'bodies':[],'operations':[]}
        self.ink(source,'Ink',self.bundle());before=copy.deepcopy(source)
        # The first stroke points along world Y, the second along world Z.
        self.assertEqual(builder.source_bounds(source)['Ink'],
                         {'min':[99.5,210,319.5],'max':[100.5,215.5,323]})
        self.assertEqual(source,before)

    def test_nearby_ink_is_retained_and_remote_ink_has_a_real_pruning_bound(self):
        source,wall=SourceNeighbourhoodTests().source()
        self.ink(source,'NearInk',self.bundle((0,20,0)))
        self.ink(source,'FarInk',self.bundle((5000,20,0)))
        selected,scope=builder.select_scope(source,wall,radius=100)
        self.assertIn('NearInk',{row['id']for row in selected['bodies']})
        self.assertNotIn('FarInk',{row['id']for row in selected['bodies']})
        self.assertGreater(scope['excluded_body_lower_bounds_mm']['FarInk'],4800)
        self.assertEqual(set(scope['source_body_bounds_mm']),{row['id']for row in source['bodies']})

    def test_invalid_bundle_cannot_be_silently_removed_from_the_neighbourhood(self):
        for mutate in (lambda s:s['glyph_spans'][1].update(start=0),
                       lambda s:s['frame'].update(z=[-1,0,0]),
                       lambda s:s['cylinders'][0].update(radius=float('nan'))):
            source={'bodies':[],'operations':[]};shape=self.bundle();mutate(shape)
            self.ink(source,'Ink',shape)
            with self.subTest(shape=shape),self.assertRaises(ValueError):builder.source_bounds(source)

    def test_scope_commands_lower_disjoint_glyphs_without_a_native_bundle_primitive(self):
        source={'id':'Fixture','status':'synthetic','components':[{'id':'RoomSigns','grounded':True}],
                'bodies':[{'id':'Screen','component':'RoomSigns','appearance':{'color':'#ffffff','opacity':1}}],
                'operations':[{'id':'Screen','body':'Screen','action':'create',
                               'shape':{'kind':'box','origin':[0,0,0],'size':[10,1,10]}}],
                'joints':[]}
        self.ink(source,'Ink',self.bundle());before=copy.deepcopy(source)
        commands=builder.solidcraft_scope_commands(source,{'id':'Fixture','status':'synthetic','parameters':{}},{})
        self.assertEqual(source,before)
        self.assertFalse(any(row['command']=='solid.cylinder_bundle'for row in commands))
        self.assertEqual(len([row for row in commands if row['command']=='solid.box']),1)
        self.assertEqual(len([row for row in commands if row['command']=='solid.cylinder']),2)
        joined=[row['params']for row in commands if row['command']=='solid.combine']
        self.assertEqual(len(joined),1)
        self.assertEqual((joined[0]['target'],joined[0]['tools']),('Ink',['Ink_Glyph1']))
        self.assertEqual([row['params']['bodies']for row in commands
                          if row['command']=='component.move_bodies'],[['Screen'],['Ink']])
        # The existing audit importer accepts a closed disconnected annotation
        # as one semantic SolidCraft body, while retaining its closure gate.
        raw={'bodies':[{'name':'Ink','closed':True,'volume_mm3':1,
                       'center_of_mass':[100,213,321],
                       'bbox':builder.source_bounds(source)['Ink']}]}
        self.assertEqual(audit.common.measurements(raw,{'bodies':[source['bodies'][-1]]},backend='solidcraft')[0]['body'],'Ink')
        raw['bodies'][0]['closed']=False
        with self.assertRaises(ValueError):audit.common.measurements(raw,{'bodies':[source['bodies'][-1]]},backend='solidcraft')


class NativeBuildInputEvidenceTests(unittest.TestCase):
    """Synthetic fixture bytes test provenance checks, not a native CAD pass."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root/'model/source.json';source.parent.mkdir(parents=True)
        source.write_text('{"fixture":"synthetic source"}\n')
        sources = {'model/source.json':self.digest(source)}
        self.records = {}
        for kind,roles in [('freecad',('case','freecad','freecad_validation')),
                           ('solidcraft',('commands','solidcraft','solidcraft_measurements'))]:
            files = {};hashes = {}
            for role in roles:
                name = 'exports/'+kind+'/'+role+'.fixture'
                path = self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(('synthetic fixture '+role).encode())
                files[role] = name;hashes[role] = self.digest(path)
            report = {'files':files,'artifact_sha256':hashes,'source_files_sha256':sources}
            path = self.root/'exports'/kind/'build-report.json';path.write_text(json.dumps(report))
            self.records[kind] = audit.build_input_evidence(path,report,self.root)

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_both_reports_and_all_original_artifacts_remain_bound(self):
        pins = audit.verify_build_input_evidence(self.records,self.root)
        self.assertEqual(len(pins),8)
        for record in self.records.values():
            self.assertEqual(pins[record['report']['path']],record['report']['sha256'])
            for ref in record['artifacts'].values():
                self.assertEqual(pins[ref['path']],ref['sha256'])

    def assert_drift_rejected(self,ref):
        path = self.root/ref['path'];before = path.read_bytes()
        path.write_bytes(before+b' changed during audit')
        try:
            with self.assertRaises(ValueError):audit.verify_build_input_evidence(self.records,self.root)
        finally:
            path.write_bytes(before)

    def test_solidcraft_measurement_drift_is_rejected(self):
        self.assert_drift_rejected(self.records['solidcraft']['artifacts']['solidcraft_measurements'])

    def test_solidcraft_native_drift_is_rejected(self):
        self.assert_drift_rejected(self.records['solidcraft']['artifacts']['solidcraft'])

    def test_solidcraft_build_report_drift_is_rejected(self):
        self.assert_drift_rejected(self.records['solidcraft']['report'])

    def test_freecad_validation_and_shared_source_drift_are_rejected(self):
        self.assert_drift_rejected(self.records['freecad']['artifacts']['freecad_validation'])
        self.assert_drift_rejected({'path':'model/source.json'})

    def test_report_snapshot_rejects_incomplete_artifact_pins(self):
        ref = self.records['solidcraft']['report'];path = self.root/ref['path']
        report = json.loads(path.read_text());report['artifact_sha256'].pop('solidcraft_measurements')
        path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):audit.build_input_evidence(path,report,self.root)


class NativeAuditSourcePinTests(unittest.TestCase):
    def test_export_helper_drift_is_rejected_by_audit_source_pins(self):
        helper_name = 'scripts/export_building_walkthrough_freecad.py'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            auditor = root/'scripts/check_foyer_monitor_wall_native.py'
            helper = root/helper_name
            auditor.parent.mkdir()
            auditor.write_bytes(Path(audit.__file__).read_bytes())
            helper_bytes = Path(audit.native.__file__).read_bytes()
            helper.write_bytes(helper_bytes)

            with patch.object(audit, '__file__', str(auditor)), patch.object(audit.native, '__file__', str(helper)):
                pins = audit.audit_source_pins(root)
                self.assertEqual(pins[helper_name], hashlib.sha256(helper_bytes).hexdigest())
                audit.native.verify_pins(pins, root)
                helper.write_bytes(helper_bytes + b'\n# Drift after the audit snapshot.\n')
                with self.assertRaisesRegex(ValueError, helper_name):
                    audit.native.verify_pins(pins, root)


if __name__ == '__main__':
    unittest.main()
