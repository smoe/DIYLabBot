"""Independent negative floor-support geometry fixtures; no service waiver."""
import math
import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_lift_checks as checks
import building_fleet_navigation as navigation


class Scene:
    def __init__(self, faces=()):
        self.manifest = {'elevator': {'reference_level': 'EG', 'reference_z_mm': 0,
                                    'cabin_bounds_mm': {'min': [0, -20, -1],
                                                        'max': [100, 20, 10]}}}
        self.faces = list(faces)
        self.scene = {'groups': [{'id': 'body_' + str(i), 'role': 'any_native_role',
                                  'triangle': face} for i, face in enumerate(faces)]}

    def bounds(self, group):
        triangle = group['triangle']
        return {'min': [min(p[k] for p in triangle) for k in range(3)],
                'max': [max(p[k] for p in triangle) for k in range(3)]}

    def triangles(self, group):
        return iter([group['triangle']])


PORT = {'id': 'port', 'active': True, 'level_id': 'EG', 'z_mm': 0,
        'side': 'inward', 'plane_x_mm': 180}


class SupportBarrierTests(unittest.TestCase):
    def test_empty_full_aperture_strip_rejects(self):
        result = checks._contact_strip(Scene(), PORT, [-10, 10], 20)
        self.assertFalse(result['passed'])
        self.assertTrue(result['rejection_proven'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['missing_strip_mm'], {'x': [110, 120], 'y': [-10, 10]})
        self.assertEqual(result['coverage']['missing_area_mm2'], 200)

    def test_finish_at_three_mm_prevents_empty_barrier_claim(self):
        faces = [[[110, -10, 3], [120, -10, 3], [120, 10, 3]],
                 [[110, -10, 3], [120, 10, 3], [110, 10, 3]]]
        result = checks._contact_strip(Scene(faces), PORT, [-10, 10], 20)
        self.assertFalse(result['passed'])  # A floor witness is not a stage proof.
        self.assertFalse(result['rejection_proven'])
        self.assertEqual(result['status'], 'unproven')
        self.assertTrue(result['coverage']['passed'])

    def test_any_contact_face_role_is_overincluded(self):
        # A slanted nonfloor face must not be silently dropped by role or normal.
        face = [[110, -10, 0], [120, -10, 20], [120, 10, 20]]
        result = checks._contact_strip(Scene([face]), PORT, [-10, 10], 20)
        self.assertFalse(result['rejection_proven'])
        self.assertGreater(result['coverage']['covered_area_mm2'], 0)
        self.assertFalse(result['passed'])

    def test_faces_outside_contact_band_do_not_create_floor(self):
        for z in (-1, 21):
            with self.subTest(z=z):
                face = [[110, -10, z], [120, -10, z], [120, 10, z]]
                result = checks._contact_strip(Scene([face]), PORT, [-10, 10], 20)
                self.assertTrue(result['rejection_proven'])

    def test_wrong_port_state_and_nonfinite_source_fail_closed(self):
        for change in ({'active': False}, {'level_id': 'OG1'}, {'z_mm': 1},
                       {'side': 'unknown'}, {'plane_x_mm': 80}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                checks._contact_strip(Scene(), dict(PORT, **change), [-10, 10], 20)
        for aperture, height in (([0, 0], 20), ([-10, math.inf], 20), ([-10, 10], 0)):
            with self.subTest(aperture=aperture, height=height), self.assertRaises(ValueError):
                checks._contact_strip(Scene(), PORT, aperture, height)

    def test_outward_side_uses_actual_minimum_cabin_edge(self):
        port = dict(PORT, side='outward', plane_x_mm=-80)
        result = checks._contact_strip(Scene(), port, [-10, 10], 20)
        self.assertEqual(result['missing_strip_mm']['x'], [-20, -10])
        self.assertTrue(result['rejection_proven'])

    def test_unchecked_mesh_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source-pinned'):
            checks.support_barrier(Scene(), 'port')


class PinTests(unittest.TestCase):
    def fixture(self, root):
        export = root / 'exports' / 'walkthrough'
        export.mkdir(parents=True)
        (root / 'source.json').write_text('{}')
        pins = {'source.json': checks.model.digest(root / 'source.json')}
        (export / 'native-mesh.json').write_text(json.dumps({
            'format': 'solidcraftbot.building-walkthrough-mesh/1',
            'source_files_sha256': pins, 'scenes': {'building': {}}}))
        checks.walkthrough_world.write(export, {
            'format': 'solidcraftbot.building-walkthrough/1', 'source_files_sha256': pins}, {}, root)
        mesh = object.__new__(navigation.NativeMesh)
        mesh.export = export
        return mesh

    def test_consumed_local_bundle_tamper_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            mesh = self.fixture(root)
            with patch.object(checks, 'ROOT', root):
                checks._verify_export(mesh)
                (mesh.export / 'native-mesh.json').write_text('{"changed":true}')
                with self.assertRaisesRegex(ValueError, 'Changed walkthrough artifact'):
                    checks._verify_export(mesh)

    def test_changed_source_rejects_before_support_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            mesh = self.fixture(root)
            (root / 'source.json').write_text('{"changed":true}')
            with patch.object(checks, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Stale walkthrough source'):
                checks._verify_export(mesh)


class CurrentNativeRegression(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('SOLIDCRAFTBOT_BF01_CURRENT_GEOMETRY_TESTS') == '1',
                         'Opt-in current pinned native export; fixture tests are independent')
    def test_new_sill_removes_old_barrier_without_qualifying_lift(self):
        export = os.environ.get('SOLIDCRAFTBOT_FLEET_WALKTHROUGH_EXPORT',
                                'exports/building-walkthrough/pages-master-80abbc7')
        mesh = navigation.NativeMesh(checks.ROOT / export)
        result = checks.support_barrier(mesh, 'LiftPort_EG_inward')
        self.assertFalse(result['passed'])
        self.assertFalse(result['rejection_proven'])
        self.assertEqual(result['status'], 'unproven')
        self.assertGreater(result['projected_contact_triangle_count'], 0)
        self.assertIn('LiftLandingSill_EG_inward',
                      [body['body'] for body in result['native_candidate_groups']])
        self.assertEqual(result['source_opening_id'], 'DLift')


class LiftGateTests(unittest.TestCase):
    def fixture(self):
        from types import SimpleNamespace
        cabin = {'id':'Cabin','joint':{'type':'prismatic','axis':[0,0,1]},
                 'states':{'EG':0.,'OG1':4250.},'reference_state':'EG',
                 'moving_body_ids':['CabinFloor'],'parent_object_id':None}
        door = {'id':'Door','joint':{'type':'prismatic','axis':[0,1,0]},
                'states':{'closed':0.,'open':100.},'reference_state':'closed',
                'moving_body_ids':['DoorBody'],'parent_object_id':'Cabin',
                'mechanism':'lift_door'}
        mesh = SimpleNamespace(manifest={'elevator':{'object_id':'Cabin','ports':[
            {'id':'P','active':True,'level_id':'OG1','z_mm':4250.,'side':'outward',
             'door_object_ids':['Door']}]},'objects':[cabin,door]})
        timeline = SimpleNamespace(values=lambda t:{'Cabin':4250.,'Door':100.})
        return mesh,timeline

    def test_compiled_numeric_gate_requires_correct_floor_and_fully_open_doors(self):
        from types import SimpleNamespace
        mesh,timeline = self.fixture()
        self.assertEqual(checks.gate_at(mesh,'P',timeline,1)['cabin_z_mm'],4250.)
        for values in ({'Cabin':0.,'Door':100.},{'Cabin':4250.,'Door':99.},
                       {'Cabin':4250.}):
            with self.subTest(values=values),self.assertRaises(ValueError):
                checks.gate_at(mesh,'P',SimpleNamespace(values=lambda t,v=values:v),1)
        mesh.manifest['elevator']['ports'][0]['active']=False
        with self.assertRaises(ValueError):checks.gate_at(mesh,'P',timeline,1)

    def test_measurement_pose_opens_both_ground_floor_ports_only(self):
        mesh, _ = self.fixture()
        ports = mesh.manifest['elevator']['ports']
        objects = mesh.manifest['objects']
        for side in ('inward', 'outward'):
            identity = 'EG_' + side
            ports.append({'id': identity, 'active': True, 'level_id': 'EG',
                          'z_mm': 0., 'side': side, 'door_object_ids': [identity]})
            objects.append({**objects[1], 'id': identity})
        both = {'Cabin': 0., 'Door': 0., 'EG_inward': 100., 'EG_outward': 100.}
        for side in ('inward', 'outward'):
            self.assertEqual(checks.fully_open_values(mesh, 'EG_' + side), both)

    def test_absolute_pose_applies_child_then_cabin_once_without_editing_source(self):
        mesh,_ = self.fixture()
        mesh._posed_bounds_cache={'old_pose':'bounds'};mesh._fleet_band_cache={'old_pose':'band'}
        posed = checks.posed_mesh(mesh,{'Cabin':4250.,'Door':100.})
        self.assertEqual(posed._posed_bounds_cache,{})
        self.assertEqual(posed._fleet_band_cache,{})
        self.assertEqual(mesh._posed_bounds_cache,{'old_pose':'bounds'})
        self.assertEqual(mesh._fleet_band_cache,{'old_pose':'band'})
        point = [12.,34.,0.]
        for obj in posed.transforms['DoorBody']:
            point = navigation.initial_transform(obj,point)
        self.assertEqual(point,[12.,134.,4250.])
        self.assertNotIn('bf01_compiled_pose',mesh.manifest['objects'][0]['states'])
        self.assertEqual(mesh.manifest['objects'][1]['states']['open'],100.)
        with self.assertRaises(ValueError):checks.posed_mesh(mesh,{'Cabin':9000.})
        with self.assertRaises(ValueError):checks.posed_mesh(mesh,{'not-a-source-object':0})


class RaisedSurfaceTests(unittest.TestCase):
    class Mesh:
        def __init__(self, wrong_top=False, wrong_role=False):
            self.manifest = {'elevator': {'object_id':'Cabin', 'ports':[
                {'id':'P','active':True,'level_id':'EG','z_mm':0.,'side':'inward','door_object_ids':['Door']}]},
                'objects':[{'id':'Cabin','joint':{'type':'prismatic','axis':[0,0,1]},
                            'states':{'EG':0.,'OG1':4250.},'reference_state':'EG',
                            'moving_body_ids':['LiftCabinFloorFinish','LiftCabinSill_inward']},
                           {'id':'Door','joint':{'type':'prismatic','axis':[0,1,0]},
                            'states':{'closed':0.,'open':100.},'reference_state':'closed','moving_body_ids':[]}]}
            roles = [('Slab','concept_storey_slab',0.),
                     ('UnrelatedRaisedSlab','concept_storey_slab',3.),
                     ('LiftCabinFloorFinish','concept_lift_floor_finish',3.),
                     ('LiftCabinSill_inward','concept_lift_cabin_sill',4. if wrong_top else 3.),
                     ('LiftLandingSill_EG_inward','wrong_role' if wrong_role else'concept_lift_landing_sill',3.)]
            self.scene={'maximum_float32_error_mm':0.,'groups':[
                {'id':name,'role':role,'triangle':[[0.,0.,z],[100.,0.,z],[0.,100.,z]]}for name,role,z in roles]}
            self.transforms={}
        def bounds(self,group):
            tri=list(self.triangles(group))[0]
            return {'min':[min(p[k]for p in tri)for k in range(3)],'max':[max(p[k]for p in tri)for k in range(3)]}
        def triangles(self,group):
            tri=[]
            for raw in group['triangle']:
                point=list(raw)
                for obj in self.transforms.get(group['id'],[]):point=navigation.initial_transform(obj,point)
                tri.append(point)
            return iter([tri])

    def contract(self):
        return {'height_offset_mm':3.,'ports':{'P':{'z_mm':0.,'height_offset_mm':3.,
            'source_surface_ids':['LiftCabinFloorFinish','LiftCabinSill_inward','LiftLandingSill_EG_inward']}}}

    def test_only_exact_source_raise_families_count_as_floor(self):
        from types import SimpleNamespace
        timeline=SimpleNamespace(values=lambda t:{'Cabin':0.,'Door':100.})
        with patch.object(checks,'source_surface_contract',return_value=self.contract()):
            result=checks.surface_rows_at(self.Mesh(),'P',timeline,1.)
        bodies={row['body_id']for row in result['surface_rows']}
        self.assertIn('Slab',bodies);self.assertIn('LiftCabinFloorFinish',bodies)
        self.assertNotIn('UnrelatedRaisedSlab',bodies)
        self.assertEqual(sum(row['height_exception_applied']for row in result['surface_rows']),3)

    def test_changed_raised_top_or_wrong_role_fails(self):
        from types import SimpleNamespace
        timeline=SimpleNamespace(values=lambda t:{'Cabin':0.,'Door':100.})
        for mesh in(self.Mesh(wrong_top=True),self.Mesh(wrong_role=True)):
            with self.subTest(mesh=mesh),patch.object(checks,'source_surface_contract',return_value=self.contract()),self.assertRaises(ValueError):
                checks.surface_rows_at(mesh,'P',timeline,1.)


if __name__ == '__main__':
    unittest.main()
