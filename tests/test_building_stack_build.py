"""Synthetic building presentation guards, without measured-plan fixtures."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import build_building_stack as build


class BuildingBuildTests(unittest.TestCase):
    def scene(self):
        levels=[];geometry=[]
        for i in range(4):
            z=i*4250.;floor='Floor'+str(i);wall='Wall'+str(i)
            levels.append({'id':'L'+str(i),'z_mm':z,'slab_bottom_mm':z-250,'slab_top_mm':z,'clear_top_mm':z+4000,'floor_bodies':[floor],'wall_bodies':[wall]})
            geometry.extend([{'body':floor,'bbox':{'min':[0,0,z-250],'max':[100,100,z]}},{'body':wall,'bbox':{'min':[0,0,z],'max':[100,1,z+4000]}}])
        geometry.extend([{'body':'Fill'},{'body':'Marker'}])
        return geometry,{'levels':levels,'marker_body_ids':['Marker'],'ground_fill_probe':{'target_body':'Fill'},'assumed_dimensions':{'clear_height_mm':4000}}

    def test_independent_backend_does_not_discover_other_cad(self):
        for backend,own,other in [('freecad','default_freecad_python','default_solidcraft_cli'),('solidcraft','default_solidcraft_cli','default_freecad_python')]:
            with patch.object(build.tool_paths,own,return_value='tool')as called,patch.object(build.tool_paths,other,side_effect=AssertionError('Other CAD queried')),patch.object(build,'build',return_value={}):
                build.main(['--backend',backend]);called.assert_called_once_with()

    def test_every_level_slab_and_wall_and_interstory_interval_is_checked(self):
        geometry,contract=self.scene();self.assertTrue(all(c['passed']for c in build.z_checks(geometry,contract)))
        for name,edge,delta in [('Floor2','min',1),('Floor3','max',1),('Wall0','max',-1),('Wall1','min',-1)]:
            mutated=copy.deepcopy(geometry);next(b for b in mutated if b['body']==name)['bbox'][edge][2]+=delta
            self.assertFalse(all(c['passed']for c in build.z_checks(mutated,contract)))
        with self.assertRaises(ValueError):build.z_checks(geometry+[{'body':'Unscoped'}],contract)

    def test_exact_polygon_ground_volume_retains_collinear_vertices_and_concave_variants(self):
        probe={'points_mm':[[0,0],[2,0],[4,0],[4,3],[0,3]],'offset_mm':-250,'depth_mm':250}
        self.assertEqual(build.prism_volume(probe),3000.)
        probe['points_mm']=[[0,0],[4,0],[4,1],[1,1],[1,3],[0,3]]
        self.assertEqual(build.prism_volume(probe),1500.)

    def test_positive_ground_proof_rejects_partial_fill_and_incomplete_native_results(self):
        raw={'checked':2,'count':1,'interferences':[{'a':'Fill','b':'Witness','volume_mm3':3000.}],
             'unchecked':[],'truncated':False,'budget_exceeded':False,'pairs_not_checked':0,'skipped_pairs':0}
        self.assertTrue(build.positive_ground(raw,'Fill','Witness',3000.,3000.)['passed'])
        self.assertFalse(build.positive_ground(raw,'Fill','Witness',4000.,3000.)['passed'])
        with self.assertRaises(ValueError):build.positive_ground({**raw,'unchecked':[{}]},'Fill','Witness',3000.,3000.)

    def test_closed_door_witness_checks_probe_material_not_whole_wall_volume(self):
        raw={'checked':2,'count':1,'interferences':[{'a':'LargeWall','b':'Witness','volume_mm3':12.}],
             'unchecked':[],'truncated':False,'budget_exceeded':False,'pairs_not_checked':0,'skipped_pairs':0}
        self.assertTrue(build.material_witness(raw,'LargeWall','Witness',12.)['passed'])
        self.assertFalse(build.material_witness(raw,'LargeWall','Witness',24.)['passed'])
        with self.assertRaises(ValueError):build.material_witness({**raw,'unchecked':[{}]},'LargeWall','Witness',12.)

    def test_actual_floor_union_requires_complete_coverage_without_double_counting(self):
        raw={'checked':3,'count':2,'interferences':[{'a':'LargeRoom','b':'Witness','volume_mm3':6.}, {'a':'Hall','b':'Witness','volume_mm3':6.}],
             'unchecked':[],'truncated':False,'budget_exceeded':False,'pairs_not_checked':0,'skipped_pairs':0}
        self.assertTrue(build.union_coverage(raw,['LargeRoom','Hall'],'Witness',12.)['passed'])
        self.assertFalse(build.union_coverage(raw,['LargeRoom','Hall'],'Witness',13.)['passed'])
        overlap={**raw,'count':3,'interferences':raw['interferences']+[{'a':'LargeRoom','b':'Hall','volume_mm3':2.}]}
        self.assertFalse(build.union_coverage(overlap,['LargeRoom','Hall'],'Witness',12.)['passed'])
        with self.assertRaises(ValueError):build.union_coverage({**raw,'pairs_not_checked':1},['LargeRoom','Hall'],'Witness',12.)
        wrong=copy.deepcopy(raw);wrong['interferences'][1]['a']='OtherRunFloor'
        with self.assertRaises(ValueError):build.union_coverage(wrong,['LargeRoom','Hall'],'Witness',12.)

    def test_sc_component_membership_comes_from_native_listing_not_measurement_or_source(self):
        geometry=[{'body':'StandaloneCabin','bbox':{'min':[0,0,0],'max':[1,1,1]}}]
        listing={'components':[{'id':0,'name':'Root','bodies':[],'occurrences':[]},
                               {'id':1,'name':'NativeLift','bodies':['StandaloneCabin'],'occurrences':[{'grounded':True,'parent':0}]}]}
        self.assertEqual(build.with_native_groups(geometry,listing)[0]['component'],'NativeLift')
        self.assertNotIn('component',geometry[0])
        changed=copy.deepcopy(listing);changed['components'][1]['bodies']=[]
        with self.assertRaises(ValueError):build.with_native_groups(geometry,changed)
        changed=copy.deepcopy(listing);changed['components'][1]['occurrences'][0]['grounded']=False
        with self.assertRaises(ValueError):build.with_native_groups(geometry,changed)

    def test_full_polygon_circle_shell_integral_matches_independent_quadrature(self):
        barrel={'axis':'X','profile_axis':'Y','radius_mm':5000.,'inner_radius_mm':4980.,'center_cross_mm':0.,'center_z_mm':-3000.}
        probe={'points_mm':[[0,-1000],[100,-1000],[100,1000],[0,1000]],'offset_mm':0.,'depth_mm':10000.}
        def delta(y):return (5000.**2-4980.**2)/(math.sqrt(5000.**2-y*y)+math.sqrt(4980.**2-y*y))
        steps=4096;h=2000/steps
        reference=100*h/3*(delta(-1000)+delta(1000)+sum((4 if i%2 else 2)*delta(-1000+i*h)for i in range(1,steps)))
        self.assertAlmostEqual(build.shell_area_volume(probe,barrel),reference,delta=reference*1e-9)
        shifted=copy.deepcopy(probe);shifted['points_mm']=[[x+1e7,y+5e7]for x,y in probe['points_mm']]
        self.assertAlmostEqual(build.shell_area_volume(shifted,{**barrel,'center_cross_mm':5e7}),reference,delta=reference*1e-9)

    def test_full_polygon_shell_integral_retains_concavity_and_requires_complete_height(self):
        barrel={'axis':'X','profile_axis':'Y','radius_mm':5000.,'inner_radius_mm':4980.,'center_cross_mm':0.,'center_z_mm':-3000.}
        prism=lambda points:{'points_mm':points,'offset_mm':0.,'depth_mm':10000.}
        concave=prism([[0,-1000],[200,-1000],[200,0],[50,0],[50,1000],[0,1000]])
        parts=[prism([[0,-1000],[200,-1000],[200,0],[0,0]]),prism([[0,0],[50,0],[50,1000],[0,1000]])]
        self.assertAlmostEqual(build.shell_area_volume(concave,barrel),sum(build.shell_area_volume(p,barrel)for p in parts),delta=.001)
        bbox=prism([[0,-1000],[200,-1000],[200,1000],[0,1000]])
        self.assertLess(build.shell_area_volume(concave,barrel),.7*build.shell_area_volume(bbox,barrel))
        with self.assertRaises(ValueError):build.shell_area_volume({**concave,'depth_mm':100.},barrel)

    def test_circulation_positive_probes_require_full_explicit_pair_coverage(self):
        probe={'id':'Synthetic','kind':'polygon_prism','points_mm':[[0,0],[2,0],[2,3],[0,3]],'offset_mm':0,'depth_mm':2,'target_bodies':['Wall']}
        circ={key:[]for key in ['door_probes','closed_door_probes','slab_hole_probes','connection_witnesses','shaft_witnesses']}
        circ['stairs']=[{'connectors':[{}, {}, {}]}]
        for key,count in [('door_probes',5),('slab_hole_probes',3)]:
            circ[key]=[{**probe,'id':key+str(i)}for i in range(count)]
        circ['closed_door_probes']=[{**probe,'id':'closed'+str(i),'target_body':'Wall','expected_volume_mm3':12.}for i in range(3)]
        for key,count in [('connection_witnesses',9),('shaft_witnesses',4)]:
            circ[key]=[{**probe,'id':key+str(i),'target_bodies':['Connector','Floor'],'expected_volumes_mm3':{'Connector':12.,'Floor':12.}}for i in range(count)]
        checks=build.circulation_probe_specs({'circulation':circ})
        self.assertEqual(len(checks),24)
        self.assertEqual(checks[-1]['expected'],{'Connector':12.,'Floor':12.})
        changed=copy.deepcopy(circ);changed['connection_witnesses'][0]['expected_volumes_mm3']['Floor']=6.
        with self.assertRaises(ValueError):build.circulation_probe_specs({'circulation':changed})
        changed=copy.deepcopy(circ);changed['closed_door_probes'].pop()
        with self.assertRaises(ValueError):build.circulation_probe_specs({'circulation':changed})
        changed=copy.deepcopy(circ);changed['connection_witnesses'][0]['expected_volumes_mm3'].pop('Floor')
        with self.assertRaises(ValueError):build.circulation_probe_specs({'circulation':changed})
        changed=copy.deepcopy(circ);changed['stairs'][0]['connectors'].pop()
        with self.assertRaises(ValueError):build.circulation_probe_specs({'circulation':changed})

    def test_elevator_open_and_closed_faces_and_stair_endpoints_are_distinct(self):
        levels=[{'id':name,'z_mm':i*4250.,'slab_bottom_mm':i*4250.-250}for i,name in enumerate(['EG','OG1','OG2','OG3'])]
        ports=[{'level_id':level['id'],'side':side,'active':i==0 or side=='outward','wall':side+'Wall'}for i,level in enumerate(levels)for side in ['outward','inward']]
        connectors=[{'body_id':'East'+str(i),'from_level':a['id'],'to_level':b['id']}for i,(a,b)in enumerate(zip(levels,levels[1:]))]
        geometry=[{'body':c['body_id'],'component':'EastStair','bbox':{'min':[0,0,levels[i]['z_mm']-5.],'max':[1,1,levels[i+1]['z_mm']]}}for i,c in enumerate(connectors)]
        geometry += [{'body':name,'component':'BuildingLift','bbox':{'min':[0,0,0],'max':[1,1,16750]}}for name in ['Shaft','Cabin','Frame']]
        circ={'elevator':{'doors_by_level':{'EG':['outward','inward'],'OG1':['outward'],'OG2':['outward'],'OG3':['outward']},'ports':ports,
                         'deferred_stops':[{'id':'KG','sides':['inward'],'elevation_mm':None,'status':'awaiting_plan'}],
                         'shaft_body_ids':['Shaft'],'cabin_body_ids':['Cabin'],'door_frame_body_ids':['Frame'],'component_id':'BuildingLift',
                         'served_extent':{'from_level':'KG','to_level':'OG3'}},
              'stairs':[{'area':'R3_028','component_id':'EastStair','connectors':connectors,'body_ids':[c['body_id']for c in connectors],
                         'served_extent':{'from_level':'KG','to_level':'OG3'},
                         'planned_connectors':[{'from_level':'KG','to_level':'EG','z0_mm':None,'z1_mm':None,'body_id':None,'status':'awaiting_plan'}]}],
              'body_ids':[body['body']for body in geometry],
              'detail_visibility_ids':['Shaft','Cabin'], 'closed_door_probes':[{'target_body':level['id']+'__Wall_inwardWall'}for level in levels[1:]]}
        contract={'levels':levels,'circulation':circ}
        self.assertEqual(len(build.circulation_geometry(contract,geometry)),5)
        self.assertTrue(all(c['passed']for c in build.circulation_geometry(contract,geometry)))
        changed=copy.deepcopy(contract);changed['circulation']['elevator']['ports'][3]['active']=True
        with self.assertRaises(ValueError):build.circulation_geometry(changed,geometry)
        changed=copy.deepcopy(contract);changed['circulation']['closed_door_probes'][0]['target_body']='AnotherWall'
        with self.assertRaises(ValueError):build.circulation_geometry(changed,geometry)
        changed=copy.deepcopy(geometry);changed[0]['bbox']['max'][2]-=1.
        self.assertFalse(all(c['passed']for c in build.circulation_geometry(contract,changed)))
        changed=copy.deepcopy(geometry);changed[0]['component']='BuildingLift'
        self.assertFalse(all(c['passed']for c in build.circulation_geometry(contract,changed)))
        changed=copy.deepcopy(contract);changed['circulation']['stairs'].append({**circ['stairs'][0],'area':'R3_017'})
        with self.assertRaises(ValueError):build.circulation_geometry(changed,geometry)
        changed=copy.deepcopy(contract);changed['circulation']['stairs'][0]['planned_connectors'][0]['body_id']='BasementBody'
        with self.assertRaises(ValueError):build.circulation_geometry(changed,geometry)


class BuildingNativeEvidenceTests(unittest.TestCase):
    def test_existing_native_proof_has_all_levels_and_scoped_holes(self):
        path=ROOT/'cad/building-stack/shared-build-report.json'
        if not path.exists():self.skipTest('Build native building presentation first')
        report=json.loads(path.read_text());self.assertTrue(report['passed']);self.assertFalse(report['metric_scale_known']);self.assertFalse(report['global_interference_checked'])
        build.common.verify_pins(report['source_files_sha256']);build.common.verify_artifacts({k:ROOT/v for k,v in report['files'].items()},report['artifact_sha256'])
        spec=build.model.load();contract=build.model.interfaces(spec,build.model.parameters(spec))
        expected={p['id']for p in contract['opening_probes']+contract['atrium_prisms']+[contract['ground_fill_probe']]}
        expected|={item['probe']['id']for item in build.circulation_probe_specs(contract)}
        expected|={item['probe']['id']for item in build.roof_probe_specs(contract)}
        for backend in ('solidcraft','freecad'):
            if report['backends']not in {backend,'both'}:continue
            proof=report['solidcraft_checks']if backend=='solidcraft'else json.loads((ROOT/report['files']['freecad_validation']).read_text())
            self.assertTrue(proof['passed']);self.assertEqual({c['id']for c in proof['probe_checks']},expected)
            self.assertEqual(len(proof['z_checks']),7);self.assertTrue(all(c['passed']for c in proof['z_checks']+proof['probe_checks']))
            if contract.get('circulation'):
                stairs=contract['circulation']['stairs']
                self.assertEqual([stair['area']for stair in stairs],['R3_028'])
                external=contract['circulation'].get('external_stairs',[])
                if external:self.assertEqual([(stair['area'],stair['classification'])for stair in external],[('R3_017','external_metal')])
                expected_geometry={'separate_stair_and_elevator_groups','no_basement_geometry'}|{c['body_id']+'_end_levels'for stair in stairs+external for c in stair['connectors']}
                self.assertEqual({check['id']for check in proof['circulation_geometry_checks']},expected_geometry)
                self.assertTrue(all(c['passed']for c in proof['circulation_geometry_checks']))
                by_id={check['id']:check for check in proof['probe_checks']}
                for item in build.circulation_probe_specs(contract):
                    self.assertEqual(set(by_id[item['probe']['id']]['target_evidence']),set(item['expected']))
            if contract.get('roof'):
                self.assertTrue(proof['roof_geometry_checks'])
                self.assertTrue(all(check['passed']for check in proof['roof_geometry_checks']))
                if contract['roof'].get('corridor_coverage_probes'):
                    self.assertTrue(proof['native_corridor_roof_checks_passed'])
                    self.assertEqual({check['area_id']for check in proof['corridor_roof_checks']},set(contract['roof']['covered_corridor_area_ids']))
                    self.assertTrue(all(check['passed']for check in proof['corridor_roof_checks']))
                    self.assertTrue(report['native_corridor_roof_checks_passed'][backend])
        if contract.get('circulation'):
            self.assertIn('circulation',report['renders'])
            self.assertIn('ground',report['renders'])
        if contract.get('roof'):self.assertIn('roof',report['renders'])
        if report['backends']=='both':self.assertLess(report['maximum_step_xor_presentation_mm3'],.001)


if __name__=='__main__':unittest.main()
