"""Shared illustrative open-metal guards from one declared building profile.

Horizontal members retain the existing atrium construction. Inclined members
support the current straight-X stair recipe through portable XZ prisms. This
geometry is not a structural, clearance or fall-protection qualification.
"""
import math
import re

import relative_floorplan as floor


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_profile(profile):
    fields = {'height_mm', 'post_mm', 'bar_mm', 'bar_fractions',
              'max_post_spacing_mm', 'color'}
    require(isinstance(profile, dict) and set(profile) == fields,
            'Explicit shared guard profile required')
    for name in ('height_mm', 'post_mm', 'bar_mm', 'max_post_spacing_mm'):
        value = profile[name]
        require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                'Positive finite guard dimension required: '+name)
    require(profile['bar_mm'] < profile['height_mm']
            and profile['post_mm'] < profile['max_post_spacing_mm'],
            'Guard handrail and post spacing must fit the profile')
    fractions = profile['bar_fractions']
    require(isinstance(fractions, list) and fractions
            and all(type(value) in (int, float) and math.isfinite(value)
                    and 0 < value < 1 for value in fractions)
            and fractions == sorted(set(fractions)),
            'Unique ordered finite guard bar fractions required')
    require(isinstance(profile['color'], str)
            and re.fullmatch('#[0-9a-fA-F]{6}', profile['color']) is not None,
            'RGB guard appearance required')
    return profile


def profile_from_exterior(source):
    """Reference existing leading values without copying them into stair data."""
    profile = {name: source[key] for name, key in (
        ('height_mm', 'guard_height_mm'), ('post_mm', 'guard_post_mm'),
        ('bar_mm', 'guard_bar_mm'), ('max_post_spacing_mm', 'guard_max_post_spacing_mm'),
        ('color', 'frame_color'))}
    profile['bar_fractions'] = list(source['guard_bar_fractions'])
    return validate_profile(profile)


def compile_segment(profile, name, start, end, *, component,
                    role='concept_open_metal_balustrade_member',
                    post_registry=None, post_embed_mm=0, post_support_z=None):
    """Compile one horizontal or straight-X inclined guard segment.

    Post registry keys are private. Compatible shared corner posts are emitted
    once; later segments refer to their IDs. A failed segment leaves the caller's
    registry unchanged. Rail spacing follows the actual three-dimensional path.
    Optional post support receives an immutable pitchline point and returns the
    actual supporting surface Z; rail tops retain the declared pitchline height.
    """
    validate_profile(profile)
    require(all(isinstance(value, str)
                and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', value)
                for value in (name, component, role)), 'Stable guard identifiers required')
    for point in (start, end):
        require(isinstance(point, (list, tuple)) and len(point) == 3
                and all(type(value) in (int, float) and math.isfinite(value)
                        for value in point), 'Finite three-dimensional guard endpoints required')
    require(type(post_embed_mm) in (int, float) and math.isfinite(post_embed_mm)
            and post_embed_mm >= 0, 'Finite nonnegative post embed required')
    require(post_registry is None or isinstance(post_registry, dict),
            'Guard post registry must be a dictionary')
    require(post_support_z is None or callable(post_support_z),
            'Guard post support must be callable')
    dx, dy, dz = (end[i]-start[i] for i in (0, 1, 2))
    length = math.hypot(dx, dy)
    path_length = math.hypot(length, dz)
    require(math.isfinite(path_length) and length > 0,
            'Guard endpoints need a finite nonzero horizontal run')
    horizontal = dz == 0
    require(horizontal or dy == 0, 'Inclined guards currently require a straight-X stair run')
    u = [dx/length, dy/length]
    normal = [-u[1], u[0]]
    height, post, bar = (profile[key] for key in ('height_mm', 'post_mm', 'bar_mm'))
    count = math.ceil(path_length/profile['max_post_spacing_mm'])
    bodies, operations, members, posts = [], [], [], []
    registry = None if post_registry is None else {key: list(value) for key, value in post_registry.items()}
    profile_key = (height, post, bar, tuple(profile['bar_fractions']),
                   profile['max_post_spacing_mm'], profile['color'])

    def footprint(along, run, thick):
        # This is deliberately the original atrium arithmetic and vertex order.
        points = [[start[j]+distance*u[j]+side*normal[j] for j in (0, 1)]
                  for distance, side in [(along, -thick/2), (along+run, -thick/2),
                                         (along+run, thick/2), (along, thick/2)]]
        if floor.signed_area(points) < 0:
            points.reverse()
        require(all(math.isfinite(value) for point in points for value in point)
                and floor.signed_area(points) > 0, 'Finite positive guard footprint required')
        return points

    def add(target, shape):
        bodies.append({'id': target, 'component': component, 'role': role,
                       'appearance': {'color': profile['color'], 'opacity': 1}})
        operations.append({'id': target+'_Profile', 'body': target,
                           'action': 'create', 'shape': shape})
        members.append(target)

    def xy_shape(points, z, depth):
        require(math.isfinite(z) and math.isfinite(depth) and depth > 0,
                'Finite positive guard member required')
        return {'kind': 'polygon_prism', 'plane': 'XY', 'points': points,
                'offset': z, 'depth': depth, 'fixed': True}

    def compatible(a, b):
        return all(any(all(math.isclose(p[i], q[i], rel_tol=0, abs_tol=1e-7)
                           for i in (0, 1)) for q in b) for p in a)

    def post_at(index):
        fraction = index/count
        # Exact endpoint declarations make shared stair corner identities stable.
        pitchline = list(start if index == 0 else end if index == count else
                         [start[i]+fraction*(end[i]-start[i]) for i in (0, 1, 2)])
        along = index*length/count-post/2
        points = footprint(along, post, post)
        z = start[2] if horizontal else pitchline[2]
        if post_support_z is None:
            support_z, base_z, top_z, post_height = z, z-post_embed_mm, z+height, height+post_embed_mm
        else:
            try:
                support_z = post_support_z(tuple(pitchline))
            except Exception as error:
                raise ValueError('Guard post support could not be evaluated') from error
            require(type(support_z) in (int, float) and math.isfinite(support_z),
                    'Finite numeric guard post support Z required')
            base_z, top_z = support_z-post_embed_mm, pitchline[2]+height
            post_height = top_z-base_z
        require(all(math.isfinite(value) for value in (base_z, top_z, post_height))
                and post_height > 0, 'Finite positive supported guard post height required')
        base = pitchline[:2]+[base_z]
        top = pitchline[:2]+[top_z]
        target = name+'_Post'+str(index)
        new = True
        if registry is not None:
            key = (component, role, profile_key, tuple(base), tuple(top))
            entries = registry.get(key, [])
            previous = next((entry for entry in entries if compatible(points, entry['footprint'])), None)
            if previous is not None:
                target, new = previous['body_id'], False
                members.append(target)
            else:
                add(target, xy_shape(points, base[2], post_height))
                registry.setdefault(key, []).append({'body_id': target, 'footprint': points})
        else:
            add(target, xy_shape(points, base[2], post_height))
        posts.append({'body_id': target, 'pitchline_mm': pitchline,
                      'support_z_mm': support_z, 'base_mm': base, 'top_mm': top, 'new': new})

    def rail(tag, shift, depth, thick, flat_z):
        target = name+'_'+tag
        if horizontal:
            add(target, xy_shape(footprint(-post/2, length+post, thick), flat_z, depth))
            return
        slope = dz/length
        points = [[start[0]+distance*u[0], start[2]+distance*slope+shift+vertical]
                  for distance, vertical in [(-post/2, 0), (length+post/2, 0),
                                             (length+post/2, depth), (-post/2, depth)]]
        if floor.signed_area(points) < 0:
            points.reverse()
        require(all(math.isfinite(value) for point in points for value in point)
                and floor.signed_area(points) > 0, 'Finite positive inclined guard profile required')
        add(target, {'kind': 'polygon_prism', 'plane': 'XZ', 'points': points,
                     'offset': start[1]-thick/2, 'depth': thick, 'fixed': True})

    # Vertical caps preserve the profile section normal to the inclined path.
    rail_depth = bar if horizontal else bar*path_length/length
    require(math.isfinite(rail_depth) and rail_depth < height,
            'Inclined handrail section must fit the declared guard height')
    post_at(0)
    rail('Handrail', height-rail_depth, rail_depth, post, start[2]+height-bar)
    for index in range(1, count+1):
        post_at(index)
    for index, fraction in enumerate(profile['bar_fractions']):
        rail('Bar'+str(index), height*fraction, rail_depth, bar, start[2]+height*fraction)
    if post_registry is not None:
        post_registry.update(registry)
    return {'bodies': bodies, 'operations': operations,
            'interface': {'body_ids': members, 'posts': posts,
                          'start_mm': list(start), 'end_mm': list(end),
                          'bar_section_mm': bar,
                          'bar_section_basis': 'normal_to_pitchline'}}
