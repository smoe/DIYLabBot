"""Source-driven vector proposal section; no photograph or CAD input."""
import argparse
import html
import math
from pathlib import Path

import building_stack as model


def number(value):
    return f'{value:g}'.replace('.', ',')


def _policy_panel(rows, sides, basement, stair, extent, text, rect):
    """A separate rule table, never a false physical section through the lift."""
    if basement['z_mm'] is not None:
        raise ValueError('The planned basement has no known elevation')
    names = {'outward': 'außen', 'inward': 'innen'}
    for row in [*rows, basement]:
        selected = row['door_sides']
        if not set(selected) <= set(names) or len(selected) != len(set(selected)):
            raise ValueError('Known, unique source-bound door sides required')
    result = [f'<g data-role="lift-door-policy" data-served-from="{html.escape(extent["from_level"], quote=True)}" data-served-to="{html.escape(extent["to_level"], quote=True)}">',
              rect(1090, 160, 335, 405, rx=10, fill='#fff3df', stroke='#d0a05b'),
              text(1110, 190, 'Bestandsaufzug · Türregel', 'policy-title'),
              text(1110, 214, f'{extent["display"]} · Tabelle, keine Lage', 'policy-small'),
              text(1110, 244, 'Ebene', 'policy-small'),
              text(1210, 244, 'Tür außen', 'policy-small'),
              text(1325, 244, 'Tür innen', 'policy-small')]
    for index, row in enumerate(rows):
        selected = row['door_sides']
        y = 274+index*28
        result.append(f'<g data-lift-stop="{html.escape(row["id"], quote=True)}" data-door-sides="{" ".join(selected)}">')
        result.append(text(1110, y, row['label'], 'policy-row'))
        for xpos, side in ((1245, 'outward'), (1360, 'inward')):
            result.append(text(xpos, y, '●' if side in selected else '–', 'policy-row', text_anchor='middle'))
        result.append('</g>')
    result.append('<path d="M 1110 372 H 1405" stroke="#dfc7a3"/>')
    result.append(f'<g data-lift-stop="{html.escape(basement["id"], quote=True)}" data-door-sides="{" ".join(basement["door_sides"])}" data-z-known="false">')
    result.append(text(1110, 396, basement['label'], 'policy-row'))
    for xpos, side in ((1245, 'outward'), (1360, 'inward')):
        result.append(text(xpos, 396, 'geplant' if side in basement['door_sides'] else '–', 'policy-small', text_anchor='middle'))
    result.append('</g>')
    result.append(text(1110, 421, f'{basement["id"]}: Höhe offen; keine Ebene gezeichnet.', 'policy-small'))
    result.append(text(1110, 446, '● Türseite im Modell, kein Öffnungszustand', 'policy-small'))
    for index, side in enumerate(('outward', 'inward')):
        result.append(text(1110, 473+index*24, f'{sides[side]["label"]} · {sides[side]["wall"]}', 'policy-small'))
    result.append(f'<g data-role="stair-extent" data-area="{html.escape(stair["area"], quote=True)}" data-z-known="false">')
    result.append(text(1110, 521, f'{stair["count"]} rechter Treppenkern · {stair["area"]}', 'policy-small'))
    result.append(text(1110, 545, f'{stair["planned_from"]} → {stair["planned_to"]} geplant · bis {stair["served_to"]}', 'policy-small'))
    result.append('</g>')
    result.append('</g>')
    return '\n'.join(result)


def _render(view):
    """Draw a schematic section from the evaluated stack interface."""
    levels = view['levels']
    clear = view['clear_height_mm']
    slab = view['slab_thickness_mm']
    pitch = view['floor_pitch_mm']
    lower = min(level['slab_bottom_mm'] for level in levels)
    roof = view['roof']; barrel = roof['barrel']; profile = barrel['profile_points_mm']
    if (barrel['axis'] != 'X' or barrel['profile_axis'] != 'Y' or len(profile) < 3 or any(len(point) != 2 for point in profile)
            or any(type(value) not in (int, float) or not math.isfinite(value) for point in profile for value in point)
            or not min(point[0] for point in profile) < barrel['center_cross_mm'] < max(point[0] for point in profile)
            or roof['slab_bottom_mm'] != levels[-1]['clear_top_mm']
            or roof['slab_top_mm'] != roof['roof_z_mm']
            or abs(roof['slab_top_mm']-roof['slab_bottom_mm']-slab) > 1e-6):
        raise ValueError('Source-derived roof profile above the last clear ceiling required')
    upper = max(barrel['crown_z_mm'], roof['roof_z_mm']+roof['guard']['height_mm'])
    xlow, xhigh = view['y_bounds_mm']
    atrium_left, atrium_right = view['atrium_y_bounds_mm']
    footprint = barrel['footprint_points_mm']
    if len(footprint) < 3 or any(len(point) != 2 for point in footprint) or any(type(v) not in (int, float) or not math.isfinite(v) for point in footprint for v in point):
        raise ValueError('Source-derived XY glazing footprint required')
    glass_left, glass_right = min(p[1] for p in footprint), max(p[1] for p in footprint)
    corridors = roof['covered_corridor_area_ids']
    if len(corridors) != 4 or len(set(corridors)) != 4 or not set(corridors) <= set(roof['covered_area_ids']):
        raise ValueError('All four distinct source corridors must be covered by glazing')
    marker = view['concept_marker']
    values = [clear, slab, pitch, lower, upper, xlow, xhigh, atrium_left, atrium_right,
              marker['offset_mm'], marker['depth_mm']]
    if (not levels or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
            or min(clear, slab, pitch, upper-lower, xhigh-xlow, marker['depth_mm']) <= 0
            or abs(pitch-clear-slab) > 1e-6
            or not xlow < glass_left <= atrium_left < atrium_right <= glass_right < xhigh):
        raise ValueError('Consistent evaluated stack geometry required')
    yscale = 590/(upper-lower)
    xscale = 850/(xhigh-xlow)
    def x(value): return 210+(value-xlow)*xscale
    def y(value): return 750-(value-lower)*yscale
    def esc(value): return html.escape(str(value), quote=True)
    def rect(left, top, width, height, **attrs):
        attributes = ' '.join(f'{key.rstrip("_").replace("_", "-")}="{esc(value)}"' for key, value in attrs.items())
        return f'<rect x="{left:.3f}" y="{top:.3f}" width="{width:.3f}" height="{height:.3f}" {attributes}/>'
    def text(left, top, value, cls='body', **attrs):
        attributes = ' '.join(f'{key.rstrip("_").replace("_", "-")}="{esc(value)}"' for key, value in attrs.items())
        return f'<text x="{left:.3f}" y="{top:.3f}" class="{cls}" {attributes}>{esc(value)}</text>'
    def dimension(left, bottom, top, label, role):
        a, b = y(bottom), y(top)
        return (f'<g data-role="{role}" data-from-mm="{bottom:g}" data-to-mm="{top:g}">'
                f'<path d="M {left-8} {a:.3f} H {left+8} M {left} {a:.3f} V {b:.3f} M {left-8} {b:.3f} H {left+8}" class="dimension"/>'
                +text(left+20, (a+b)/2, label, 'dimension-label', transform=f'rotate(-90 {left+20} {(a+b)/2:.3f})', text_anchor='middle')+'</g>')
    result = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="1000" viewBox="0 0 1500 1000" role="img" aria-labelledby="title desc" data-horizontal-axis="Y">',
        '<title id="title">Atriumprinzip und Aufzugtürregel · schematischer Gebäudeentwurf</title>',
        '<desc id="desc">Schematische Y/Z-Prinzipprojektion, kein ortsfester Gebäudeschnitt. Eigener EG-Plan und drei referenzierte Obergeschosse. Unten ist der Atriumboden geschlossen. Ein geschlossenes Glasgewölbe bedeckt Atrium und alle vier umlaufenden Flure; ihre Böden bleiben erhalten. Die Aufzugtabelle beschreibt Türseiten, keine räumliche Lage.</desc>',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 Z" fill="#167ca6"/></marker></defs>',
        '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#24394a}.title{font-size:34px;font-weight:700}.subtitle{font-size:19px;fill:#607383}.body{font-size:18px}.small{font-size:16px;fill:#607383}.level{font-size:21px;font-weight:700}.dimension-label{font-size:17px;fill:#526978}.dimension{fill:none;stroke:#718897;stroke-width:1.5}.slab{fill:#81939e}.edge{fill:none;stroke:#9bacb5;stroke-width:2}.blue{fill:#167ca6}.tag{font-size:18px;fill:#167ca6;font-weight:700}.policy-title{font-size:19px;font-weight:700;fill:#906025}.policy-small{font-size:13px;fill:#795c38}.policy-row{font-size:16px;fill:#795522}</style>',
        '<rect width="1500" height="1000" fill="#fbfcfd"/>',
        text(75, 68, 'Vertikaler Laboraustausch', 'title'),
        text(75, 103, f'{len(levels)} Ebenen · Y/Z-Prinzipprojektion und Aufzugtürregel · keine Bauaufnahme', 'subtitle'),
        '<path d="M 75 126 H 1425" stroke="#dbe3e8"/>',
    ]
    # XY is deliberately schematic; only the source-relative atrium proportions
    # are reused. The vertical geometry follows the declared height assumptions.
    a, b = x(atrium_left), x(atrium_right)
    for level in levels:
        identity = esc(level['id'])
        base, ceiling = level['z_mm'], level['clear_top_mm']
        floor_bottom, floor_top = level['slab_bottom_mm'], level['slab_top_mm']
        result.append(f'<g data-level="{identity}" data-z-mm="{base:g}">')
        result.append(rect(x(xlow), y(ceiling), a-x(xlow), y(base)-y(ceiling), fill='#edf2f5', data_role='template-room'))
        result.append(rect(b, y(ceiling), x(xhigh)-b, y(base)-y(ceiling), fill='#edf2f5', data_role='template-room'))
        if level['id'] == 'KG':
            result.append(rect(a, y(ceiling), b-a, y(base)-y(ceiling), fill='#edf2f5', data_role='basement-room'))
        for left, right in ((x(xlow), a), (b, x(xhigh))):
            result.append(rect(left, y(floor_top), right-left, y(floor_bottom)-y(floor_top), class_='slab', data_role='slab'))
        if level['atrium_floor_filled']:
            result.append(rect(a, y(floor_top), b-a, y(floor_bottom)-y(floor_top), class_='slab', data_role='atrium-floor'))
        elif level['id'] == 'KG':
            result.append(rect(a, y(floor_top), b-a, y(floor_bottom)-y(floor_top), class_='slab', data_role='basement-floor'))
        else:
            result.append(f'<path d="M {a:.3f} {y(base):.3f} H {b:.3f}" stroke="#a8c7d6" stroke-dasharray="3 5" data-role="atrium-opening"/>')
        result.append(text(75, y(base)-10, 'KG' if level['id'] == 'KG' else level['label'], 'level'))
        result.append(text(75, y(base)+15, f'{"+" if base >= 0 else ""}{number(base/1000)} m*', 'small'))
        result.append('</g>')
    for left, right in ((x(xlow), x(glass_left)), (x(glass_right), x(xhigh))):
        result.append(rect(left, y(roof['slab_top_mm']), right-left, y(roof['slab_bottom_mm'])-y(roof['slab_top_mm']), class_='slab', data_role='roof-slab'))
    curve = ' '.join(('M' if index == 0 else 'L')+f'{x(point[0]):.1f} {y(point[1]):.1f}' for index, point in enumerate(profile))
    result.append(f'<path d="{curve}" fill="none" stroke="#3987a9" stroke-width="4" data-role="glass-roof-profile" data-profile-axis="Y" data-roof-z-mm="{roof["roof_z_mm"]:g}" data-crown-z-mm="{barrel["crown_z_mm"]:g}"/>')
    eaves = ' '.join(f'M{x(point[0]):.1f} {y(roof["roof_z_mm"]):.1f}V{y(point[1]):.1f}' for point in (profile[0], profile[-1]))
    result.append(f'<path d="{eaves}" fill="none" stroke="#3987a9" stroke-width="2" data-role="glass-roof-eaves"/>')
    cx = [point[1] for point in marker['points_mm']]
    left, right = x(min(cx)), x(max(cx))
    top, bottom = y(marker['offset_mm']+marker['depth_mm']), y(marker['offset_mm'])
    result.append(rect(left, top, right-left, bottom-top, fill='#2497c7', fill_opacity='.12', stroke='#248bb5', stroke_dasharray='7 5', data_role='concept-volume'))
    for fraction, reverse in ((.35, False), (.65, True)):
        xpos = left+fraction*(right-left)
        start, end = (bottom-30, top+30) if not reverse else (top+30, bottom-30)
        result.append(f'<path d="M {xpos:.3f} {start:.3f} V {end:.3f}" fill="none" stroke="#167ca6" stroke-width="5" marker-end="url(#arrow)" data-role="exchange-arrow"/>')
    result.append(text(x(barrel['center_cross_mm']), 144, f'Glas über Atrium und {len(corridors)} Fluren', 'tag', text_anchor='middle'))
    circulation = view['circulation']
    elevator = circulation['elevator']
    if set(elevator['doors_by_level']) != {level['id'] for level in levels}:
        raise ValueError('Door policy must cover exactly the drawn storeys')
    if elevator['deferred_stops']:
        deferred = elevator['deferred_stops']
        if len(deferred) != 1 or deferred[0]['id'] in elevator['doors_by_level'] or deferred[0]['status'] != 'awaiting_plan':
            raise ValueError('One separately deferred basement stop required')
        planned = deferred[0]
        rows = [{'id': level['id'], 'label': level['label'], 'door_sides': elevator['doors_by_level'][level['id']]} for level in reversed(levels)]
        basement = {'id': planned['id'], 'label': planned['label'], 'z_mm': planned['elevation_mm'], 'door_sides': planned['sides']}
        stairs = circulation['stairs']
        if len(stairs) != 1:
            raise ValueError('Exactly one right stair core required')
        stair = stairs[0]; extent = elevator['served_extent']
        if (stair['classification'] != 'internal' or stair['served_extent'] != extent
                or extent['from_level'] != basement['id'] or extent['to_level'] != levels[-1]['id']):
            raise ValueError('Separate lift and stair must declare the same source-served extent')
        links = stair['planned_connectors']
        if (len(links) != 1 or links[0]['from_level'] != basement['id'] or links[0]['to_level'] != levels[0]['id']
                or links[0]['status'] != 'awaiting_plan' or any(links[0][key] is not None for key in ('z0_mm', 'z1_mm', 'body_id'))):
            raise ValueError('Basement stair link must remain planned without elevation or geometry')
        labels = {level['id']: level['label'] for level in levels}
        stair_note = {'count': len(stairs), 'area': stair['area'], 'planned_from': links[0]['from_level'], 'planned_to': labels[links[0]['to_level']], 'served_to': labels[extent['to_level']]}
        extent_note = {**extent, 'display': f'{extent["from_level"]} → {labels[extent["to_level"]]}'}
        result.append(_policy_panel(rows, elevator['sides'], basement, stair_note, extent_note, text, rect))
    else:
        deferred = elevator['deferred_stops']
        rows = [{'id': level['id'], 'label': level['label'], 'door_sides': elevator['doors_by_level'][level['id']]} for level in reversed(levels)]
        stairs = circulation['stairs']
        if len(stairs) != 1:
            raise ValueError('Exactly one right stair core required')
        stair = stairs[0]; extent = elevator['served_extent']
        labels = {level['id']: level['label'] for level in levels}
        if deferred:
            raise ValueError('The current section requires all basement stops to be modeled')
        if levels[0]['id'] != 'KG' or stair['planned_connectors']:
            raise ValueError('Basement floor and its stair connector must be modeled')
        extent_note = {**extent, 'display': f'{extent["from_level"]} → {labels[extent["to_level"]]}'}
        panel = [rect(1090, 160, 335, 405, rx=10, fill='#fff3df', stroke='#d0a05b'),
                 text(1110, 190, 'Bestandsaufzug · Türregel', 'policy-title')]
        names = {'outward': 'außen', 'inward': 'innen'}
        for index, row in enumerate(rows):
            panel.append(f'<g data-lift-stop="{html.escape(row["id"], quote=True)}" data-door-sides="{" ".join(row["door_sides"])}" data-elevation-basis="assumed">')
            panel.append(text(1110, 230+index*32, row['label']+' · '+', '.join(names[side] for side in row['door_sides']), 'policy-small'))
            panel.append('</g>')
        panel.append(text(1110, 425, 'KG-Höhe vorläufig angenommen', 'policy-small'))
        panel.append(text(1110, 450, 'Türseite, kein Öffnungszustand', 'policy-small'))
        panel.append('<g data-role="stair-extent" data-area="'+html.escape(stair['area'], quote=True)+'">')
        panel.append(text(1110, 490, f'1 rechter Treppenkern · {stair["area"]}', 'policy-small'))
        panel.append('</g>')
        panel.append(text(1110, 520, 'Außentreppe EG → Dach', 'policy-small'))
        result.append('<g data-role="lift-door-policy">'+'\n'.join(panel)+'</g>')
    external = circulation['external_stairs']
    if (len(external) != 1 or external[0]['classification'] != 'external_metal'
            or external[0]['served_extent'] != {'from_level': next((level['id'] for level in levels if level['id'] == 'EG'), levels[0]['id']), 'to_level': 'ROOF'}):
        raise ValueError('One separately sourced external metal stair from roof to EG required')
    first = levels[0]
    result.append(dimension(1130, first['z_mm'], first['clear_top_mm'], f'{number(clear/1000)} m lichte Höhe*', 'clear-height'))
    result.append(dimension(1260, first['z_mm'], next((level for level in levels if level['z_mm'] > first['z_mm']), levels[1])['z_mm'], f'{number(pitch/1000)} m Geschossteilung*', 'floor-pitch'))
    if view.get('exterior'):
        grade=view['exterior']['grade_z_mm']; ground_y=y(grade)
        result.append(rect(180, ground_y-2, 25, 2, fill='#559447', data_role='lawn-surface'))
        result.append(rect(1065, ground_y-2, 20, 2, fill='#559447', data_role='lawn-surface'))
        result.append(f'<path d="M180 {ground_y:.3f}H1085" stroke="#559447" stroke-width="3" data-role="terrain-grade"/>')
        result.append(text(250, ground_y+24, 'Gelände ±0 m*', 'small'))
    result.append(text(210, 786, 'EG: Atriumboden geschlossen. Darüber: Öffnungen der gemeinsamen Vorlage.', 'small'))
    result.append('<rect x="75" y="805" width="1350" height="180" rx="12" fill="#edf2f5"/>')
    result.append(text(95, 832, f'* Annahmen: lichte Höhe {number(clear/1000)} m · Platte {number(slab)} mm · Teilung {number(pitch/1000)} m.', 'body'))
    result.append(text(95, 858, 'Breite schematisch; XY nicht kalibriert. Raumkennungen sind Vorlagenreferenzen, keine bestätigten Räume anderer Ebenen.', 'small'))
    result.append(text(95, 884, 'Blau: Konzeptbereich und Austauschpfeile. Transporttechnik, Tragwerk, Übergaben und Sicherheit sind nicht qualifiziert.', 'small'))
    result.append(text(95, 910, f'{len(stairs)} interner Treppenkern: {extent_note["display"]} · {len(external)} äußere Metalltreppe: Dach → {labels[external[0]["served_extent"]["from_level"]]}', 'small', data_role='separate-stair-extents'))
    result.append(text(95, 936, f'Quellen: EG {view["ground_floor"]["id"]} · Obergeschosse {view["template_id"]}', 'small'))
    basement_note = 'Kellerhöhe angenommen' if levels[0]['id'] == 'KG' else 'Keller nicht modelliert'
    result.append(text(95, 960, f'Dachgeländer {number(roof["guard"]["height_mm"])} mm und Glasgewölbe: Konzept · {basement_note} · keine Schutzwirkung', 'small'))
    result.append('</svg>')
    return '\n'.join(result)+'\n'


def render_svg(spec=None):
    """Load the stack once, then render only its evaluated public interface."""
    if spec is None:
        spec = model.load()
    return _render(model.interfaces(spec, model.parameters(spec)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    svg = render_svg()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg, encoding='utf-8')
    print(str(args.out))


if __name__ == '__main__':
    main()
