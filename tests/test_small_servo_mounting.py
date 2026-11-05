"""X2/X4 drawing dimensions, worst-case stacks and actual generated pin/plate solids."""
import copy,json,math,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from servo_mounting_design import analyse
import robot_spec as model
import robot_components as components

class SmallServoFits(unittest.TestCase):
    def setUp(self):
        self.sources={size:json.loads((ROOT/f'model/{size}-mounting-interface.json').read_text()) for size in ['x2','x4']}

    def test_drawing_thread_and_dowel_depths_are_not_step_core_depths(self):
        for size,expected in [('x2',[(4,4,4),(4,5,4)]),('x4',[(6,6,4),(6,6,3)])]:
            for name,(count,thread,locating) in zip(['housing','output'],expected):
                source=self.sources[size][name]
                self.assertEqual(source['fastener_count'],count)
                self.assertEqual(source['vendor_thread_depth_mm'],thread)
                self.assertEqual(source['locating_bores']['depth_mm'],locating)
        self.assertEqual(self.sources['x4']['output']['locating_bores']['count'],3)
        self.assertEqual(len(self.sources['x4']['output']['plate_locating_pins']['unused_centres_mm']),1)

    def test_screw_stacks_have_length_and_bottoming_reserve(self):
        for size,values in [('x2',[(3.1,2.9,3.3,.5),(4.1,3.9,4.3,.5)]),('x4',[(5.1,4.9,5.3,.5)]*2)]:
            report=analyse(self.sources[size])
            for name,(nominal,lo,hi,margin) in zip(['housing','output'],values):
                data=report['fasteners'][name]
                self.assertAlmostEqual(data['nominal_axial_thread_overlap_mm'],nominal)
                for a,b in zip(data['axial_thread_overlap_range_mm'],[lo,hi]):self.assertAlmostEqual(a,b)
                self.assertAlmostEqual(data['minimum_tip_margin_mm'],margin)
                self.assertIsNone(data['torque_nm'])
        self.assertIn('08.8',self.sources['x2']['output']['fastener_design']['designation'])

    def test_pin_clearance_retention_and_relief(self):
        for size in self.sources:
            result=analyse(self.sources[size])
            for name in ['housing','output']:
                data=result['locating'][name]
                self.assertAlmostEqual(data['diametral_clearance_range_mm'][0],0)
                self.assertAlmostEqual(data['diametral_clearance_range_mm'][1],.026 if size=='x2' else .036)
                for a,b in zip(data['retention_interference_range_mm'],[.004,.016]):self.assertAlmostEqual(a,b)
                self.assertGreater(data['minimum_vendor_bore_tip_margin_mm'],.25)
                self.assertGreater(data['radial_relief_allowance_mm'],data['worst_assumed_offset_including_primary_pin_float_mm'])
                self.assertGreater(data['minimum_diamond_corner_clearance_mm'],0)

    def test_bad_thickness_head_type_length_or_retention_is_rejected(self):
        for size in self.sources:
            with self.assertRaisesRegex(ValueError,'thickness changed'):analyse(self.sources[size],7)
            source=copy.deepcopy(self.sources[size]);source['housing']['fastener_design']['length_mm']+=2
            with self.assertRaisesRegex(ValueError,'bottoming'):analyse(source)
            source=copy.deepcopy(self.sources[size]);source['housing']['plate_locating_pins']['stem_diameter_limits_mm']=[2.99,3]
            with self.assertRaisesRegex(ValueError,'retention'):analyse(source)
        source=copy.deepcopy(self.sources['x2']);source['output']['fastener_design']['head_height_max_mm']=3
        with self.assertRaisesRegex(ValueError,'proud'):analyse(source)
        source=copy.deepcopy(self.sources['x4']);source['housing']['plate_locating_pins']['relieved_tangential_width_limits_mm']=[2.994,3]
        with self.assertRaisesRegex(ValueError,'corners'):analyse(source)
        source=copy.deepcopy(self.sources['x4']);source['housing']['plate_locating_pins']['assumed_relief_clocking_error_deg']=10
        with self.assertRaisesRegex(ValueError,'corners'):analyse(source)

    def test_twenty_own_pins_stay_with_their_plate_links(self):
        spec=model.load();expanded=model.expanded(spec);pins=[(l,o) for l in expanded['links'] for o in l['recipe'] if o.get('role')=='locating_pin']
        self.assertEqual(len(pins),20)
        for link,op in pins:
            plate=op['body'].split('_pin_')[0]
            self.assertTrue(any(o.get('body')==plate and o['action']=='mount_plate' for l in spec['links'] if l['id']==link['id'] for o in l['recipe']))

    @unittest.skipUnless((ROOT / 'exports/generated/build-report.json').is_file(), "Requires local CAD/ROS build: python scripts/build_models.py --ros2")
    def test_native_plates_and_pins_match_independent_analytic_volumes(self):
        spec=model.load();lib=components.library(spec)
        build=json.loads((ROOT/'exports/generated/build-report.json').read_text())
        self.assertEqual(build['spec_sha256'],model.digest(model.SPEC))
        report=json.loads((ROOT/build['artifacts']['freecad_report']).read_text());bodies={b['body']:b for b in report['geometry']}
        for link in spec['links']:
            for op in link['recipe']:
                if op['action']!='mount_plate' or op['part']=='RMD-X6-P20-60-E':continue
                interface=lib['parts'][op['part']]['interfaces'][op['section']];pins=interface['plate_locating_pins'];recess=interface['plate_head_recess']
                thickness=model.evaluate(op['thickness_mm'],model.parameters(spec));n=len(interface['hole_centres_mm']);r=interface['plate_clearance_diameter_mm']/2
                volume=math.pi*thickness*(op['outer_radius_mm']**2-op['clearance_radius_mm']**2-n*r*r)
                volume-=n*math.pi*((recess['diameter_mm']/2)**2-r*r)*recess['depth_mm']
                volume-=2*math.pi*(pins['retention_bore_nominal_diameter_mm']/2)**2*pins['retention_depth_mm']
                self.assertAlmostEqual(bodies[op['body']]['volume_mm3'],volume,places=5)
                rh=pins['head_nominal_diameter_mm']/2
                base=math.pi*(pins['stem_nominal_diameter_mm']/2)**2*pins['stem_length_mm']
                for suffix in ['round','relieved']:
                    area=math.pi*rh*rh
                    if suffix=='relieved':area=pins['relieved_radial_width_mm']*pins['relieved_tangential_width_mm']/2
                    self.assertAlmostEqual(bodies[op['body']+'_pin_'+suffix]['volume_mm3'],base+area*pins['projection_mm'],places=6)
        self.assertTrue(report['screw_head_clearance']['passed']);self.assertEqual(len(report['screw_head_clearance']['checks']),70)
        self.assertTrue(report['retained_pin_clearance']['passed']);self.assertEqual(len(report['retained_pin_clearance']['checks']),20)

if __name__=='__main__':unittest.main()
