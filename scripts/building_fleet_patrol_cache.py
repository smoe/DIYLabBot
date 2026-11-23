"""Restore source-bound static BF01 graph data without weakening motion checks."""
import copy
import math
from pathlib import Path

import building_fleet_model as model
from building_fleet_missions import MissionPlanner
from building_fleet_resources import ResourceCatalog
from building_fleet_runner import RouteGraph


GENERATORS = ('building_fleet_runner.py', 'building_fleet_missions.py',
              'building_fleet_motion.py', 'building_fleet_resources.py',
              'building_fleet_port_paths.py', 'building_fleet_lift_checks.py',
              'building_fleet_geometry_checks.py')
GRAPH_FIELDS = frozenset({'format', 'source_files_sha256', 'world_report',
    'navigation_input', 'resource_input', 'sealed', 'hubs', 'endpoints',
    'centreline', 'repairs', 'routes', 'route_bank_sha256', 'qualification', 'scope'})
QUALIFICATION = {'static_derivation_only': True, 'motion_executed': False,
                 'native_motion_qualified': False, 'full_fleet_qualified': False}
MAX_GRAPH_BYTES = 128 * 1024 * 1024


def _local(path):
    root = model.ROOT.resolve()
    result = (root / Path(path)).resolve()
    if not result.is_relative_to((root / 'exports/building-fleet').resolve()):
        raise ValueError('Static graph evidence must remain in BF01 exports')
    return result


def _artifact(ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256', 'bytes'}:
        raise ValueError('Exact named graph artifact, SHA256 and size required')
    path = _local(ref['path'])
    if (type(ref['bytes']) is not int or not 0 < ref['bytes'] <= MAX_GRAPH_BYTES
            or not path.is_file() or path.stat().st_size != ref['bytes']):
        raise ValueError('Missing, altered or oversized static graph artifact')
    return model.resolve_pin(ref)


def _mandatory_pins(nav):
    world = nav.mesh.world_report_path.resolve()
    if not world.is_relative_to(model.ROOT.resolve()):
        raise ValueError('Project-local navigation world required')
    return {**nav._cache_pins(),
        **{'scripts/' + name: model.digest(model.ROOT / 'scripts' / name)
           for name in GENERATORS},
        str(world.relative_to(model.ROOT.resolve())): model.digest(world)}


def _verify_pins(pins, required):
    if (not isinstance(pins, dict) or not required
            or any(pins.get(name) != digest for name, digest in required.items())):
        raise ValueError('Missing or stale mandatory static graph source pins')
    for path, digest in pins.items():
        model.resolve_pin({'path': path, 'sha256': digest})


def _point(value):
    if (type(value) is not list or len(value) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        raise ValueError('Finite two-dimensional graph point required')
    return tuple(value)


def _endpoints(value):
    if type(value) is not dict:
        raise ValueError('Named static graph endpoint sets required')
    result = {}
    for level, points in value.items():
        if not isinstance(level, str) or type(points) is not list:
            raise ValueError('Named static graph endpoint sets required')
        rows = [_point(p) for p in points]
        if len(rows) != len(set(rows)):
            raise ValueError('Duplicate static graph endpoint')
        result[level] = set(rows)
    return result


def _routes(rows, graph, *, repairs):
    if type(rows) is not list:
        raise ValueError('Static graph route rows required')
    result = {}
    for row in rows:
        if type(row) is not dict or set(row) != {'level', 'start', 'end', 'route'}:
            raise ValueError('Closed static graph route row required')
        level = row['level']
        a, b = _point(row['start']), _point(row['end'])
        if level not in graph.endpoints or a not in graph.endpoints[level] or b not in graph.endpoints[level]:
            raise ValueError('Static route references an unknown endpoint')
        hub = tuple(graph.hubs[level])
        if a == b or (repairs and hub in (a, b)) or (not repairs and b != hub):
            raise ValueError('Static route disagrees with its graph role')
        key = (level, a, b)
        route = row['route']
        if (key in result or type(route) is not dict or route.get('level') != level
                or route.get('curve_qualified') is not False):
            raise ValueError('Unique unqualified source-level graph route required')
        points = route.get('points_mm')
        if (type(points) is not list or len(points) < 2
                or _point(points[0]) != a or _point(points[-1]) != b):
            raise ValueError('Graph route does not retain its declared endpoints')
        for point in points:
            _point(point)
        result[key] = copy.deepcopy(route)
    return result


def prepare_cached(source, nav, graph_report_path, resource_cache, progress=None):
    """Restore static routing only; reject stale evidence without a fallback."""
    model.validate(source)
    if nav.config != source:
        raise ValueError('Source-matched navigation required for static graph reuse')
    report_path = _local(graph_report_path)
    if not report_path.is_file() or report_path.stat().st_size > 1024 * 1024:
        raise ValueError('Bounded static preparation report required')
    report = model.read_json(report_path)
    if (report.get('format') != 'solidcraftbot.building-fleet-static-preparation/1'
            or report.get('passed') is not True
            or report.get('engine_model_time_s') != 0
            or report.get('qualification') != {'static_preparation_only': True,
                'motion_executed': False, 'full_fleet_qualified': False,
                'hardware_executed': False}):
        raise ValueError('Successful static-only graph preparation report required')
    required = _mandatory_pins(nav)
    pins = report.get('source_files_sha256_start')
    if pins != report.get('source_files_sha256_end'):
        raise ValueError('Graph preparation sources changed during derivation')
    _verify_pins(pins, required)
    graph_path = _artifact(report.get('route_graph'))
    data = model.read_json(graph_path)
    if (type(data) is not dict or set(data) != GRAPH_FIELDS
            or data['format'] != 'solidcraftbot.building-fleet-route-graph-cache/1'
            or data['sealed'] is not True or data['qualification'] != QUALIFICATION
            or data['source_files_sha256'] != pins):
        raise ValueError('Closed source-bound static graph cache required')
    if _artifact(data['world_report']) != nav.mesh.world_report_path.resolve():
        raise ValueError('Graph cache belongs to another navigation world')
    _artifact(data['navigation_input'])
    if _artifact(data['resource_input']) != _local(resource_cache) / 'cache-report.json':
        raise ValueError('Graph cache belongs to another resource cache')
    if progress is not None:
        progress({'phase': 'static_graph_cache_restore'})
    graph = RouteGraph(nav, progress=progress)
    planner = MissionPlanner(source, nav, graph)
    # Match exactly the source endpoint registration in RouteGraph.prepare.
    for home in nav.homes.values():
        graph.add_endpoint(home['level'], home['departure_xy_mm'])
        graph.add_endpoint(home['level'], home['arrival_xy_mm'])
    for (level, _), inspection in nav.inspections.items():
        graph.add_endpoint(level, inspection['points_mm'][0])
        graph.add_endpoint(level, inspection['points_mm'][-1])
    if data['hubs'] != graph.hubs or _endpoints(data['endpoints']) != graph.endpoints:
        raise ValueError('Cached graph endpoints differ from current source endpoints')
    centres = _routes(data['centreline'], graph, repairs=False)
    expected_order = [(level, endpoint, tuple(graph.hubs[level]))
        for level, endpoints in graph.endpoints.items()
        for endpoint in sorted(endpoints) if endpoint != tuple(graph.hubs[level])]
    if set(centres) != set(expected_order):
        raise ValueError('Static graph does not contain every source hub connection')
    # JSON rows have a serialization order; the bank retains the derivation's
    # source-level / sorted-endpoint iteration order from RouteGraph.prepare.
    graph.centreline = {key: centres[key] for key in expected_order}
    repairs = _routes(data['repairs'], graph, repairs=True)
    graph.repairs = {key: repairs[key] for level in graph.endpoints
                     for key in sorted(repairs) if key[0] == level}
    graph.sealed = True
    routes = graph.base_routes() + planner.prepared_routes()
    bank = ResourceCatalog.route_bank_hash(routes)
    if (type(data['routes']) is not list or bank != data['route_bank_sha256']
            or ResourceCatalog.route_bank_hash(data['routes']) != bank
            or len(routes) != report.get('route_count')
            or len(graph.centreline) != report.get('centreline_count')
            or len(graph.repairs) != report.get('repair_count')):
        raise ValueError('Restored complete route bank differs from its pinned derivation')
    catalog = ResourceCatalog.from_cache(nav, routes, _local(resource_cache))
    if _mandatory_pins(nav) != required:
        raise ValueError('Static graph inputs changed during reconstruction')
    _verify_pins(pins, required)
    if progress is not None:
        progress({'phase': 'static_graph_cache_ready', 'routes': len(routes)})
    return graph, catalog, planner
