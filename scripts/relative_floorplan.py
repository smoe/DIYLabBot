"""Relative 2D topology and explicitly arbitrary CAD/SVG visualizations.

No image is loaded or embedded. Relative coordinates and labels are the sole
plan input. Display millimetres are not measured building dimensions.
"""
from pathlib import Path
import copy
import hashlib
import html
import json
import math
import re

import robot_spec as robot
import tube_carrier_model as portable

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/floor-f03.shared.json'
SCHEMA = ROOT/'model/relative-floorplan.schema.json'
FORMAT = 'solidcraftbot.relative-floorplan/1'
EPS = 1e-9
CONFIDENCE = {'clear', 'approximate', 'uncertain'}
DEFAULTS = {'display_height': 50, 'display_thickness': 3, 'display_floor_depth': 1}
DISPLAY_DEFAULTS = DEFAULTS
digest = robot.digest
evaluate = robot.evaluate


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, fields, label):
    require(isinstance(value, dict) and set(value) == set(fields.split()), 'Invalid '+label+' fields')


def finite(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Finite numeric coordinate required')
    return value


def identity(value):
    require(isinstance(value, str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', value), 'Stable ASCII identifier required')
    return value


def cross(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])


def on_segment(point, a, b, *, strict=False):
    length = math.dist(a, b)
    if abs(cross(a, b, point)) > EPS*length:
        return False
    t = sum((point[i]-a[i])*(b[i]-a[i]) for i in (0, 1))/(length*length)
    return EPS/length < t < 1-EPS/length if strict else -EPS/length <= t <= 1+EPS/length


def side(a, b, point):
    distance = cross(a, b, point)/math.dist(a, b)
    return 0 if abs(distance) <= EPS else (1 if distance > 0 else -1)


def signed_area(points):
    return sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:]+points[:1]))/2


def point_membership(point, polygon):
    """Return 0 on boundary, 1 inside and -1 outside a simple polygon."""
    inside = False
    for a, b in zip(polygon, polygon[1:]+polygon[:1]):
        if on_segment(point, a, b):
            return 0
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = a[0]+(point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if x > point[0]:
                inside = not inside
    return 1 if inside else -1


def area_vertices(spec, area):
    walls = {wall['id']: wall for wall in spec['walls']}
    return [walls[ref['wall']]['start' if ref['direction'] == 1 else 'end'] for ref in area['boundary']]


def area_points(spec, area):
    return [spec['vertices'][vertex] for vertex in area_vertices(spec, area)]


def outline(spec, area):
    """Return a derived relative polygon by area ID or area object."""
    spec = _plan(spec)
    selected = next((item for item in spec['areas'] if item['id'] == area), None) if isinstance(area, str) else area
    require(selected is not None, 'Unknown area')
    return copy.deepcopy(area_points(spec, selected))


def validate(spec):
    leading = {k: v for k, v in spec.items() if k != '_source'}
    exact(leading, 'format id units calibration vertices walls areas openings provenance', 'relative plan')
    require(spec['format'] == FORMAT and spec['units'] == {'length': 'relative'} and spec['calibration'] is None, 'Relative coordinates without metric calibration required')
    identity(spec['id'])
    provenance = spec['provenance']
    exact(provenance, 'method source_kind accuracy notes', 'public provenance')
    require(provenance['method'] == 'manual_trace' and provenance['source_kind'] in {'photograph_of_plan', 'synthetic_fixture'} and provenance['accuracy'] == 'approximate', 'Declare approximate manual tracing')
    require(isinstance(provenance['notes'], list) and all(isinstance(v, str) and v for v in provenance['notes']), 'Text-only trace notes required')
    require(isinstance(spec['vertices'], dict) and len(spec['vertices']) >= 3, 'Plan vertices required')
    vertices = spec['vertices']
    for name, point in vertices.items():
        identity(name)
        require(isinstance(point, list) and len(point) == 2, 'Two relative coordinates required')
        for value in point:
            finite(value)
    for index, (name, point) in enumerate(vertices.items()):
        for other, position in list(vertices.items())[index+1:]:
            require(math.dist(point, position) > EPS, 'Duplicate vertex coordinates: '+name+'/'+other)
    require(isinstance(spec['walls'], list), 'Boundary list required')
    walls = {}; edges = set()
    for wall in spec['walls']:
        exact(wall, 'id start end kind', 'wall or open boundary')
        identity(wall['id'])
        require(wall['id'] not in walls, 'Duplicate wall ID')
        require(wall['kind'] in {'wall', 'open_boundary', 'unknown'}, 'Unknown boundary kind')
        require(wall['start'] in vertices and wall['end'] in vertices and wall['start'] != wall['end'], 'Distinct existing wall endpoints required')
        edge = frozenset((wall['start'], wall['end']))
        require(edge not in edges, 'Shared boundary must be described once')
        edges.add(edge); walls[wall['id']] = wall
        a, b = vertices[wall['start']], vertices[wall['end']]
        for name, point in vertices.items():
            if name not in edge:
                require(not on_segment(point, a, b, strict=True), 'Split T-junction at vertex '+name+' on '+wall['id'])
    for index, wall in enumerate(spec['walls']):
        a, b = (vertices[wall[key]] for key in ('start', 'end'))
        for other in spec['walls'][index+1:]:
            if {wall['start'], wall['end']} & {other['start'], other['end']}:
                continue
            c, d = (vertices[other[key]] for key in ('start', 'end'))
            require(not (side(a, b, c)*side(a, b, d) == -1 and side(c, d, a)*side(c, d, b) == -1), 'Crossing boundaries require a shared split vertex: '+wall['id']+'/'+other['id'])
    require(isinstance(spec['areas'], list) and spec['areas'], 'Closed area faces required')
    incidence = {name: [] for name in walls}; ids = set(); polygons = []
    for area in spec['areas']:
        exact(area, 'id label kind boundary confidence', 'area')
        identity(area['id']); require(area['id'] not in ids, 'Duplicate area ID'); ids.add(area['id'])
        require(area['label'] is None or isinstance(area['label'], str) and area['label'], 'Area label must be text or unknown')
        require(area['kind'] in {'room', 'corridor', 'stairwell', 'void', 'unknown'} and area['confidence'] in CONFIDENCE, 'Unknown area kind or confidence')
        require(isinstance(area['boundary'], list) and len(area['boundary']) >= 3, 'Area needs a closed boundary loop')
        directed = []; used = set()
        for ref in area['boundary']:
            exact(ref, 'wall direction', 'directed boundary reference')
            require(ref['wall'] in walls and ref['wall'] not in used, 'Existing, non-repeated boundary required')
            require(type(ref['direction']) is int and ref['direction'] in (-1, 1), 'Boundary direction is +1 or -1')
            used.add(ref['wall']); wall = walls[ref['wall']]
            pair = (wall['start'], wall['end']) if ref['direction'] == 1 else (wall['end'], wall['start'])
            directed.append(pair); incidence[ref['wall']].append((area['id'], ref['direction']))
        require(all(a[1] == b[0] for a, b in zip(directed, directed[1:]+directed[:1])), 'Area boundary is not closed and ordered: '+area['id'])
        require(len({a[0] for a in directed}) == len(directed), 'Area loop repeats a vertex')
        points = area_points(spec, area)
        require(signed_area(points) > 0, 'Area boundary must be counterclockwise and nonzero: '+area['id'])
        polygons.append((area['id'], points))
    for name, users in incidence.items():
        require(len(users) <= 2, 'Boundary belongs to more than two areas: '+name)
        require(len(users) != 2 or users[0][1] == -users[1][1], 'Shared boundary must have opposite directions: '+name)
    for index, (name, polygon) in enumerate(polygons):
        for other, points in polygons[index+1:]:
            require(not any(point_membership(p, polygon) == 1 for p in points) and not any(point_membership(p, points) == 1 for p in polygon), 'Area interiors overlap: '+name+'/'+other)
    require(isinstance(spec['openings'], list), 'Opening list required')
    intervals = {}; ids = set()
    for opening in spec['openings']:
        exact(opening, 'id wall interval kind confidence connection', 'opening')
        identity(opening['id']); require(opening['id'] not in ids, 'Duplicate opening ID'); ids.add(opening['id'])
        require(opening['wall'] in walls and walls[opening['wall']]['kind'] != 'open_boundary', 'Opening needs a wall or uncertain wall')
        interval = opening['interval']; require(isinstance(interval, list) and len(interval) == 2, 'Opening interval required')
        for value in interval: finite(value)
        require(0 <= interval[0] < interval[1] <= 1, 'Opening lies outside wall or has zero width')
        require(opening['kind'] in {'door', 'window', 'unknown'} and opening['confidence'] in CONFIDENCE and opening['connection'] in {'observed', 'uncertain'}, 'Unknown opening interpretation')
        previous = intervals.setdefault(opening['wall'], [])
        require(all(interval[1] <= a or b <= interval[0] for a, b in previous), 'Overlapping openings on one wall')
        previous.append(interval)
    return spec


def load(path=SOURCE):
    path = Path(path).resolve(); raw = path.read_bytes(); spec = json.loads(raw)
    validate(spec); sha = hashlib.sha256(raw).hexdigest()
    require(digest(path) == sha, 'Relative plan changed while loading')
    spec['_source'] = {'path': str(path), 'sha256': sha}
    return spec


def topology(spec):
    validate(spec)
    incidence = {wall['id']: [] for wall in spec['walls']}
    for area in spec['areas']:
        for ref in area['boundary']: incidence[ref['wall']].append(area['id'])
    connections = [{'kind': 'open_boundary', 'wall': wall['id'], 'areas': incidence[wall['id']], 'passable': None} for wall in spec['walls'] if wall['kind'] == 'open_boundary' and len(incidence[wall['id']]) == 2]
    connections += [{'kind': opening['kind'], 'opening': opening['id'], 'wall': opening['wall'], 'areas': incidence[opening['wall']], 'connection': opening['connection'], 'passable': None} for opening in spec['openings'] if opening['kind'] != 'window']
    return {'connections': connections, 'unreferenced_walls': [name for name, users in incidence.items() if not users], 'metric_scale_known': False, 'robot_navigation_qualified': False}


def wall_metrics(spec):
    validate(spec)
    return {wall['id']: {'length_relative': math.dist(spec['vertices'][wall['start']], spec['vertices'][wall['end']]), 'length_mm': None} for wall in spec['walls']}


def metric_geometry(spec):
    validate(spec)
    raise ValueError('Metric geometry is unknown: calibration is null; visualization scale is not calibration')


def parameters(spec, overrides=None):
    inherited = {name: definition['expression'] for name, definition in spec.get('parameters', {}).items()} if '_plan' in spec else {}
    values = {**DEFAULTS, **inherited, **(overrides or {})}
    require(not set(values)-{'display_scale', *DEFAULTS}, 'Unknown display parameter')
    require('display_scale' in values, 'An explicit arbitrary display_scale is required; this is not a metric scale')
    for value in values.values(): require(finite(value) > 0, 'Positive display parameter required')
    return values


def cases(spec):
    return [{'id': 'overview'}]


def materialize(spec, case_id):
    require(case_id == 'overview', 'Only a static relative overview is implemented')
    return copy.deepcopy(spec)


def native_spec(spec, p):
    return {'id': spec['id'], 'status': 'Relative schematic visualization; arbitrary display millimetres, no metric building dimensions',
            'parameters': {name: {'expression': value, 'unit': 'mm', 'range': [value, value], 'description': 'Arbitrary visualization only; not a measured building dimension'} for name, value in p.items()}, '_plan': spec}


def preview(spec, display_scale_mm_per_unit, wall_height_display_mm=50, wall_thickness_display_mm=3, floor_depth_display_mm=1):
    p = parameters(spec, {'display_scale': display_scale_mm_per_unit, 'display_height': wall_height_display_mm, 'display_thickness': wall_thickness_display_mm, 'display_floor_depth': floor_depth_display_mm})
    return {'spec': native_spec(spec, p), 'parameters': p}


def _plan(spec):
    return spec.get('_plan', spec)


def _strip(a, b, left, right, half_width):
    length = math.dist(a, b); nx, ny = -(b[1]-a[1])/length, (b[0]-a[0])/length
    start = [a[i]+left*(b[i]-a[i]) for i in (0, 1)]; end = [a[i]+right*(b[i]-a[i]) for i in (0, 1)]
    return [[f'({point[0]})*display_scale+({sign*nx})*({half_width})', f'({point[1]})*display_scale+({sign*ny})*({half_width})'] for point, sign in [(start, 1), (end, 1), (end, -1), (start, -1)]]


def numeric_shape(shape, p):
    result = copy.deepcopy(shape)
    if 'points' in result: result['points'] = [[evaluate(value, p) for value in point] for point in result['points']]
    for key in ('origin', 'size'):
        if key in result: result[key] = [evaluate(value, p) for value in result[key]]
    for key in ('offset', 'depth', 'height', 'radius'):
        if key in result: result[key] = evaluate(result[key], p)
    return result


def expanded(spec, p):
    spec = _plan(spec); validate(spec)
    result = {'id': spec['id'], 'status': 'Arbitrary display geometry only', 'parameters': native_spec(spec, p)['parameters'], 'components': [{'id': 'Display', 'grounded': True}], 'bodies': [], 'operations': [], 'joints': []}
    def prism(name, body, points, offset, depth, action='create'):
        result['operations'].append({'id': name, 'body': body, 'action': action, 'shape': {'kind': 'polygon_prism', 'plane': 'XY', 'points': points, 'offset': offset, 'depth': depth, 'fixed': True}})
    colors = {'room': '#dce8ec', 'corridor': '#f2dfad', 'stairwell': '#c8cedf', 'unknown': '#e7e3dc'}
    for area in spec['areas']:
        if area['kind'] in {'void', 'unknown'}: continue
        name = 'Area_'+area['id']; result['bodies'].append({'id': name, 'component': 'Display', 'role': 'relative_area_display', 'appearance': {'color': colors[area['kind']], 'opacity': 1}})
        prism(name+'_Profile', name, [[f'({x})*display_scale', f'({y})*display_scale'] for x, y in area_points(spec, area)], '-display_floor_depth', 'display_floor_depth')
    walls = {wall['id']: wall for wall in spec['walls']}
    for wall in spec['walls']:
        if wall['kind'] != 'wall': continue
        name = 'Wall_'+wall['id']; a, b = (spec['vertices'][wall[key]] for key in ('start', 'end'))
        result['bodies'].append({'id': name, 'component': 'Display', 'role': 'relative_wall_display', 'appearance': {'color': '#a0b5bf' if wall['kind'] == 'wall' else '#cfad72', 'opacity': .7}})
        prism(name+'_Profile', name, _strip(a, b, 0, 1, 'display_thickness/2'), 0, 'display_height')
    for opening in spec['openings']:
        wall = walls[opening['wall']]; a, b = (spec['vertices'][wall[key]] for key in ('start', 'end'))
        if wall['kind'] != 'wall' or opening['kind'] == 'unknown': continue
        sill = '.35*display_height' if opening['kind'] == 'window' else 0
        height = '.4*display_height' if opening['kind'] == 'window' else '.75*display_height'
        prism('Opening_'+opening['id'], 'Wall_'+opening['wall'], _strip(a, b, *opening['interval'], 'display_thickness*.6'), sill, height, 'cut')
    return result


def interfaces(spec, p):
    spec = _plan(spec); validate(spec); walls = {wall['id']: wall for wall in spec['walls']}; probes = []
    for opening in spec['openings']:
        wall = walls[opening['wall']]; a, b = (spec['vertices'][wall[key]] for key in ('start', 'end'))
        if wall['kind'] != 'wall' or opening['kind'] == 'unknown': continue
        length = math.dist(a, b); lo, hi = opening['interval']; width = (hi-lo)*length*p['display_scale']
        bottom = .35*p['display_height'] if opening['kind'] == 'window' else 0
        height = (.4 if opening['kind'] == 'window' else .75)*p['display_height']
        inset = min(width, height, p['display_thickness'])/10
        points = _strip(a, b, lo+inset/(length*p['display_scale']), hi-inset/(length*p['display_scale']), str(p['display_thickness']/2-inset))
        probes.append({'id': opening['id'], 'target_body': 'Wall_'+opening['wall'], 'kind': 'polygon_prism', 'points_mm': [[evaluate(v, p) for v in point] for point in points],
                       'offset_mm': bottom+inset, 'depth_mm': height-2*inset, 'display_inset_mm': inset, 'visualization_only': True})
    return {'opening_probes': probes, 'unmodeled_openings': [o['id'] for o in spec['openings'] if walls[o['wall']]['kind'] != 'wall' or o['kind'] == 'unknown'], 'topology': topology(spec), 'wall_metrics': wall_metrics(spec), 'metric_scale_known': False,
            'visualization_only': True, 'display_parameters': copy.deepcopy(p), 'real_wall_height_mm': None, 'real_wall_thickness_mm': None,
            'passability_qualified': False, 'hardware_executed': False, 'junction_overlap_expected': True}


def pose(spec, p, name=None):
    require(name in (None, 'overview'), 'Only a static overview is implemented')
    return {}


def validate_pose(source, values):
    require(source['joints'] == [] and values == {}, 'Relative overview has no motion channels')


def samples(spec, p): return [{'id': 'overview', 'values_mm': {}}]
def displacement(source, component, values):
    validate_pose(source, values); return [0, 0, 0]


def source_dependencies(spec):
    spec = _plan(spec)
    paths = [SCHEMA, Path(__file__), ROOT/'scripts/robot_spec.py', ROOT/'scripts/tube_carrier_model.py']
    if '_source' in spec: paths.insert(0, Path(spec['_source']['path']))
    return paths


def solidcraft_commands(spec, p):
    plan = _plan(spec)
    class Provider:
        SOURCE = Path(plan.get('_source', {}).get('path', __file__))
        expanded = staticmethod(expanded)
        pose = staticmethod(pose)
        samples = staticmethod(samples)
    commands = portable.solidcraft_commands(native_spec(plan, p), p, provider=Provider)
    for command in commands:
        if command['command'] == 'document.metadata.set':
            command['params']['values'] = {'org.solidcraftbot.relative-floorplan': {'plan_id': plan['id'], 'metric_scale_known': False, 'visualization_only': True, 'display_parameters': p}}
    return commands


def render_svg(spec):
    """Render only declared relative vectors/text; no images or external links."""
    spec = _plan(spec); validate(spec)
    points = list(spec['vertices'].values()); low = [min(p[i] for p in points) for i in (0, 1)]; high = [max(p[i] for p in points) for i in (0, 1)]
    scale = 900/max(high[i]-low[i] for i in (0, 1)); width = (high[0]-low[0])*scale+80; height = (high[1]-low[1])*scale+120
    def xy(point): return [40+(point[0]-low[0])*scale, 40+(high[1]-point[1])*scale]
    def line(a, b, color, stroke=2, dash=''):
        x, y = xy(a); u, v = xy(b)
        return f'<line x1="{x:.4f}" y1="{y:.4f}" x2="{u:.4f}" y2="{v:.4f}" stroke="{color}" stroke-width="{stroke}"'+(f' stroke-dasharray="{dash}"' if dash else '')+'/>'
    def label_anchor(polygon, text):
        # Polygon moments are invariant under added collinear T-junction nodes.
        twice_area = 2*signed_area(polygon)
        centroid = [sum((a[i]+b[i])*(a[0]*b[1]-b[0]*a[1]) for a, b in zip(polygon, polygon[1:]+polygon[:1]))/(3*twice_area) for i in (0, 1)]
        low = [min(p[i] for p in polygon) for i in (0, 1)]; high = [max(p[i] for p in polygon) for i in (0, 1)]
        edges = list(zip(polygon, polygon[1:]+polygon[:1]))
        def point_distance(point, a, b):
            delta = [b[i]-a[i] for i in (0, 1)]
            t = max(0, min(1, sum((point[i]-a[i])*delta[i] for i in (0, 1))/sum(v*v for v in delta)))
            return math.dist(point, [a[i]+t*delta[i] for i in (0, 1)])
        def clearance(center, half):
            x, y = center; w, h = half
            corners = [[x-w, y-h], [x+w, y-h], [x+w, y+h], [x-w, y+h]]
            if any(point_membership(corner, polygon) != 1 for corner in corners): return -1
            rectangle = list(zip(corners, corners[1:]+corners[:1]))
            for a, b in edges:
                for c, d in rectangle:
                    if side(a, b, c)*side(a, b, d) == -1 and side(c, d, a)*side(c, d, b) == -1: return -1
            return min([point_distance(corner, a, b) for corner in corners for a, b in edges] + [point_distance(vertex, a, b) for vertex in polygon for a, b in rectangle])
        # Conservative text envelope, including one SVG pixel of edge padding.
        # The bounded raster is only needed when the area centroid cannot fit.
        glyph_width = sum(.35 if char == '.' else .4 if char in ' ilI' else .9 if char in 'MW' else .65 for char in text)
        initial = min(13, max(7, (high[0]-low[0]-2.25)/max(1, glyph_width)))
        fonts = sorted({7, *[max(7, initial-.5*i) for i in range(14)]}, reverse=True)
        for font in fonts:
            half = [glyph_width*font/2+1, font*1.2/2+1]
            if any(2*half[i] >= high[i]-low[i] for i in (0, 1)): continue
            if clearance(centroid, half) > 1e-4: return centroid, font
            candidates = [[low[0]+(i+.5)*(high[0]-low[0])/24, low[1]+(j+.5)*(high[1]-low[1])/24] for j in range(24) for i in range(24)]
            best = max(candidates, key=lambda point: clearance(point, half))
            if clearance(best, half) > 1e-4: return best, font
        return None  # An unfit tiny label remains available in the area's title.
    result = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.4f} {height:.4f}" role="img">', '<title>Relative floorplan — approximate trace, no metric scale</title>', f'<rect width="{width:.4f}" height="{height:.4f}" fill="#f8fafb"/>']
    colors = {'room': '#dce8ec', 'corridor': '#f2dfad', 'stairwell': '#c8cedf', 'void': '#f8fafb', 'unknown': '#e7e3dc'}
    for area in spec['areas']:
        polygon = area_points(spec, area)
        coords = ' '.join(f'{x:.4f},{y:.4f}' for x, y in map(xy, polygon))
        text = area['label'] or area['id']; label = html.escape(text)
        result.append(f'<polygon points="{coords}" fill="{colors[area["kind"]]}"><title>{label}</title></polygon>')
        anchor = label_anchor(list(map(xy, polygon)), text)
        if anchor is not None:
            (x, y), font = anchor
            result.append(f'<text x="{x:.4f}" y="{y:.4f}" text-anchor="middle" dominant-baseline="central" font-family="sans-serif" font-size="{font:.2f}" fill="#263846">{label}</text>')
    walls = {wall['id']: wall for wall in spec['walls']}
    for wall in spec['walls']:
        a, b = (spec['vertices'][wall[key]] for key in ('start', 'end'))
        result.append(line(a, b, '#344d5b' if wall['kind'] == 'wall' else '#b17b37', 2.5, '' if wall['kind'] == 'wall' else '5 4'))
    for opening in spec['openings']:
        wall = walls[opening['wall']]; a, b = (spec['vertices'][wall[key]] for key in ('start', 'end'))
        lo, hi = ([a[i]+fraction*(b[i]-a[i]) for i in (0, 1)] for fraction in opening['interval'])
        result.append(line(lo, hi, '#f8fafb', 7))
        uncertain = opening['connection'] == 'uncertain' or opening['confidence'] == 'uncertain' or opening['kind'] == 'unknown'
        color = '#c38637' if uncertain else ('#277d9b' if opening['kind'] == 'window' else '#379368')
        result.append(line(lo, hi, color, 2.5, '' if opening['confidence'] == 'clear' and not uncertain else '3 2'))
    result.append(f'<text x="40" y="{height-40:.4f}" font-family="sans-serif" font-size="12" fill="#526471">Relative / approximate — no metric scale, heights or passability qualification</text>')
    result.append('</svg>')
    return '\n'.join(result)+'\n'
