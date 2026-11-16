"""Room bindings, presentation transforms and the shared native furniture contract."""
import copy
import json
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_stack as stack
import building_furnishings as furniture
import relative_floorplan as floor
import wall_worktops
import building_walkthrough as walkthrough


MEDIA_COMPATIBLE_PRODUCERS = {
    'model/building-walkthrough.schema.json',
    'model/building-walkthrough.shared.json',
    'scripts/building_walkthrough.py',
    'scripts/building_walkthrough_viewer.html',
    'tests/check_building_walkthrough.cjs',
    'tests/test_building_furnishings.py',
}
MEDIA_COMPATIBLE_SITE_PRODUCERS = {'scripts/building_exterior.py'}
MEDIA_CAMERA_FIELDS = ('default_stop', 'stops', 'levels', 'settings', 'rendering', 'hidden_body_ids')


def media_camera_digest(program):
    projection = {key: program[key] for key in MEDIA_CAMERA_FIELDS}
    return hashlib.sha256(json.dumps(projection, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


class FurnishingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = stack.load(); cls.p = stack.parameters(cls.spec)
        cls.data = stack.interfaces(cls.spec, cls.p)
        cls.level_plans = {level['id']: stack.level_plan(cls.spec,level['id']) for level in cls.data['levels'] if level['id'].startswith('OG')}
        cls.result = furniture.compile(cls.spec['sources']['furnishings'], stack.templates(cls.spec)[0], cls.p, cls.data['levels'], cls.level_plans)

    def test_owner_room_assignments(self):
        self.assertEqual({r['room'] for r in self.result['rooms']}, {'1.008','1.002','2.002','3.002','3.009'})
        self.assertEqual({r['level'] for r in self.result['rooms'] if r['room']=='1.008'}, {'OG1'})
        self.assertEqual(set(self.result['omitted_walls']), {'OG1__Wall_W027', 'OG1__Wall_W017'})

    def test_only_kitchen_partitions_removed(self):
        expanded = stack.expanded(self.spec, self.p)
        ids = {b['id'] for b in expanded['bodies']}
        for wall in ('W017','W027'):
            self.assertNotIn('OG1__Wall_'+wall,ids)
            self.assertTrue({'OG2__Wall_'+wall,'OG3__Wall_'+wall} <= ids)
        self.assertEqual(len(ids),len(expanded['bodies']))
        self.assertTrue({o['body'] for o in expanded['operations']} <= ids)

    def test_easter_egg_has_separate_occluding_door(self):
        kitchen = next(r for r in self.result['rooms'] if r['room']=='1.008')
        self.assertTrue(kitchen['easter_egg_body_ids'])
        self.assertEqual(len(kitchen['fridge_door_body_ids']),2)
        self.assertFalse(set(kitchen['fridge_door_body_ids']) & set(kitchen['easter_egg_body_ids']))
        self.assertTrue(any(o['body']=='Kitchen1008_Fridge_Shell' and o['action']=='cut' for o in self.result['operations']))

    def test_desk_and_chair_counts(self):
        ids = self.result['body_ids']
        for room in ['PhD1002','PhD2002','PhD3002']:
            self.assertEqual(sum(id.startswith(room+'_Desk') and id.endswith('_Top') for id in ids),4)
            self.assertEqual(sum(id.startswith(room+'_Chair') and id.endswith('_Seat') for id in ids),4)
        self.assertIn('Office3009_Desk_Top', ids)

    def test_phd3002_desks_follow_both_long_sides_and_the_window_end(self):
        source=furniture.read(self.spec['sources']['furnishings'])
        room=next(room for room in source['rooms'] if room['room']=='3.002')
        desks=[item for item in room['instances'] if item['type']=='desk']
        sides=[item for item in desks if not item['wall_span']['corner_owner']]
        window=[item for item in desks if item['wall_span']['corner_owner']]
        self.assertEqual(len(sides),3)
        self.assertEqual(len(window),1)
        self.assertEqual({item['wall_span']['wall_id'] for item in sides},{'W070','W086'})
        self.assertEqual(window[0]['wall_span']['wall_id'],'W072')
        self.assertTrue(all(item['wall_span']['back_gap_mm']==0 for item in desks))
        self.assertIn('presentation assumptions',room['layout_basis'])
        self.assertTrue(all(item['type']!='first_aid_cabinet' for other in source['rooms']
                            if other['room']!='3.002' for item in other['instances']))

    def test_first_aid_is_inside_to_the_right_of_the_actual_corridor_door(self):
        room=next(room for room in self.result['rooms'] if room['room']=='3.002')
        anchor=room['opening_anchors'][0]
        self.assertEqual((anchor['opening_id'],anchor['area_id'],anchor['side']),
                         ('D3_002N','R3_002','interior_right'))
        self.assertFalse(anchor['dimensions_measured'])
        cabinet=next(op['shape'] for op in self.result['operations']
                     if op['body']=='PhD3002_FirstAid_Cabinet')
        center=[sum(point[i] for point in cabinet['points'])/4 for i in (0,1)]
        delta=[center[i]-anchor['jamb_mm'][i] for i in (0,1)]
        self.assertGreater(sum(delta[i]*anchor['right_direction'][i] for i in (0,1)),0)
        self.assertGreater(sum(delta[i]*anchor['interior_direction'][i] for i in (0,1)),0)
        plan=stack.templates(self.spec)[0]
        polygon=floor.outline(plan,next(area for area in plan['areas'] if area['id']=='R3_002'))
        for point in cabinet['points']:
            self.assertEqual(floor.point_membership([v/self.p['display_scale'] for v in point],polygon),1)

    def test_phd3002_flat_furniture_clears_source_open_door_leaves(self):
        leaves={self.data['exterior']['door_leaves'][key]
                for key,value in self.data['exterior']['door_bindings'].items()
                if value['level_id']=='OG3' and 'R3_002' in value['area_ids']}
        self.assertEqual(len(leaves),2)
        doors=[op for op in stack.expanded(self.spec,self.p)['operations']
               if op['action']=='create' and op['body'] in leaves]
        flat=[op for op in self.result['operations'] if op['action']=='create'
              and op['body'].startswith('PhD3002_') and op['shape']['kind']=='polygon_prism']
        def bounds(op):
            shape=op['shape']
            self.assertEqual(shape['plane'],'XY')
            return ([min(v[i] for v in shape['points']) for i in (0,1)]+[shape['offset']],
                    [max(v[i] for v in shape['points']) for i in (0,1)]+[shape['offset']+shape['depth']])
        for item in flat:
            lo,hi=bounds(item)
            for door in doors:
                other_lo,other_hi=bounds(door)
                self.assertFalse(all(min(hi[i],other_hi[i])-max(lo[i],other_lo[i])>1e-5
                                     for i in range(3)),(item['body'],door['body']))

    def test_first_aid_anchor_tracks_the_door_without_moving_desks(self):
        plan=copy.deepcopy(self.level_plans['OG3'])
        opening=next(value for value in plan['openings'] if value['id']=='D3_002N')
        wall=next(value for value in plan['walls'] if value['id']==opening['wall'])
        shift=-.1
        opening['interval']=[value+shift for value in opening['interval']]
        level_plans={**self.level_plans,'OG3':plan}
        other=furniture.compile(self.spec['sources']['furnishings'],stack.templates(self.spec)[0],self.p,self.data['levels'],level_plans)
        before={op['body']:op['shape'] for op in self.result['operations'] if op['action']=='create'}
        after={op['body']:op['shape'] for op in other['operations'] if op['action']=='create'}
        start,end=(plan['vertices'][wall[key]] for key in ('start','end'))
        for a,b in zip(before['PhD3002_FirstAid_Cabinet']['points'],after['PhD3002_FirstAid_Cabinet']['points']):
            for axis in (0,1):self.assertAlmostEqual(b[axis]-a[axis],shift*(end[axis]-start[axis])*self.p['display_scale'])
        for identity in before:
            if '_FirstAid_' not in identity:self.assertEqual(before[identity],after[identity])

    def test_separate_items_have_no_unintended_bbox_overlap(self):
        bounds={}
        for op in self.result['operations']:
            if op['action']!='create': continue
            shape=op['shape']
            if shape['kind']=='polygon_prism':
                lo=[min(v[i] for v in shape['points']) for i in (0,1)]+[shape['offset']]
                hi=[max(v[i] for v in shape['points']) for i in (0,1)]+[shape['offset']+shape['depth']]
            else:
                x,y,z=shape['origin'];r=shape['radius']
                lo=[x-r,y-r,z];hi=[x+r,y+r,z+shape['height']]
            bounds[op['body']]=(lo,hi)
        # These AABB overlaps are the intentionally cut basin and fridge cavities.
        cavity_pairs={frozenset(('LeftRun','Sink')),frozenset(('Fridge','Penguin')),frozenset(('Fridge','PenguinTea'))}
        names=list(bounds)
        for index,a in enumerate(names):
            for b in names[index+1:]:
                room,instance=a.split('_')[:2];other_room,other_instance=b.split('_')[:2]
                if (room,instance)==(other_room,other_instance): continue
                lo,hi=bounds[a];blo,bhi=bounds[b]
                if min(min(hi[k],bhi[k])-max(lo[k],blo[k]) for k in range(3))>1e-5:
                    self.assertEqual(room,other_room,(a,b))
                    if instance.startswith('Desk') and other_instance.startswith('Desk') and room=='PhD3002':
                        sa=next(op['shape'] for op in self.result['operations'] if op['body']==a and op['action']=='create')
                        sb=next(op['shape'] for op in self.result['operations'] if op['body']==b and op['action']=='create')
                        points=sa['points'];polygon=sb['points']
                        orientation=1 if floor.signed_area(polygon)>0 else -1
                        for x,y in zip(polygon,polygon[1:]+polygon[:1]):
                            normal=[orientation*(x[1]-y[1]),orientation*(y[0]-x[0])]
                            points=wall_worktops.clip(points,x,normal,0)
                            if not points:break
                        self.assertLessEqual(abs(floor.signed_area(points)) if len(points)>=3 else 0,1e-5,(a,b))
                    else:
                        self.assertIn(frozenset((instance,other_instance)),cavity_pairs,(a,b))

    def assert_media_source_binding(self, proof, compatibility, actual, camera_digest, site):
        # Historical images retain their original producer pins. Only the exact
        # reviewed browser revisions and separately proved site update are allowed.
        self.assertEqual(compatibility['format'], 'solidcraftbot.building-furnishings-media-compatibility/1')
        approved = compatibility['producer_updates']
        self.assertEqual(set(approved), MEDIA_COMPATIBLE_PRODUCERS)
        site_approved = compatibility['site_producer_updates']
        self.assertEqual(set(site_approved), MEDIA_COMPATIBLE_SITE_PRODUCERS)
        self.assertFalse(set(approved) & set(site_approved))
        self.assertEqual(set(actual), set(proof['source_files_sha256']))
        for name, digest in proof['source_files_sha256'].items():
            update = approved.get(name, site_approved.get(name))
            if update is not None:
                self.assertEqual(update['historical_sha256'], digest, name)
                self.assertNotEqual(update['historical_sha256'], update['current_sha256'], name)
                self.assertEqual(actual[name], update['current_sha256'], name)
            else:
                self.assertEqual(actual[name], digest, name)
        witness = compatibility['site_update']
        for field in ('native_build_report', 'native_site_proof', 'native_readonly_audit', 'native_scope'):
            self.assertEqual(witness[field], site[field], field)
        self.assertEqual(witness['native_scope'], {
            'unchanged_building_geometry_bodies': 1933,
            'semantically_unchanged_non_site_operations': 2755,
            'reopened_non_site_bodies_checked': 1933,
            'reopened_brep_byte_identical_bodies': 1812,
            'reopened_brep_reserialized_xor_zero_bodies': 121,
            'reopened_brep_maximum_xor_mm3': 0,
            'read_only_audit_inputs_stable': True,
            'read_only_audit_native_files_modified': False,
            'new_site_bodies': 5,
            'exact_site_step_comparisons': 5, 'maximum_site_step_xor_mm3': 0,
            'site_pair_checks': 10, 'front_band_continuity_checks': 2,
            'build_backends': 'freecad', 'full_building_cross_cad_checked': False,
            'full_building_cross_cad_check_repeated': False})
        self.assertEqual(len(witness['changed_site_body_ids']), witness['native_scope']['new_site_bodies'])
        self.assertEqual(set(witness['changed_site_body_ids']), set(self.data['exterior']['site_body_ids']))
        for name, update in site_approved.items():
            self.assertEqual(site['source_files_sha256'][name], update['current_sha256'], name)
        self.assertIs(site['original_photographs_included'], False)
        self.assertEqual(compatibility['camera_projection']['fields'], list(MEDIA_CAMERA_FIELDS))
        self.assertEqual(camera_digest, compatibility['camera_projection']['sha256'])
        for image in proof['images']:
            if 'browser_view' in image:
                self.assertEqual(compatibility['historical_manifest'], image['browser_view']['manifest'])

    def test_public_views_bind_current_sources_and_reviewed_images(self):
        path=stack.ROOT/'docs/media/building-furnishings.provenance.json'
        proof=json.loads(path.read_text())
        compatibility=json.loads((stack.ROOT/'docs/building-furnishings-media-compatibility.json').read_text())
        site_path=stack.ROOT/'docs/media/front-access-correction.provenance.json'
        site_bytes=site_path.read_bytes();site=json.loads(site_bytes)
        self.assertEqual(compatibility['site_update']['front_access_provenance'],
                         {'path':str(site_path.relative_to(stack.ROOT)),
                          'sha256':hashlib.sha256(site_bytes).hexdigest(), 'bytes':len(site_bytes)})
        self.assertEqual(compatibility['historical_provenance'],
                         {'path':str(path.relative_to(stack.ROOT)), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        self.assertFalse(proof['original_photographs_included'])
        self.assertEqual({image['id'] for image in proof['images']},{'Kitchen1008','PhD1002','PhD3002','Kitchen1008_EasterEgg'})
        # These preserved PNGs predate the explicitly added office devices and
        # microwave leaf. Validate their last compatible bindings separately;
        # never promote their old pixels to a current rendering claim.
        status=json.loads((stack.ROOT/'docs/building-furnishings-media-status.json').read_text())
        self.assertIs(status['historical_images_represent_current_model'], False)
        self.assertEqual(status['historical_provenance'], compatibility['historical_provenance'])
        self.assertEqual(set(status['last_compatible_sources_sha256']), set(proof['source_files_sha256']))
        self.assertEqual(set(status['current_sources_sha256']), set(proof['source_files_sha256'])|{'scripts/worktop_equipment.py'})
        for name,digest in status['current_sources_sha256'].items():
            self.assertEqual(hashlib.sha256((stack.ROOT/name).read_bytes()).hexdigest(),digest,name)
        # The equipped lab now belongs to the building frame. Its intentional
        # camera/scene change is recorded separately from the preserved PNGs.
        current_camera=media_camera_digest(walkthrough.compile())
        self.assertEqual(status['current_camera_projection'],
                         {'fields':list(MEDIA_CAMERA_FIELDS),'sha256':current_camera})
        self.assertIs(status['camera_projection_matches_historical'],False)
        archived_camera=compatibility['camera_projection']['sha256']
        self.assertNotEqual(current_camera,archived_camera)
        self.assert_media_source_binding(proof, compatibility, status['last_compatible_sources_sha256'], archived_camera, site)
        for image in proof['images']:
            data=(stack.ROOT/image['path']).read_bytes()
            self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(hashlib.sha256(data).hexdigest(),image['sha256'])
            self.assertTrue(image['visual_reviewed'])

    def test_media_compatibility_rejects_unreviewed_source_and_camera_drift(self):
        proof=json.loads((stack.ROOT/'docs/media/building-furnishings.provenance.json').read_text())
        compatibility=json.loads((stack.ROOT/'docs/building-furnishings-media-compatibility.json').read_text())
        site=json.loads((stack.ROOT/'docs/media/front-access-correction.provenance.json').read_text())
        actual=json.loads((stack.ROOT/'docs/building-furnishings-media-status.json').read_text())['last_compatible_sources_sha256']
        camera=compatibility['camera_projection']['sha256']
        for name in ('scripts/building_furnishings.py', 'scripts/building_walkthrough_viewer.html', 'scripts/building_exterior.py'):
            changed={**actual, name:'0'*64}
            with self.subTest(source=name), self.assertRaises(AssertionError):
                self.assert_media_source_binding(proof, compatibility, changed, camera, site)
        with self.subTest(camera=True), self.assertRaises(AssertionError):
            self.assert_media_source_binding(proof, compatibility, actual, '0'*64, site)
        changed=copy.deepcopy(compatibility)
        changed['producer_updates']['scripts/building_furnishings.py']={
            'historical_sha256':proof['source_files_sha256']['scripts/building_furnishings.py'],
            'current_sha256':'0'*64}
        with self.subTest(undeclared_producer=True), self.assertRaises(AssertionError):
            self.assert_media_source_binding(proof, changed, actual, camera, site)
        for field in ('native_build_report', 'native_site_proof', 'native_readonly_audit'):
            changed=copy.deepcopy(compatibility)
            changed['site_update'][field]['sha256']='0'*64
            with self.subTest(site_evidence=field), self.assertRaises(AssertionError):
                self.assert_media_source_binding(proof, changed, actual, camera, site)
        changed=copy.deepcopy(compatibility)
        changed['site_update']['native_scope']['full_building_cross_cad_check_repeated']=True
        with self.subTest(overstated_scope=True), self.assertRaises(AssertionError):
            self.assert_media_source_binding(proof, changed, actual, camera, site)

    def test_sources_match_declared_schemas(self):
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest('jsonschema is unavailable')
        anchor_schema = json.loads((stack.ROOT/'model/atrium-seating.schema.json').read_text())
        registry = Registry().with_resource('atrium-seating.schema.json', Resource.from_contents(anchor_schema))
        for source, schema in [('furnishings/building-social.json', 'building-furnishings.schema.json'), ('furniture/social.catalog.json', 'social-furniture-catalog.schema.json')]:
            Draft202012Validator(json.loads((stack.ROOT/'model'/schema).read_text()), registry=registry).validate(json.loads((stack.ROOT/'model'/source).read_text()))

    def test_stale_pins_rejected(self):
        ref=copy.deepcopy(self.spec['sources']['furnishings']);ref['source_sha256']='0'*64
        with self.assertRaises(ValueError): furniture.read(ref)

    def test_vertical_placement_and_body_ownership(self):
        source=stack.expanded(self.spec,self.p)
        by_room={r['id']:r for r in self.result['rooms']}
        for body in self.result['bodies']:
            room=by_room[body['component'].removesuffix('_Furniture')]
            self.assertFalse(room['placement_qualified'])
            self.assertGreater(room['presentation_scale'],0)
            for op in [o for o in self.result['operations'] if o['body']==body['id']]:
                shape=op['shape']; z=shape.get('offset',shape.get('origin',[0,0,0])[2])
                self.assertGreaterEqual(z,room['origin_mm'][2]-1e-6)
        stack.solidcraft_commands(self.spec,self.p)


class KitchenSeatingTests(unittest.TestCase):
    def test_kitchen_chairs_are_evenly_distributed_along_both_long_sides(self):
        ref=json.loads(stack.SOURCE.read_text())['sources']['furnishings']
        source=furniture.read(ref);catalog=furniture.read(source['catalog'])
        kitchen=next(room for room in source['rooms'] if room['room']=='1.008')
        tables=[item for item in kitchen['instances'] if item['id'].startswith('Table')]
        top=next(part['shape'] for part in furniture.parts_for(catalog,'desk') if part['id']=='Top')
        self.assertTrue(all(item['yaw_deg']==90 for item in tables))
        xlo=min(t['xyz_mm'][0]-top['size'][1] for t in tables)
        xhi=max(t['xyz_mm'][0] for t in tables)
        ylo=min(t['xyz_mm'][1] for t in tables)
        yhi=max(t['xyz_mm'][1]+top['size'][0] for t in tables)
        chairs=[item for item in kitchen['instances'] if item['type'] in ('dining_chair','office_chair')]
        self.assertEqual(len(chairs),8)
        sides=[[c for c in chairs if c['xyz_mm'][0]<xlo],[c for c in chairs if c['xyz_mm'][0]>xhi]]
        self.assertEqual([len(side) for side in sides],[4,4])
        rows=[]
        for side,yaw in zip(sides,[90,-90]):
            ys=sorted(c['xyz_mm'][1] for c in side);pitch=(yhi-ylo)/len(side)
            self.assertTrue(all(ylo<y<yhi for y in ys))
            self.assertTrue(all(c['yaw_deg']==yaw for c in side))
            for index,y in enumerate(ys):self.assertAlmostEqual(y,ylo+(index+.5)*pitch)
            rows.append(ys)
        self.assertEqual(rows[0],rows[1])


if __name__=='__main__': unittest.main()
