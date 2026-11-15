"""Wall contact, butt joins and doorway preservation from shared room geometry."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_furnishings as furniture
import building_stack as stack
import wall_worktops as worktops


class WallWorktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = json.loads(stack.SOURCE.read_text())
        cls.p = stack.parameters(raw); cls.plan = stack.templates(raw)[0]
        cls.source = json.loads((ROOT/'model/furnishings/building-social.json').read_text())
        cls.catalog = furniture.read(cls.source['catalog'])
        cls.room = next(r for r in cls.source['rooms'] if r['id']=='PhD3002')
        cls.effective = copy.deepcopy(cls.plan)
        # Explicit fixture for the owner's OG3-only closed right boundary.
        cls.effective['openings'] = [o for o in cls.plan['openings'] if o['id']!='D3_002_003']
        cls.scale = 0.8819000819000824

    def fitted(self, room=None, plan=None):
        return worktops.fit_spans(room or self.room, self.catalog, plan or self.effective, self.p, self.scale)

    def test_legacy_default_parts_remain_exactly_unchanged(self):
        # Captured from the original five-part catalog before parameterization.
        parts = furniture.parts_for(self.catalog,'desk')
        digest = hashlib.sha256(json.dumps(parts,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(digest,'8f2e460fe6b3051ac266d770bbc2d59fd1a3e368f8184d1ba39351b1ce152311')

    def test_each_worktop_back_is_flush_with_the_actual_inner_wall(self):
        fits = self.fitted()
        self.assertEqual(set(fits),{'Desk0','Desk1','Desk2','Desk3'})
        for fit in fits.values():
            distances = [sum((q[i]-fit['back'][i])*fit['inward'][i] for i in (0,1)) for q in fit['points']]
            self.assertGreaterEqual(min(distances),-1e-7)
            self.assertAlmostEqual(min(distances),0,places=7)
            self.assertEqual(sum(abs(d)<1e-7 for d in distances),2)
        # The tilted window back is followed exactly, rather than approximated by XY placement.
        window = fits['Desk3']
        back = [q for q in window['points'] if abs(sum((q[i]-window['back'][i])*window['inward'][i] for i in (0,1)))<1e-7]
        self.assertGreater(abs(back[0][1]-back[1][1]),1)

    def test_window_owns_corners_and_side_tops_have_no_gap_or_overlap(self):
        fits = self.fitted(); owner = fits['Desk3']
        for name in ['Desk0','Desk2']:
            distances = [sum((q[i]-owner['back'][i])*owner['inward'][i] for i in (0,1))-owner['depth'] for q in fits[name]['points']]
            self.assertGreaterEqual(min(distances),-1e-7)
            self.assertEqual(sum(abs(d)<1e-7 for d in distances),2)
        self.assertEqual({f['span']['wall_id'] for f in fits.values()},{'W070','W072','W086'})

    def test_left_glass_door_aperture_and_margin_remain_free(self):
        fits = self.fitted(); opening = next(o for o in self.effective['openings'] if o['id']=='D3_002_001')
        area = next(a for a in self.effective['areas'] if a['id']=='R3_002')
        origin,u,_,length = worktops.wall_frame(self.effective,area,'W086',self.p)
        margin = 60*self.scale
        for name,bound,sign in [('Desk1',opening['interval'][0]*length-margin,1),('Desk2',opening['interval'][1]*length+margin,-1)]:
            projected = [sum((q[i]-origin[i])*u[i] for i in (0,1)) for q in fits[name]['points']]
            self.assertTrue(all(sign*(v-bound)<=1e-7 for v in projected),name)

    def test_door_movement_recomputes_both_split_lengths_only(self):
        plan = copy.deepcopy(self.effective)
        opening = next(o for o in plan['openings'] if o['id']=='D3_002_001')
        opening['interval'] = [v+.01 for v in opening['interval']]
        before,after = self.fitted(),self.fitted(plan=plan)
        for name in ['Desk0','Desk3']:
            self.assertEqual(before[name]['points'],after[name]['points'])
        self.assertGreater(after['Desk1']['values']['length'],before['Desk1']['values']['length'])
        self.assertLess(after['Desk2']['values']['length'],before['Desk2']['values']['length'])

    def test_effective_level_plan_is_required_for_the_closed_right_wall(self):
        with self.assertRaisesRegex(ValueError,'cannot cover a doorway'):
            self.fitted(plan=self.plan)

    def test_parameters_are_bounded_and_dependent_geometry_is_rebuilt(self):
        definition = self.catalog['types']['desk']
        for overrides in [{'depth':True},{'height':float('nan')},{'length':1},{'unknown':100}]:
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                worktops.desktop_parts(definition,overrides)
        parts = worktops.desktop_parts(definition,{'length':3000})
        self.assertEqual(parts[0]['shape']['size'][0],3000)
        end_leg = next(p for p in parts if p['id']=='Leg1300_40')
        self.assertEqual(end_leg['shape']['origin'][0],2900)
        self.assertTrue(any(p['id'].startswith('LegMid') for p in parts))

    def test_all_supports_stay_inside_their_derived_top(self):
        for fit in self.fitted().values():
            parts = worktops.desktop_parts(self.catalog['types']['desk'],fit['values'],fit['footprint'])
            self.assertGreater(len(parts),4)
            self.assertEqual(parts[0]['shape']['points'],fit['footprint'])

    def test_invalid_pose_and_nonuniform_top_height_fail_closed(self):
        for change in ['gap','offset','length','height']:
            room = copy.deepcopy(self.room); item = next(i for i in room['instances'] if i['id']=='Desk0')
            if change=='gap':item['wall_span']['back_gap_mm']=10
            elif change=='offset':item['xyz_mm'][0]=10
            else:item['parameter_overrides_mm']={change:900}
            with self.subTest(change=change),self.assertRaises(ValueError):self.fitted(room=room)

    def test_common_instancing_keeps_one_geometry_path(self):
        parts = furniture.parts_for(self.catalog,'desk')
        direct = furniture.place_parts(parts,'Example','Furniture',lambda x,y,z:[10-2*y,20+2*x,30+2*z],2)
        ordinary = furniture.instantiate(self.catalog,'desk','Example','Furniture',[10,20,30],90,2)
        for left,right in zip(direct['operations'],ordinary['operations']):
            self.assertEqual(left['body'],right['body'])
            for a,b in zip(left['shape']['points'],right['shape']['points']):
                for x,y in zip(a,b):self.assertAlmostEqual(x,y)


if __name__=='__main__':unittest.main()
