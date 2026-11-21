"""Gated source lift surfaces for the canonical BF01 floor-support proof.

A context is selected only for an allocated lift stage by its caller. It is a
geometry evaluator, not a resource grant. Ordinary support remains the first
choice; raised bodies are admitted only after replaying the actual compiled
cabin and door state over the entire requested time interval.
"""
import copy
import math

import building_fleet_model as model
from building_fleet_lift_checks import (_verify_export, active_port, gate_at,
                                       source_surface_contract, surface_rows_at)
from check_building_fleet_freecad import LiftTimeline


class PortSupportContext:
    def __init__(self, mesh, source, port_id, timeline, *, vehicle_id=None):
        model.validate(source)
        self.export_report = _verify_export(mesh)
        if not isinstance(timeline, LiftTimeline):
            raise ValueError('The compiled source LiftTimeline is required')
        port = active_port(mesh, port_id)
        if (timeline.config['object_id'] != mesh.manifest['elevator']['object_id']
                or timeline.config['ports'] != mesh.manifest['elevator']['ports']):
            raise ValueError('Compiled lift timeline belongs to a different source scene')
        if vehicle_id is not None and (not isinstance(vehicle_id, str)
                                      or len(vehicle_id) != 4 or not vehicle_id.startswith('BF')
                                      or not vehicle_id[2:].isdigit()
                                      or not 1 <= int(vehicle_id[2:]) <= source['fleet']['count']):
            raise ValueError('Only an own BF01..BF20 vehicle identity is accepted')
        self.mesh, self.source, self.port_id, self.timeline = mesh, copy.deepcopy(source), port_id, timeline
        self.vehicle_id = vehicle_id; self.level = port['level_id']
        self.settings = model.support_settings(source)
        contract = source_surface_contract()
        self.source_contract = contract
        if (contract['height_offset_mm'] > source['geometry']['floor_band_start_mm']
                or port_id not in contract['ports']):
            raise ValueError('Source lift surface top is outside the owner support contract')
        self._raised_rows = None; self._raised_index = None; self._proof_cache = {}
        self.applications = []; self.height_applications = []
        self.metadata = {'port_id': port_id, 'level_id': self.level,
                         'vehicle_id': vehicle_id,
                         'source_derived_height_offset_mm': contract['height_offset_mm'],
                         'source_surface_ids': contract['ports'][port_id]['source_surface_ids'],
                         'scope': 'Compiled numeric FK/door-gated native support only; no resource grant or wheel qualification'}

    def _gate_interval(self, start_s, end_s):
        if (any(type(t) not in (int, float) or not math.isfinite(t) or t < 0
                for t in (start_s, end_s)) or end_s < start_s):
            raise ValueError('Finite chronological compiled support interval required')
        times = {start_s, end_s, (start_s + end_s)/2}
        for row in self.timeline.schedule:
            for t in (row['start_s'], row['end_s']):
                if start_s < t < end_s: times.add(t)
        # Source lift/door curves are monotone quintics between these events.
        # Checking all event sides therefore bounds their full interval state;
        # a close-and-reopen cannot be hidden between two open endpoints.
        return [gate_at(self.mesh, self.port_id, self.timeline, t) for t in sorted(times)]

    def _rows(self, time_s):
        if self._raised_rows is None:
            data = surface_rows_at(self.mesh, self.port_id, self.timeline, time_s)
            self._raised_rows = [r for r in data['surface_rows'] if r['height_exception_applied']]
            from building_fleet_clearance import PolygonIndex
            polygons = []; self._raised_body_by_triangle = {}
            for row in self._raised_rows:
                for triangle in row['triangles_mm']:
                    polygons.append(triangle); self._raised_body_by_triangle[id(triangle)] = row['body_id']
            self._raised_index = PolygonIndex(polygons)
        return self._raised_rows

    def support(self, centre, yaw, half_length, half_width, *, start_s, end_s,
                ordinary_triangles, ordinary_body_ids, ordinary_result=None,
                curve_ref=None):
        """Apply R1/R2/R3 without adding a virtual surface or an edge overhang."""
        from building_fleet_support import support_covers, query_padding_mm
        if len(ordinary_triangles) != len(ordinary_body_ids):
            raise ValueError('Every ordinary native support triangle needs its body identity')
        case_id = getattr(self,'curve_reference',None)
        if case_id is not None:curve_ref={'curve_id':case_id,'interval':copy.deepcopy(curve_ref)}
        gap = self.settings['gap']['maximum']
        if ordinary_result is None:
            ordinary_result = support_covers(ordinary_triangles, centre, yaw,
                half_length, half_width, gap, body_ids=ordinary_body_ids, curve_ref=curve_ref)
        if ordinary_result['passed']:
            # A later ordinary prefix is allowed after the lift has left, but
            # it receives no raised support and no implicit shaft permission.
            return dict(ordinary_result, lift_height_exception_applied=False)
        gates = self._gate_interval(start_s, end_s)
        self._rows((start_s + end_s)/2)
        radius = math.hypot(half_length, half_width) + query_padding_mm(gap)
        lo = [v-radius for v in centre]; hi = [v+radius for v in centre]
        raised = self._raised_index.query(lo, hi)
        bodies = [self._raised_body_by_triangle[id(poly)] for poly in raised]
        if not raised:
            return dict(ordinary_result, lift_height_exception_applied=False)
        # Cache only byte-equivalent geometric queries against exactly these
        # same source surfaces. Exported Float64 missing polygons are NEVER
        # re-fed as new support; that could inflate a certified patch by1ULP.
        key = (tuple(centre), yaw, half_length, half_width,
               tuple(tuple(tuple(v) for v in tri) for tri in ordinary_triangles),
               tuple(ordinary_body_ids), tuple(bodies))
        if key not in self._proof_cache:
            proof = support_covers([*ordinary_triangles, *raised], centre, yaw,
                half_length, half_width, gap, body_ids=[*ordinary_body_ids, *bodies],
                curve_ref=curve_ref)
            if len(self._proof_cache) >= 512: self._proof_cache.clear()
            self._proof_cache[key] = copy.deepcopy(proof)
        result = copy.deepcopy(self._proof_cache[key])
        for application in result.get('applications', []):
            application['curve_refs'] = [] if curve_ref is None else [copy.deepcopy(curve_ref)]
            self.applications.append(copy.deepcopy(application))
        height = {**self.metadata, 'time_s': [start_s, end_s],
                  'body_ids': sorted(set(bodies)), 'curve_ref': copy.deepcopy(curve_ref),
                  'compiled_gate_checks': gates}
        result.update(lift_height_exception_applied=True,
                      lift_height_exception=height)
        if result['passed']: self.height_applications.append(height)
        return result

    def report(self):
        return {**self.metadata, 'gap_applications': copy.deepcopy(self.applications),
                'height_applications': copy.deepcopy(self.height_applications),
                'qualification': {'wheel_model': False, 'real_lift_operation': False}}
