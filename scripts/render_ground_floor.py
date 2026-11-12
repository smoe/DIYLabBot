"""Compact EG vectors from the resolved shared graph, never an original image."""
import argparse
from collections import Counter
import html
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import relative_floorplan as floor

BUDGET = 12000


def compact_svg(raw):
    """Batch identical paints; round preview positions by at most 0.05 units.

    The validated faces have disjoint interiors. Walls precede opening masks,
    then their colored annotations; source labels retain their shared anchors.
    Source coordinates and native geometry are never changed.
    """
    tree = ET.fromstring(raw)
    allowed = {'svg', 'title', 'rect', 'polygon', 'text', 'line'}
    for element in tree.iter():
        if (element.tag.rsplit('}', 1)[-1] not in allowed or any('href' in key.lower() for key in element.attrib)
                or any('url(' in value.lower() for value in element.attrib.values())):
            raise ValueError('Only self-contained plan vectors and escaped text are supported')
    def esc(value): return html.escape(str(value), quote=True)
    def n(value, places=1):
        value = float(value)
        if not math.isfinite(value): raise ValueError('Finite vector coordinate required')
        return f'{value:.{places}f}'.rstrip('0').rstrip('.') if value else '0'
    styles = {}; faces = {}; layers = {'walls': {}, 'masks': {}, 'openings': {}}
    labels = []; rectangles = []; headings = []; mask_seen = False
    text_sizes = Counter(element.get('font-size') for element in tree if element.tag.rsplit('}', 1)[-1] == 'text')
    default_size = n(text_sizes.most_common(1)[0][0], 2) if text_sizes else '13'
    def style(values, prefix):
        key = tuple(sorted(values.items()))
        if key not in styles:
            styles[key] = prefix+str(len(styles))
        return styles[key]
    def title(element):
        return '<title>'+esc(element.text or '')+'</title>'
    def segments(points, closed=False):
        start = points[0]; result = ['M'+start[0]+' '+start[1]]; previous = start
        for point in points[1:]:
            result.append('H'+point[0] if point[1] == previous[1] else ('V'+point[1] if point[0] == previous[0] else 'L'+point[0]+' '+point[1]))
            previous = point
        return ''.join(result)+('Z' if closed else '')
    for element in tree:
        tag = element.tag.rsplit('}', 1)[-1]
        attrs = dict(element.attrib)
        if tag == 'line':
            x0, y0, x1, y1 = [n(attrs.pop(key)) for key in ('x1', 'y1', 'x2', 'y2')]
            if set(attrs)-{'stroke', 'stroke-width', 'stroke-dasharray'}:
                raise ValueError('Unsupported vector stroke attribute')
            name = style({'fill': 'none', **attrs}, 'l')
            mask = float(attrs.get('stroke-width', 0)) == 7
            if mask: mask_seen = True
            layer = 'masks' if mask else ('openings' if mask_seen else 'walls')
            layers[layer].setdefault(name, []).append(segments([[x0, y0], [x1, y1]]))
            continue
        if tag == 'title':
            headings.append(title(element))
        elif tag == 'polygon':
            points = [[n(v) for v in point.split(',')] for point in attrs.pop('points').split()]
            name = style(attrs, 'f')
            faces.setdefault(name, []).append(segments(points, True))
        elif tag == 'text':
            x, y = n(attrs.pop('x')), n(attrs.pop('y'))
            size = n(attrs.pop('font-size'), 2)
            name = style(attrs, 't')
            font = '' if size == default_size else f' font-size="{size}"'
            labels.append(f'<text x="{x}" y="{y}"{font} class="{name}">{esc(element.text or "")}</text>')
        elif tag == 'rect':
            other = ' '.join(f'{key}="{esc(n(value) if key in {"x", "y", "width", "height"} else value)}"' for key, value in attrs.items())
            rectangles.append('<rect '+other+'/>')
        else:
            raise ValueError('Unsupported nested vector container')
    def batch(name, values):
        return '<g data-layer="'+name+'">'+''.join(f'<path class="{key}" d="{"".join(paths)}"/>' for key, paths in values.items())+'</g>'
    css = ''.join('.'+name+'{'+(';'.join(key+':'+value for key, value in values))+'}' for values, name in styles.items())
    result = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{esc(tree.get("viewBox"))}" role="img" font-size="{default_size}">'
              +''.join(headings)+'<style>'+css+'</style>'+''.join(rectangles)+batch('faces', faces)
              +'<g data-layer="labels">'+''.join(labels[:-1])+'</g>'
              +''.join(batch(name, values) for name, values in layers.items())+''.join(labels[-1:])+'</svg>\n')
    if len(result.encode('utf-8')) > BUDGET:
        raise ValueError('Ground-floor vector exceeds the 12 KB documentation budget')
    return result


def render_svg(spec=None):
    """Resolve the EG source once; reuse the common plan geometry and anchors."""
    if spec is None:
        import ground_floor_model
        spec = ground_floor_model.load()
    raw = floor.render_svg(spec)
    tree = ET.fromstring(raw)
    tree[0].text = 'EG · relative Nachzeichnung ohne metrische Kalibrierung'
    tree[-1].text = 'Relative Nachzeichnung · Maßstab unbekannt · keine Wege- oder Sicherheitsfreigabe'
    _complete_labels(tree)
    return compact_svg(ET.tostring(tree, encoding='unicode'))


def _complete_labels(tree):
    """Give an unfit tiny face a source-derived callout in empty canvas space."""
    ns = '{http://www.w3.org/2000/svg}'
    children = list(tree)
    polygons = [[[float(v) for v in p.split(',')] for p in e.get('points').split()]
                for e in children if e.tag == ns+'polygon']
    _, _, width, height = map(float, tree.get('viewBox').split())
    for index, element in enumerate(children):
        if element.tag != ns+'polygon' or children[index+1].tag == ns+'text': continue
        label = element.find(ns+'title').text
        polygon = [[float(v) for v in p.split(',')] for p in element.get('points').split()]
        low = [min(p[i] for p in polygon) for i in (0, 1)]; high = [max(p[i] for p in polygon) for i in (0, 1)]
        half = [len(label)*7*.65/2+1, 7*1.2/2+1]
        center = [(a+b)/2 for a, b in zip(low, high)]
        candidates = [([center[0], low[1]-gap], [center[0], low[1]]) for gap in (12, 24, 40, 60)]
        candidates += [([center[0], high[1]+gap], [center[0], high[1]]) for gap in (12, 24, 40, 60)]
        def clear(point):
            x, y = point; w, h = half
            corners = [[x-w, y-h], [x+w, y-h], [x+w, y+h], [x-w, y+h]]
            if any(not 1 < p[0] < width-1 or not 1 < p[1] < height-60 for p in corners): return False
            edges = list(zip(corners, corners[1:]+corners[:1]))
            for other in polygons:
                if any(floor.point_membership(p, other) != -1 for p in corners): return False
                if any(floor.point_membership(p, corners) != -1 for p in other): return False
                for a, b in edges:
                    for c, d in zip(other, other[1:]+other[:1]):
                        if floor.side(a, b, c)*floor.side(a, b, d) == -1 and floor.side(c, d, a)*floor.side(c, d, b) == -1: return False
            return True
        match = next(((point, anchor) for point, anchor in candidates if clear(point)), None)
        if match is None: raise ValueError('A source label has no readable common anchor or exterior callout')
        point, anchor = match
        line_end = [point[0], point[1]+math.copysign(half[1]+1, anchor[1]-point[1])]
        line = ET.Element(ns+'line', dict(zip(('x1', 'y1', 'x2', 'y2'), map(str, anchor+line_end))), stroke='#607383', **{'stroke-width': '.8'})
        text = ET.Element(ns+'text', {'x': str(point[0]), 'y': str(point[1]), 'text-anchor': 'middle',
                                    'dominant-baseline': 'central', 'font-family': 'sans-serif', 'font-size': '7', 'fill': '#263846'})
        text.text = label
        position = list(tree).index(element)+1
        tree.insert(position, line); tree.insert(position+1, text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args(argv)
    if args.source is None:
        svg = render_svg()
    else:
        import ground_floor_model
        svg = render_svg(ground_floor_model.load(args.source))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg, encoding='utf-8')
    print(str(args.out))


if __name__ == '__main__':
    main()
