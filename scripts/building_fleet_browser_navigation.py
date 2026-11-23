"""Retain pinned bearing witnesses for bit-identical browser route geometry.

Fresh native sweeps always run first. Only redundant portal bearing metadata
may retain its original source value when a platform's atan2 differs by one
adjacent float. Paths, resources, limits and existing cache guards are unchanged.
"""
import copy
import hashlib
import json
import math

import building_fleet_model as model
from building_fleet_routes import Navigation
from building_fleet_resources import ResourceCatalog
from building_fleet_patrol_cache import (GRAPH_FIELDS, QUALIFICATION, _artifact,
    _local, _mandatory_pins, _verify_pins)


POLICY = 'original_pinned_metadata_for_bit_identical_geometry'


def _typed(value, path=()):
    if (len(path) == 3 and path[0] == 'portal_certificates' and
            type(path[1]) is int and path[2] == 'yaw_rad'):
        if type(value) is not float or not math.isfinite(value):
            raise ValueError('Finite floating-point portal bearing required')
        return ['original_portal_bearing']
    if value is None:
        return ['null']
    if type(value) is bool:
        return ['bool', value]
    if type(value) is int:
        return ['int', str(value)]
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('Finite route metadata required')
        return ['float', value.hex()]
    if type(value) is str:
        return ['str', value]
    if type(value) is list:
        return ['list', [_typed(item, (*path, index)) for index, item in enumerate(value)]]
    if type(value) is dict and all(type(key) is str for key in value):
        return ['dict', [[key, _typed(value[key], (*path, key))] for key in sorted(value)]]
    raise ValueError('Closed JSON route metadata required')


def geometry_signature(route):
    certificates = route.get('portal_certificates') if isinstance(route, dict) else None
    if not isinstance(route, dict):
        raise ValueError('A complete route object is required')
    if ('portal_certificates' in route and (not isinstance(certificates, list) or
            any(not isinstance(row, dict) or 'yaw_rad' not in row for row in certificates))):
        raise ValueError('Explicit portal certificate bearing fields required')
    raw = json.dumps(_typed(route), separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _adjacent_or_same(original, fresh):
    if (type(original) is not float or type(fresh) is not float or
            not math.isfinite(original) or not math.isfinite(fresh)):
        return False
    return fresh.hex() in {original.hex(), math.nextafter(original, math.inf).hex(),
                          math.nextafter(original, -math.inf).hex()}


class BrowserNavigation(Navigation):
    """An opt-in witness adapter; base navigation/native checks stay intact."""
    def bind_source_metadata(self, graph_report_path):
        if hasattr(self, '_browser_bearing_templates'):
            raise RuntimeError('Original route witness binding cannot be replaced')
        model.validate(self.config)
        report_path = _local(graph_report_path)
        if not report_path.is_file() or report_path.stat().st_size > 1024*1024:
            raise ValueError('Bounded original static preparation report required')
        report = model.read_json(report_path)
        if (report.get('format') != 'solidcraftbot.building-fleet-static-preparation/1' or
                report.get('passed') is not True or report.get('engine_model_time_s') != 0 or
                report.get('qualification') != {'static_preparation_only': True,
                    'motion_executed': False, 'full_fleet_qualified': False, 'hardware_executed': False}):
            raise ValueError('Successful static-only source preparation required')
        pins = report.get('source_files_sha256_start')
        if pins != report.get('source_files_sha256_end'):
            raise ValueError('Original preparation source pins changed')
        _verify_pins(pins, _mandatory_pins(self))
        graph_path = _artifact(report.get('route_graph'))
        data = model.read_json(graph_path)
        if (type(data) is not dict or set(data) != GRAPH_FIELDS or
                data['format'] != 'solidcraftbot.building-fleet-route-graph-cache/1' or
                data['sealed'] is not True or data['qualification'] != QUALIFICATION or
                data['source_files_sha256'] != pins):
            raise ValueError('Original closed source-bound route graph required')
        if _artifact(data['world_report']) != self.mesh.world_report_path.resolve():
            raise ValueError('Witness templates belong to another native world')
        _artifact(data['navigation_input'])
        _artifact(data['resource_input'])
        routes = data['routes']
        if (type(routes) is not list or len(routes) != report.get('route_count') or
                ResourceCatalog.route_bank_hash(routes) != data['route_bank_sha256']):
            raise ValueError('Original complete source route-bank hash required')
        templates = {}
        signatures = []
        for route in routes:
            signature = geometry_signature(route)
            signatures.append(signature)
            if 'portal_certificates' not in route:
                continue
            bearings = tuple(row['yaw_rad'] for row in route['portal_certificates'])
            previous = templates.get(signature)
            if previous is not None and tuple(value.hex() for value in previous) != tuple(value.hex() for value in bearings):
                raise ValueError('Ambiguous original bearing witnesses for identical route geometry')
            templates[signature] = bearings
        # Recheck original bytes/pins before exposing a template binding.
        _verify_pins(pins, _mandatory_pins(self))
        _artifact(report['route_graph'])
        self._browser_bearing_templates = templates
        self._browser_bearing_provenance = {
            'policy': POLICY, 'source_route_bank_sha256': data['route_bank_sha256'],
            'graph_report': {'path': report_path.relative_to(model.ROOT).as_posix(),
                             'sha256': model.digest(report_path)},
            'route_graph': copy.deepcopy(report['route_graph']),
            'template_route_count': len(routes),
            'bearing_template_geometry_count': len(templates),
            'typed_geometry_signature_bank_sha256': hashlib.sha256(
                json.dumps(signatures, separators=(',', ':')).encode()).hexdigest(),
            'fresh_native_sweeps_required': True, 'matched_route_calls': 0,
            'unknown_route_calls': 0, 'rebound_route_calls': 0,
            'rebound_bearing_count': 0, 'maximum_ulp_distance': 0,
            'maximum_absolute_difference_rad': 0., 'examples': []}
        return self.browser_metadata_provenance()

    def browser_metadata_provenance(self):
        if not hasattr(self, '_browser_bearing_provenance'):
            raise RuntimeError('Original route witness templates are not bound')
        return copy.deepcopy(self._browser_bearing_provenance)

    def _own_right(self, result):
        # Never bypass the actual lane generation or fresh native sweeps.
        fresh = super()._own_right(result)
        if not hasattr(self, '_browser_bearing_templates'):
            raise RuntimeError('Bind original source witnesses before using browser navigation')
        signature = geometry_signature(fresh)
        original = self._browser_bearing_templates.get(signature)
        stats = self._browser_bearing_provenance
        if original is None:
            stats['unknown_route_calls'] += 1
            return fresh
        changes = []
        for index, (certificate, witness) in enumerate(zip(fresh['portal_certificates'], original)):
            local = certificate['yaw_rad']
            if not _adjacent_or_same(witness, local):
                raise ValueError('Fresh portal bearing differs from its source witness by more than one adjacent float')
            if local.hex() != witness.hex():
                changes.append((index, witness, local))
        stats['matched_route_calls'] += 1
        if changes:
            stats['rebound_route_calls'] += 1
        for index, witness, local in changes:
            fresh['portal_certificates'][index]['yaw_rad'] = witness
            stats['rebound_bearing_count'] += 1
            stats['maximum_ulp_distance'] = 1
            stats['maximum_absolute_difference_rad'] = max(
                stats['maximum_absolute_difference_rad'], abs(witness-local))
            if len(stats['examples']) < 8:
                stats['examples'].append({'route_geometry_signature': signature,
                    'segment_index': fresh['portal_certificates'][index]['segment_index'],
                    'original_witness_hex': witness.hex(), 'fresh_checked_bearing_hex': local.hex()})
        return fresh
