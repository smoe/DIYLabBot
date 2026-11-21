"""Source room, doorway and lift regions for the BF01 zone speed contract."""
import math

from building_fleet_navigation import point_in_polygon
from building_fleet_sim import point_segment_distance


def point_distance(point, polygon):
    if len(polygon)>2 and point_in_polygon(point,polygon):return 0.
    return min(point_segment_distance(point,a,b)for a,b in zip(polygon,polygon[1:]+polygon[:1]))


def source_regions(navigation, level):
    """Return immutable source geometry, without live occupancy or flags."""
    regions=[]
    for area in navigation.topological[level]['plan']['areas']:
        if area['kind']=='room':regions.append({'kind':'room','id':area['id'],
            'polygon_mm':navigation.polygons[level][area['id']]})
    for portal in navigation.portals[level]:
        if not portal.get('opening'):continue
        centre,tangent=portal['centre_mm'],portal['tangent'];half=portal['opening_width_mm']/2
        regions.append({'kind':'door','id':portal['opening'],
            'polygon_mm':[[centre[k]+sign*tangent[k]*half for k in range(2)]for sign in(-1,1)]})
    elevator=navigation.mesh.manifest['elevator'];bounds=elevator['cabin_bounds_mm']
    for port in elevator['ports']:
        if not port['active']or port['level_id']!=level:continue
        lo=[min(bounds['min'][0],port['exit_eye_mm'][0]),bounds['min'][1]]
        hi=[max(bounds['max'][0],port['exit_eye_mm'][0]),bounds['max'][1]]
        regions.append({'kind':'lift','id':port['id'],
            'polygon_mm':[[lo[0],lo[1]],[hi[0],lo[1]],[hi[0],hi[1]],[lo[0],hi[1]]]})
    return regions


def progress_windows(path, regions, guard_mm, velocity_mm_s):
    """Conservatively cover every guarded source-zone intersection in progress.

    Each short interval belongs to one Bezier piece. The convex hull of its
    first-derivative controls bounds centre displacement from its midpoint;
    the physical circumscribed guard therefore covers the whole body between
    observations, not just sampled centre positions. Zone endpoints do not
    introduce a rest into the shared continuous motion profile.
    """
    if guard_mm<0 or velocity_mm_s<=0:raise ValueError('Positive source zone speed and nonnegative body guard required')
    output=[];piece_index=0
    for start,end,_,_ in path.samples:
        while path.ends[piece_index]<end-1e-8:piece_index+=1
        piece=path.pieces[piece_index]
        derivative=max(math.hypot(*row[:2])for row in piece['derivatives'][0])
        movement=derivative*(end-start)/2+1e-6
        centre=path.evaluate((start+end)/2)[0][:2]
        if not any(point_distance(centre,row['polygon_mm'])<=guard_mm+movement for row in regions):continue
        if output and start<=output[-1][1]+1e-7:output[-1]=(output[-1][0],end,velocity_mm_s)
        else:output.append((start,end,velocity_mm_s))
    return output
