"""Plain-data BF01 static geometry cache; never a vehicle/action recording.

The build verifies original native inputs. Runtime restores the same geometry
classes from hash-bound data and continues to execute their ordinary collision,
floor, FK and controller checks. No CAD file is represented by a placeholder.
"""
import array
import ast
import collections
from collections.abc import MutableMapping
import copy
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import sys
import shutil
import struct

import building_fleet_model as model

LEGACY_FORMAT='solidcraftbot.building-fleet-runtime-static-cache/1'
FORMAT='solidcraftbot.building-fleet-runtime-static-cache/2'
QUALIFICATION={'static_geometry_only':True,'motion_recorded':False,
               'full_fleet_qualified':False,'hardware_qualified':False}
STATE_FIELDS={'mesh','navigation','grids','floors','certificates','graph','catalog',
              'planner','port_paths','scan_geometry','zone_regions','surface_contract'}
REPORT_FIELDS={'format','runtime_source_files_sha256','operation_sha256','files',
               'source_config_sha256','derivation_inputs','geometry_selection','qualification'}
OPERATION_SPEC={
 'building_fleet_model.py':('lift_route_ports','lift_open_sides_by_level','lift_scan_side_sets'),
 'building_fleet_routes.py':('Navigation',),
 'building_fleet_navigation.py':('NativeMesh','ClearanceGrid','initial_transform','clip_height',
     'native_rectangle_collisions','closed_mesh_membership','_native_band_index'),
 'building_fleet_floor.py':('FloorSupport',),
 'building_fleet_clearance.py':('PolygonIndex','ClearanceCertificate.__init__'),
 'building_fleet_motion.py':('Path',),
 'building_fleet_runner.py':('RouteGraph','native_scan_geometry'),
 'building_fleet_missions.py':('MissionPlanner.__init__','MissionPlanner.prepare_endpoints',
     'MissionPlanner._waiting_approaches','MissionPlanner._private_free','MissionPlanner.prepared_routes'),
 'building_fleet_port_paths.py':('PortPaths',),
 'building_fleet_lift_checks.py':('_source_surface_contract','posed_mesh','fully_open_values'),
 'building_fleet_zones.py':('source_regions',),
 'building_fleet_sim.py':('SegmentIndex','footprint','point_segment_distance'),
 'building_fleet_geometry.py':('vehicle_envelope',),
 'building_fleet_browser_navigation.py':('_typed','geometry_signature','BrowserNavigation._own_right'),
}
_CONTEXTS={}
PERCEPTION_OPERATIONS={'building_fleet_control.py':('qualified_perception_limit','_qualified_scalar_stop',
    '_scalar_stop_catalogue','_scalar_stop_state','_quantized_scalar_clock','source_perception_limit',
    'bind_prepared_perception_limit','perception_cache_input_sha256','preparation_digest',
    'scalar_stop_cache_input_sha256','bind_prepared_scalar_stops')}
RAY_OPERATIONS={'building_fleet_sim.py':('SensorWorld.__init__','SensorWorld._first_returns',
    'SensorWorld._exact_key','ray_segment'),
    'building_fleet_runtime_cache.py':('_direction_fingerprint','seed_static_rays')}


def _require(ok,message):
    if not ok:raise ValueError(message)


def _json(value):
    return (json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()


def _sha(raw):return hashlib.sha256(raw).hexdigest()


def _source_hash(source):return _sha(_json(source))


def operation_pins(*,include_perception=False,include_static_rays=False):
    """Hash only operations which actually define the cached static data."""
    result={}
    groups=[*OPERATION_SPEC.items(),*(PERCEPTION_OPERATIONS.items()if include_perception else()),
            *(RAY_OPERATIONS.items()if include_static_rays else())]
    for filename,names in groups:
        raw=(model.ROOT/'scripts'/filename).read_bytes();lines=raw.splitlines(keepends=True);tree=ast.parse(raw)
        for name in names:
            node=tree
            for part in name.split('.'):
                rows=[row for row in node.body if getattr(row,'name',None)==part]
                _require(len(rows)==1,'Missing static cache operation: '+filename+':'+name)
                node=rows[0]
            first=min([node.lineno,*[row.lineno for row in getattr(node,'decorator_list',[])]])
            result['scripts/'+filename+':'+name]=_sha(b''.join(lines[first-1:node.end_lineno]))
    return result


def operation_pins_for_report(report):
    report=_read(_path(report))if not isinstance(report,dict)else report
    return operation_pins(include_perception=report['format']==FORMAT,
        include_static_rays='static-returns.json'in report['files'])


def _pack(value):
    kind=type(value)
    if value is None or kind in(str,int,bool):return value
    if kind is float:
        _require(math.isfinite(value),'Nonfinite static cache data');return value
    if kind is Fraction:return{'$q':[str(value.numerator),str(value.denominator)]}
    if kind is tuple:return{'$t':[_pack(v)for v in value]}
    if kind is set:return{'$s':[_pack(v)for v in sorted(value,key=repr)]}
    if kind is list:return[_pack(v)for v in value]
    if isinstance(value,dict):
        if all(type(k)is str and not k.startswith('$')for k in value):return{k:_pack(v)for k,v in value.items()}
        return{'$m':[[_pack(k),_pack(v)]for k,v in value.items()]}
    raise ValueError('Unsupported static cache value: '+str(kind))


def _unpack(value,depth=0):
    _require(depth<=80,'Static cache nesting exceeds its closed contract')
    if isinstance(value,list):return[_unpack(v,depth+1)for v in value]
    if not isinstance(value,dict):
        _require(type(value)in(str,int,bool,float,type(None)),'Closed static primitive required')
        _require(type(value)is not float or math.isfinite(value),'Finite static primitive required')
        return value
    tags=set(value)&{'$q','$t','$s','$m'}
    if tags:
        _require(len(value)==len(tags)==1,'Closed typed static value required')
        tag=next(iter(tags));rows=value[tag];_require(type(rows)is list,'Typed static array required')
        if tag=='$q':
            _require(len(rows)==2 and all(type(v)is str and v.lstrip('-').isdigit()for v in rows),'Exact rational numerator/denominator required')
            result=Fraction(int(rows[0]),int(rows[1]));_require(str(result.numerator)==rows[0]and str(result.denominator)==rows[1],'Canonical rational required');return result
        if tag=='$t':return tuple(_unpack(v,depth+1)for v in rows)
        if tag=='$s':
            result=set(_unpack(v,depth+1)for v in rows);_require(len(result)==len(rows),'Unique static set values required');return result
        result={}
        for row in rows:
            _require(type(row)is list and len(row)==2,'Static mapping pair required')
            key=_unpack(row[0],depth+1);_require(key not in result,'Duplicate static mapping key');result[key]=_unpack(row[1],depth+1)
        return result
    _require(all(type(k)is str and not k.startswith('$')for k in value),'Unknown static value tag')
    return{k:_unpack(v,depth+1)for k,v in value.items()}


def _read(path):
    def pairs(rows):
        result={}
        for key,value in rows:
            _require(key not in result,'Duplicate static JSON field');result[key]=value
        return result
    return json.loads(Path(path).read_bytes(),object_pairs_hook=pairs,
        parse_constant=lambda value:(_ for _ in()).throw(ValueError('Nonfinite static JSON')))


def _read_typed(path):
    """Decode tags during JSON parsing, without walking every numeric scalar."""
    return _typed_bytes(Path(path).read_bytes())


def _typed_bytes(raw):
    # Only exact hash-verified artifacts produced by _pack enter this decoder.
    # Their ordinary unique-key JSON dictionaries need no Python per-field
    # reconstruction. The report/boundary parser above remains strict.
    def tagged(result):
        if len(result)!=1:return result
        tag=next(iter(result))
        if not tag.startswith('$'):return result
        _require(tag in('$q','$t','$s','$m'),'Unknown static type tag')
        value=result[tag];_require(type(value)is list,'Static typed array required')
        if tag=='$t':return tuple(value)
        if tag=='$s':
            answer=set(value);_require(len(answer)==len(value),'Unique static set required');return answer
        if tag=='$q':
            _require(len(value)==2 and all(type(v)is str and v.lstrip('-').isdigit()for v in value),'Exact rational encoding required')
            answer=Fraction(int(value[0]),int(value[1]));_require(str(answer.numerator)==value[0]and str(answer.denominator)==value[1],'Canonical rational required');return answer
        answer={}
        for row in value:
            _require(type(row)is list and len(row)==2 and row[0]not in answer,'Unique static mapping pair required');answer[row[0]]=row[1]
        return answer
    return json.loads(raw,object_hook=tagged,
        parse_constant=lambda value:(_ for _ in()).throw(ValueError('Nonfinite static JSON')))


def _path(path):
    result=(model.ROOT/Path(path)).resolve()
    _require(result.is_relative_to(model.ROOT.resolve()),'Project-local static cache path required')
    return result


def _artifact(path):
    path=Path(path).resolve();raw=path.read_bytes()
    return{'path':path.relative_to(model.ROOT.resolve()).as_posix(),'sha256':_sha(raw),'bytes':len(raw)}


def _fields(obj,excluded=()):return{k:v for k,v in obj.__dict__.items()if k not in excluded}


def _index(index):return{'cell':index.cell,'cells':index.cells,'large':index.large}


def _restore_index(polygons,data):
    from building_fleet_clearance import PolygonIndex
    _require(set(data)=={'cell','cells','large'}and type(data['cell'])in(int,float)and data['cell']>0,'Closed positive polygon index required')
    index=PolygonIndex.__new__(PolygonIndex);index.polygons=polygons;index.cell=data['cell'];index.cells=data['cells'];index.large=data['large']
    _require(all(type(k)is tuple and len(k)==2 and all(type(v)is int for v in k)for k in index.cells),'Integer polygon cells required')
    _require(all(type(i)is int and 0<=i<len(polygons)for rows in[*index.cells.values(),index.large]for i in rows),'Polygon index exceeds geometry')
    return index


def _mesh_data(mesh,nav,output,write):
    moving=set(mesh.transforms)
    error=mesh.scene['linear_tessellation_deflection_mm']+math.sqrt(3)*mesh.scene['maximum_float32_error_mm']
    bands=[(z-error,z+nav.height+error)for z in nav.level_z.values()]
    selected=[];omitted=[];indices=array.array('I');positions=array.array('f');remap={}
    for group in mesh.scene['groups']:
        bounds=mesh.bounds(group)
        keep=(group['id']in moving or group['role']=='concept_storey_slab'or
              any(bounds['max'][2]>=lo and bounds['min'][2]<=hi for lo,hi in bands))
        if not keep:
            omitted.append({'id':group['id'],'role':group['role'],'bounds_mm':bounds,
                'reason':'nonmoving whole body strictly outside every source floor-height query band'})
            continue
        row=copy.deepcopy(group);row['index_start']=len(indices)
        for old in mesh.indices[group['index_start']:group['index_start']+group['index_count']]:
            if old not in remap:
                remap[old]=len(remap);positions.extend(mesh.positions[old*3:old*3+3])
            indices.append(remap[old])
        selected.append(row)
    if sys.byteorder!='little':positions.byteswap();indices.byteswap()
    write('positions.f32le',positions.tobytes());write('indices.u32le',indices.tobytes())
    scene={key:copy.deepcopy(mesh.scene[key])for key in('bounds_mm','maximum_float32_error_mm',
        'linear_tessellation_deflection_mm','angular_tessellation_deflection_rad','coordinate_frame','units','up_axis','handedness')}
    scene.update(groups=selected,vertex_count=len(positions)//3,index_count=len(indices),
        scope='Lossless complete native bodies in every reachable source floor band, plus all moving bodies; display normals omitted')
    selection={'source_body_count':len(mesh.scene['groups']),'retained_body_count':len(selected),
        'source_index_count':len(mesh.indices),'retained_index_count':len(indices),'bands_mm':bands,
        'all_moving_bodies_retained':True,'whole_bodies_only':True,'group_order_preserved':True,
        'source_global_bounds_unchanged':True,'omitted_bodies':omitted}
    return{'scene':scene,'manifest':mesh.manifest},selection


def build_cache(output_dir,*,source,navigation,graph,catalog,planner,derivation_inputs,
                runtime_source_files_sha256,surface_contract=None):
    """Export a newly attested plain static cache from checked model objects."""
    import walkthrough_world
    from building_fleet_runner import native_scan_geometry
    from building_fleet_geometry_checks import GeometryChecks
    from building_fleet_zones import source_regions
    from building_fleet_lift_checks import source_surface_contract
    source=model.validate(source);nav=navigation
    _require(nav.config==source and graph.sealed is True and catalog._frozen is True,'Closed checked static source map required')
    _require(all(not row['queue']and not row['seen']and not row['completed']and row['active']is None for row in planner.states.values()),'Never cache active missions or observations')
    original_report,_,_=walkthrough_world.read(nav.mesh.export,model.ROOT)
    pins=dict(runtime_source_files_sha256)
    for path,digest in pins.items():model.resolve_pin({'path':path,'sha256':digest})
    ops=operation_pins();output=_path(output_dir);_require(not output.exists(),'Preserve existing static cache evidence');output.mkdir(parents=True)
    files={}
    def write(name,raw):
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);files[name]=_artifact(path)
    native,selection=_mesh_data(nav.mesh,nav,output,write)
    state={'mesh':native,'navigation':_fields(nav,('mesh','grids','_straight_cache','_fleet_band_cache')),
           'grids':{},'floors':{},'certificates':{},'graph':_fields(graph,('navigation','progress')),
           'catalog':{},'planner':_fields(planner,('source','nav','graph','states','port_paths')),
           'port_paths':None if planner.port_paths is None else _fields(planner.port_paths,('source','nav')),
           'scan_geometry':native_scan_geometry(nav),'zone_regions':{level:source_regions(nav,level)for level in nav.level_z},
           'surface_contract':source_surface_contract()if surface_contract is None else surface_contract}
    # A source map cache contains templates, not accumulated route-call counters.
    if '_browser_bearing_provenance'in state['navigation']:
        stats=copy.deepcopy(state['navigation']['_browser_bearing_provenance'])
        for key in('matched_route_calls','unknown_route_calls','rebound_route_calls','rebound_bearing_count','maximum_ulp_distance'):
            stats[key]=0
        stats['maximum_absolute_difference_rad']=0.;stats['examples']=[]
        state['navigation']['_browser_bearing_provenance']=stats
    for level,grid in nav.grids.items():
        prefix='grids/'+level
        write(prefix+'.blocked.bin',bytes(grid.blocked));write(prefix+'.supported.bin',bytes(grid.supported))
        distances=array.array('d',grid.distance_squared)
        if sys.byteorder!='little':distances.byteswap()
        write(prefix+'.distance.f64le',distances.tobytes())
        state['grids'][level]={'width':grid.width,'height':grid.height,'origin':grid.origin,'resolution_mm':grid.resolution_mm}
        bank=grid.floor_support
        state['floors'][level]={'gap':bank.gap,'padding':bank.padding,'z':bank.z,'height_tolerance':bank.height_tolerance,
            'triangles':bank.triangles,'body_ids':bank.body_ids,'cells':bank.cells,
            'cell_bodies':[bank.cell_bodies[id(p)]for p in bank.cells],'index':_index(bank.index),'cell_index':_index(bank.cell_index)}
    checks=GeometryChecks(source,nav)
    for level in nav.level_z:
        cert=checks.certificate(level)
        # The base excludes no owned waiting bay. Variants are rebuilt by the
        # original GeometryChecks.certificate with the actual own grant.
        base=checks.base[level]
        state['certificates'][level]={'L':base.L,'W':base.W,'radius':base.radius,'reserve':base.reserve,
            'mesh_error':base.mesh_error,'obstacles':base.obstacles,'obstacle_names':base.obstacle_names,
            'floor_index':_index(base.floor_index),'obstacle_index':_index(base.obstacle_index)}
    simple=('guard','parent','kind','regions','room_alias','room_polygons','canonical','resources',
        '_region_keys','_room_index','_rooms_by_level','_unindexed_rooms','_room_numeric_padding',
        '_index','_query_cell_size','_query_index','_region_coarse_bounds')
    state['catalog']={key:getattr(catalog,key)for key in simple}
    write('state.json',_json(_pack(state)))
    _require(ops==operation_pins(),'Static geometry operations changed during export')
    for path,digest in pins.items():model.resolve_pin({'path':path,'sha256':digest})
    report={'format':LEGACY_FORMAT,'runtime_source_files_sha256':pins,'operation_sha256':ops,'files':files,
        'source_config_sha256':_source_hash(source),'derivation_inputs':{**derivation_inputs,
            'original_world_report':original_report,'generator_source_sha256':model.digest(Path(__file__))},
        'geometry_selection':selection,'qualification':QUALIFICATION}
    (output/'cache-report.json').write_bytes(_json(report))
    return report


def bundle_files(report_path,*,verify=True):
    """Return only real compact artifacts; original CAD refs are build evidence."""
    path=_path(report_path);report=_read(path)
    _require(type(report)is dict and set(report)==REPORT_FIELDS and report['format']in(FORMAT,LEGACY_FORMAT)
        and report['qualification']==QUALIFICATION,'Closed static-only cache report required')
    _require(type(report['files'])is dict and set(report['files'])>={'state.json','positions.f32le','indices.u32le'},'Complete static artifacts required')
    result={path.relative_to(model.ROOT.resolve()).as_posix():{'sha256':model.digest(path),'bytes':path.stat().st_size}}
    for name,ref in report['files'].items():
        artifact=_path(ref['path'])
        _require(type(name)is str and name and not Path(name).is_absolute()and '..'not in Path(name).parts
            and artifact==path.parent/name and set(ref)=={'path','sha256','bytes'},'Bounded named static artifact required')
        _require(type(ref['bytes'])is int and artifact.is_file()and artifact.stat().st_size==ref['bytes'],'Static cache size changed: '+name)
        if verify:
            raw=artifact.read_bytes();_require(_sha(raw)==ref['sha256'],'Static cache bytes changed: '+name)
        result[ref['path']]={'sha256':ref['sha256'],'bytes':ref['bytes']}
    return result


def verification_receipt(report_path):
    """Build-only operation proof, bound to exact code and cache file hashes."""
    path=_path(report_path);files=bundle_files(path);report=_read(path)
    _require(report['operation_sha256']==operation_pins_for_report(report),'Cache static operations differ from the actual bundle code')
    modules={key.split(':',1)[0]for key in report['operation_sha256']}
    return{'format':'solidcraftbot.building-fleet-static-cache-verification/1',
        'report':_artifact(path),'operation_sha256':report['operation_sha256'],
        'module_files_sha256':{name:model.digest(_path(name))for name in sorted(modules)},
        'runtime_source_files_sha256':report['runtime_source_files_sha256'],'files':files}


def _verified_binding(path,report,files,receipt):
    _require(type(files)is dict and type(receipt)is dict and set(receipt)=={
        'format','report','operation_sha256','module_files_sha256','runtime_source_files_sha256','files'}
        and receipt['format']=='solidcraftbot.building-fleet-static-cache-verification/1','Closed extraction verification receipt required')
    known=bundle_files(path,verify=False)
    _require(receipt['report']==_artifact(path)and receipt['files']==known
        and receipt['operation_sha256']==report['operation_sha256']
        and receipt['runtime_source_files_sha256']==report['runtime_source_files_sha256'],'Build operation receipt belongs to another exact cache')
    modules={key.split(':',1)[0]for key in report['operation_sha256']}
    _require(set(receipt['module_files_sha256'])==modules,'Every static operation module must be bound')
    for name,row in known.items():
        _require(files.get(name)==row,'Extracted cache file differs from its exact build receipt: '+name)
    for name,digest in{**report['runtime_source_files_sha256'],**receipt['module_files_sha256']}.items():
        _require(isinstance(files.get(name),dict)and files[name].get('sha256')==digest,'Extracted source/code differs from its static operation receipt: '+name)


def _array(code,raw):
    result=array.array(code);_require(len(raw)%result.itemsize==0,'Whole native scalar array required');result.frombytes(raw)
    if sys.byteorder!='little':result.byteswap()
    return result


def _restore_catalog(data,nav):
    import building_fleet_resources as resources
    c=resources.ResourceCatalog.__new__(resources.ResourceCatalog);c.__dict__.update(data);c.nav=nav;c.paths=[];c._frozen=True
    c._bind_polygon_queries()
    c._candidates=lru_cache(maxsize=32768)(c._candidate_indices);c._static_paths={};c._raw_alias_windows={}
    return c


def bind_active_fleet(prepared, source, profile):
    """Bind fresh live state to a subset of the unchanged static home map.

    The cache still describes every reference route and all twenty available
    home placements. Only selected homes count as occupied in the world,
    conditional home maps and isolated own-route preparation proofs.
    """
    identities = model.active_vehicle_ids(source, profile)
    nav, planner = prepared['nav'], prepared['planner']
    expected = set(model.active_vehicle_ids(source))
    _require(nav.config == source and set(nav.homes) == expected,
             'The active fleet needs the complete source-matched reference home map')
    if len(identities) == len(expected):
        return prepared
    _require(set(planner.states) == expected and all(
        not state['queue'] and not state['seen'] and not state['completed']
        and state['active'] is None and state['terminal'] is None and not state['done']
        and not state['requested'] and not state['admission_deferred']
        and state['home_confirmation'] is None for state in planner.states.values()),
        'Select live occupants before any assignment, observation or execution')
    active_nav = copy.copy(nav)
    active_nav.homes = {identity: copy.deepcopy(nav.homes[identity]) for identity in identities}
    graph = copy.copy(prepared['graph'])
    graph.navigation = active_nav
    catalog = copy.copy(prepared['catalog'])
    catalog.nav = active_nav
    active_planner = copy.copy(planner)
    active_planner.nav, active_planner.graph = active_nav, graph
    active_planner.states = {identity: copy.deepcopy(planner.states[identity]) for identity in identities}
    if planner.port_paths is not None:
        active_planner.port_paths = copy.copy(planner.port_paths)
        active_planner.port_paths.nav = active_nav
    result = {**prepared, 'nav': active_nav, 'graph': graph,
              'catalog': catalog, 'planner': active_planner}
    if 'geometry_checks' in prepared and getattr(prepared['geometry_checks'], 'nav', None) is nav:
        result['geometry_checks'] = copy.copy(prepared['geometry_checks'])
        result['geometry_checks'].nav = active_nav
    return result


def restore(report_path,source,*,progress=None,verified_operations=None,initial_level=None,
            verified_files=None,verification_receipt=None):
    """Restore original static classes; initialize no robot, mission or scan."""
    from building_fleet_navigation import NativeMesh,ClearanceGrid,initial_transform
    from building_fleet_browser_navigation import BrowserNavigation
    import building_fleet_floor as floors
    from building_fleet_clearance import ClearanceCertificate
    from building_fleet_geometry_checks import GeometryChecks
    from building_fleet_runner import RouteGraph
    from building_fleet_missions import MissionPlanner
    from building_fleet_port_paths import PortPaths
    path=_path(report_path);report=_read(path)
    verified=verified_files is not None or verification_receipt is not None
    if verified:_verified_binding(path,report,verified_files,verification_receipt)
    else:bundle_files(path)
    source=model.validate(source,verify_pins=not verified)
    _require(report['source_config_sha256']==_source_hash(source),'Static cache belongs to a different fleet source')
    if not verified:
        _require(report['operation_sha256']==(operation_pins_for_report(report)if verified_operations is None else verified_operations),'Static geometry operation pins changed')
        for filename,digest in report['runtime_source_files_sha256'].items():model.resolve_pin({'path':filename,'sha256':digest})
    data=_read_typed(path.parent/'state.json')
    if report['format']==FORMAT:
        return _restore_partitioned(path,report,data,source,progress,initial_level)
    _require(set(data)==STATE_FIELDS,'Closed static state data required')
    native=data['mesh'];mesh=NativeMesh.__new__(NativeMesh);mesh.manifest=native['manifest'];mesh.scene=native['scene']
    mesh.export=path.parent;mesh.world_report_path=path;mesh.positions=_array('f',(path.parent/'positions.f32le').read_bytes());mesh.indices=_array('I',(path.parent/'indices.u32le').read_bytes())
    _require(len(mesh.positions)==mesh.scene['vertex_count']*3 and len(mesh.indices)==mesh.scene['index_count'],'Complete compact native buffers required')
    _require(all(0<=i<len(mesh.positions)//3 for i in mesh.indices),'Native indices exceed retained vertices')
    mesh.transforms=collections.defaultdict(list);objects={o['id']:o for o in mesh.manifest['objects']}
    for obj in objects.values():
        chain=[obj];parent=obj.get('parent_object_id')
        while parent:chain.append(objects[parent]);parent=objects[parent].get('parent_object_id')
        for body in obj['moving_body_ids']:mesh.transforms[body]=chain
    nav=BrowserNavigation.__new__(BrowserNavigation);nav.__dict__.update(data['navigation']);nav.config=source;nav.mesh=mesh;nav.grids={}
    _require(set(data['grids'])==set(nav.level_z)==set(data['floors'])==set(data['certificates']),'Every source level must retain its complete static geometry')
    for level,row in data['grids'].items():
        grid=ClearanceGrid.__new__(ClearanceGrid);grid.__dict__.update(row);count=grid.width*grid.height
        grid.blocked=bytearray((path.parent/('grids/'+level+'.blocked.bin')).read_bytes());grid.supported=bytearray((path.parent/('grids/'+level+'.supported.bin')).read_bytes());grid.distance_squared=_array('d',(path.parent/('grids/'+level+'.distance.f64le')).read_bytes())
        _require(type(grid.width)is int and type(grid.height)is int and count>0 and len(grid.blocked)==len(grid.supported)==len(grid.distance_squared)==count,'Complete source-framed static grid required')
        row=data['floors'][level];bank=floors.FloorSupport.__new__(floors.FloorSupport)
        bank.mesh=mesh;bank.level=level;bank.config=source
        for key in('gap','padding','z','height_tolerance','triangles','body_ids','cells'):setattr(bank,key,row[key])
        _require(len(bank.triangles)==len(bank.body_ids)and len(bank.cells)==len(row['cell_bodies']),'Every support primitive needs its native body identity')
        bank.ids={id(p):b for p,b in zip(bank.triangles,bank.body_ids)};bank.cell_bodies={id(p):b for p,b in zip(bank.cells,row['cell_bodies'])}
        bank.index=_restore_index(bank.triangles,row['index']);bank.cell_index=_restore_index(bank.cells,row['cell_index']);bank.applications=[]
        grid.floor_support=bank;grid._floor_edges={};nav.grids[level]=grid
        floors._CACHE[(id(mesh),level,model.digest(model.SOURCE),model.digest(model.SCHEMA))]=bank
    graph=RouteGraph.__new__(RouteGraph);graph.__dict__.update(data['graph']);graph.navigation=nav;graph.progress=progress
    _require(graph.sealed is True and set(graph.hubs)==set(nav.level_z),'All source route graphs must remain sealed')
    catalog=_restore_catalog(data['catalog'],nav)
    planner=MissionPlanner.__new__(MissionPlanner);planner.__dict__.update(data['planner']);planner.source=source;planner.nav=nav;planner.graph=graph
    planner.states={vehicle:{'queue':[],'seen':{},'completed':set(),'active':None,'terminal':None,'done':False,
        'requested':False,'admission_deferred':False,'home_confirmation':None}for vehicle in nav.homes}
    planner.port_paths=None
    if data['port_paths']is not None:
        planner.port_paths=PortPaths.__new__(PortPaths);planner.port_paths.__dict__.update(data['port_paths']);planner.port_paths.source=source;planner.port_paths.nav=nav
    checker=GeometryChecks(source,nav)
    for level,row in data['certificates'].items():
        cert=ClearanceCertificate.__new__(ClearanceCertificate);cert.mesh=mesh;cert.level=level;cert.config=source;cert.lift_context=None;cert.floor_bank=nav.grids[level].floor_support
        for key in('L','W','radius','reserve','mesh_error','obstacles','obstacle_names'):setattr(cert,key,row[key])
        _require(len(cert.obstacles)==len(cert.obstacle_names),'Every native obstacle needs its body identity')
        cert.floor_triangles=cert.floor_bank.triangles;cert.floor_index=_restore_index(cert.floor_triangles,row['floor_index']);cert.obstacle_index=_restore_index(cert.obstacles,row['obstacle_index']);cert.obstacle_ids={id(p):i for i,p in enumerate(cert.obstacles)};cert.start_grid=nav.grids[level];checker.base[level]=cert
    token=object();mesh._runtime_static_cache_token=token
    _CONTEXTS[token]={'source':copy.deepcopy(source),'report':report,'report_path':path,'surface_contract':data['surface_contract']}
    if progress:progress({'phase':'compact_static_geometry_ready','levels':len(nav.level_z),'native_bodies':len(mesh.scene['groups'])})
    return{'nav':nav,'graph':graph,'catalog':catalog,'planner':planner,'geometry_checks':checker,
           'scan_geometry':data['scan_geometry'],'zone_regions':data['zone_regions']}


def cached_world_report(mesh):
    """Explicit derived-cache provenance for ordinary and source-posed meshes."""
    token=getattr(mesh,'_runtime_static_cache_token',None);context=_CONTEXTS.get(token)
    if context is None:return None
    _require(context['report']['source_config_sha256']==_source_hash(model.load()),'Compact native source changed')
    return{**copy.deepcopy(context['report']['derivation_inputs']['original_world_report']),
        'compact_runtime_provenance':{'cache':_artifact(context['report_path']),
            'original_native_CAD_verified':'at_build','runtime_verified':'exact compact data and all used source/code hashes'}}


def cached_surface_contract():
    source_hash=_source_hash(model.load())
    candidates=[row for row in _CONTEXTS.values()if row['report']['source_config_sha256']==source_hash]
    if not candidates:return None
    value=candidates[-1]['surface_contract']
    for path,digest in value['source_files_sha256'].items():model.resolve_pin({'path':path,'sha256':digest})
    return copy.deepcopy(value)


class _LazyMap(MutableMapping):
    """Known immutable keys; checked static values are materialized on first use."""
    def __init__(self,keys,load):self._keys=tuple(keys);self._keyset=set(keys);self._load=load;self._values={}
    def __getitem__(self,key):
        if key not in self._keyset:raise KeyError(key)
        if key not in self._values:self._values[key]=self._load(key)
        return self._values[key]
    def __contains__(self,key):return key in self._keyset
    def __iter__(self):return iter(self._keys)
    def __len__(self):return len(self._keys)
    def __setitem__(self,key,value):
        if key not in self._keyset:raise KeyError('No static cache expansion')
        self._values[key]=value
    def __delitem__(self,key):raise TypeError('Immutable static cache key')


class _RouteMap(MutableMapping):
    def __init__(self,levels,counts,load):self._levels=tuple(levels);self._counts=counts;self._load=load
    def __getitem__(self,key):
        if not isinstance(key,tuple)or not key or key[0]not in self._counts:raise KeyError(key)
        return self._load(key[0])[key]
    def __contains__(self,key):return isinstance(key,tuple)and bool(key)and key[0]in self._counts and key in self._load(key[0])
    def __iter__(self):
        for level in self._levels:yield from self._load(level)
    def __len__(self):return sum(self._counts.values())
    def __setitem__(self,key,value):self._load(key[0])[key]=value
    def __delitem__(self,key):raise TypeError('Immutable static route key')


def _segment_data(segments):
    from building_fleet_sim import SegmentIndex
    index=SegmentIndex(segments)
    return{'segments':index.segments,'cell':index.cell,'cells':index.cells}


def _restore_segment(data):
    from building_fleet_sim import SegmentIndex
    _require(set(data)=={'segments','cell','cells'}and type(data['cell'])in(int,float)and data['cell']>0,'Closed static ray index required')
    index=SegmentIndex.__new__(SegmentIndex);index.segments=tuple(data['segments']);index.cell=data['cell'];index.cells=data['cells']
    _require(all(type(i)is int and 0<=i<len(index.segments)for rows in index.cells.values()for i in rows),'Ray index exceeds exact segments')
    return index


def partition_cache(report_path,output_dir,source):
    """Derive a fresh lazy-level cache from verified immutable native data."""
    from building_fleet_clearance import PolygonIndex
    import building_fleet_control as control
    source=model.validate(source);original=_path(report_path);bundle_files(original);prior=_read(original)
    _require(prior['format']==LEGACY_FORMAT and prior['source_config_sha256']==_source_hash(source),'A source-matched original compact cache is required')
    _require(prior['operation_sha256']==operation_pins(),'Original static operations changed before partitioning')
    data=_read_typed(original.parent/'state.json');_require(set(data)==STATE_FIELDS,'Original complete static data required')
    output=_path(output_dir);_require(not output.exists(),'Preserve existing partitioned cache');output.mkdir(parents=True)
    files={}
    def write(name,raw):
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);files[name]=_artifact(path)
    for name in prior['files']:
        if name!='state.json':
            path=output/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original.parent/name,path);files[name]=_artifact(path)
    levels=tuple(data['navigation']['level_z']);scans,cabins,landings=data['scan_geometry']
    global_data={key:data[key]for key in('mesh','navigation','graph','catalog','planner','port_paths','zone_regions','surface_contract')}
    global_data['layout']='lazy_native_levels/1';global_data['levels']=levels
    global_data['route_counts']={};global_data['level_files']={}
    nav_routes=global_data['navigation'].pop('_route_cache')
    centres=global_data['graph'].pop('centreline');repairs=global_data['graph'].pop('repairs')
    global_data['cabin_indices']={sides:_segment_data(rows)for sides,rows in cabins.items()}
    global_data['variant_keys']=[]
    for level in levels:
        certificate=data['certificates'][level];variants={};waits=data['navigation']['waiting_bay_polygons'][level]
        for own in(None,*range(len(waits))):
            for port in(False,True):
                omitted=[i for i,name in enumerate(certificate['obstacle_names'])if port and name=='ExcludedArea.LiftCore']
                extra=[i for i in range(len(waits))if i!=own]
                polygons=[p for i,p in enumerate(certificate['obstacles'])if i not in omitted]+[waits[i]for i in extra]
                variants[own,port]={'omitted':omitted,'extra':extra,'index':_index(PolygonIndex(polygons))}
                global_data['variant_keys'].append((level,own,port))
        routes={'navigation':{k:v for k,v in nav_routes.items()if k[0]==level},
            'centreline':{k:v for k,v in centres.items()if k[0]==level},'repairs':{k:v for k,v in repairs.items()if k[0]==level}}
        global_data['route_counts'][level]={key:len(value)for key,value in routes.items()}
        row={'grid':data['grids'][level],'floor':data['floors'][level],'certificate':certificate,
            'variants':variants,'routes':routes,'scan_index':_segment_data(scans[level]),
            'landing_indices':{sides:_segment_data(rows)for(l,sides),rows in landings.items()if l==level}}
        filename='levels/'+level+'.json';write(filename,_json(_pack(row)));global_data['level_files'][level]=filename
    radius=data['navigation']['envelope']['radius_mm']
    global_data['perception_limit']={'input_sha256':control.perception_cache_input_sha256(source,radius),
        'result':control.source_perception_limit(source,radius)}
    write('state.json',_json(_pack(global_data)))
    pins={path:model.digest(_path(path))for path in prior['runtime_source_files_sha256']}
    report={'format':FORMAT,'runtime_source_files_sha256':pins,'operation_sha256':operation_pins(include_perception=True),
        'files':files,'source_config_sha256':_source_hash(source),'geometry_selection':prior['geometry_selection'],
        'qualification':QUALIFICATION,'derivation_inputs':{**prior['derivation_inputs'],
            'partition_source_cache':_artifact(original),'partition_source_generator_sha256':model.digest(Path(__file__)),
            'partition_scope':'Same verified native geometry, exact original ray indexes and base/waiting variants; lazy materialization only. New pure source-bound perception math, no recorded scans/actions.'}}
    (output/'cache-report.json').write_bytes(_json(report));return report


def _restore_partitioned(path,report,data,source,progress,initial_level):
    from building_fleet_navigation import NativeMesh,ClearanceGrid
    from building_fleet_browser_navigation import BrowserNavigation
    import building_fleet_floor as floors
    from building_fleet_clearance import ClearanceCertificate
    from building_fleet_geometry_checks import GeometryChecks
    from building_fleet_runner import RouteGraph
    from building_fleet_missions import MissionPlanner
    from building_fleet_port_paths import PortPaths
    import building_fleet_control as control
    _require(data.get('layout')=='lazy_native_levels/1','Closed lazy native level layout required')
    levels=data['levels'];_require(set(levels)==set(data['navigation']['level_z'])==set(data['level_files']),'Every source level must be present before use')
    native=data['mesh'];mesh=NativeMesh.__new__(NativeMesh);mesh.manifest=native['manifest'];mesh.scene=native['scene'];mesh.export=path.parent;mesh.world_report_path=path
    mesh.positions=_array('f',(path.parent/'positions.f32le').read_bytes());mesh.indices=_array('I',(path.parent/'indices.u32le').read_bytes())
    _require(len(mesh.positions)==3*mesh.scene['vertex_count']and len(mesh.indices)==mesh.scene['index_count'],'Complete lossless native buffers required')
    mesh.transforms=collections.defaultdict(list);objects={o['id']:o for o in mesh.manifest['objects']}
    for obj in objects.values():
        chain=[obj];parent=obj.get('parent_object_id')
        while parent:chain.append(objects[parent]);parent=objects[parent].get('parent_object_id')
        for body in obj['moving_body_ids']:mesh.transforms[body]=chain
    nav=BrowserNavigation.__new__(BrowserNavigation);nav.__dict__.update(data['navigation']);nav.mesh=mesh;nav.config=source
    loaded={}
    def level_data(level):
        if level not in loaded:
            _require(level in data['level_files'],'Unknown source floor')
            name=data['level_files'][level];ref=report['files'].get(name);_require(ref is not None,'Floor artifact is undeclared')
            raw=(path.parent/name).read_bytes();_require(_sha(raw)==ref['sha256']and len(raw)==ref['bytes'],'Floor geometry changed before use')
            loaded[level]=_read_typed(path.parent/name)
        return loaded[level]
    grid_values={};cert_values={}
    def grid_at(level):
        if level in grid_values:return grid_values[level]
        row=level_data(level);grid=ClearanceGrid.__new__(ClearanceGrid);grid.__dict__.update(row['grid']);prefix='grids/'+level
        grid.blocked=bytearray((path.parent/(prefix+'.blocked.bin')).read_bytes());grid.supported=bytearray((path.parent/(prefix+'.supported.bin')).read_bytes());grid.distance_squared=_array('d',(path.parent/(prefix+'.distance.f64le')).read_bytes())
        count=grid.width*grid.height;_require(len(grid.blocked)==len(grid.supported)==len(grid.distance_squared)==count,'Complete lazy floor grid required')
        f=row['floor'];bank=floors.FloorSupport.__new__(floors.FloorSupport);bank.mesh=mesh;bank.level=level;bank.config=source
        for name in('gap','padding','z','height_tolerance','triangles','body_ids','cells'):setattr(bank,name,f[name])
        bank.ids={id(p):name for p,name in zip(bank.triangles,bank.body_ids)};bank.cell_bodies={id(p):names for p,names in zip(bank.cells,f['cell_bodies'])}
        bank.index=_restore_index(bank.triangles,f['index']);bank.cell_index=_restore_index(bank.cells,f['cell_index']);bank.applications=[]
        grid.floor_support=bank;grid._floor_edges={};grid_values[level]=grid
        floors._CACHE[(id(mesh),level,model.digest(model.SOURCE),model.digest(model.SCHEMA))]=bank
        return grid
    nav.grids=_LazyMap(levels,grid_at);mesh._runtime_floor_loader=grid_at
    def base_at(level):
        if level in cert_values:return cert_values[level]
        grid=grid_at(level);row=level_data(level)['certificate'];cert=ClearanceCertificate.__new__(ClearanceCertificate)
        cert.mesh=mesh;cert.level=level;cert.config=source;cert.lift_context=None;cert.floor_bank=grid.floor_support
        for key in('L','W','radius','reserve','mesh_error','obstacles','obstacle_names'):setattr(cert,key,row[key])
        cert.floor_triangles=cert.floor_bank.triangles;cert.floor_index=_restore_index(cert.floor_triangles,row['floor_index']);cert.obstacle_index=_restore_index(cert.obstacles,row['obstacle_index']);cert.obstacle_ids={id(p):i for i,p in enumerate(cert.obstacles)};cert.start_grid=grid;cert_values[level]=cert;return cert
    def variant_at(key):
        level,own,port=key;base=base_at(level);row=level_data(level)['variants'][own,port];cert=copy.copy(base)
        cert.obstacles=[p for i,p in enumerate(base.obstacles)if i not in row['omitted']];cert.obstacle_names=[n for i,n in enumerate(base.obstacle_names)if i not in row['omitted']]
        for i in row['extra']:cert.obstacles.append(nav.waiting_bay_polygons[level][i]);cert.obstacle_names.append('ReservedLiftWaitingBay.'+level+'.'+str(i))
        cert.obstacle_index=_restore_index(cert.obstacles,row['index']);cert.obstacle_ids={id(p):i for i,p in enumerate(cert.obstacles)};return cert
    checker=GeometryChecks(source,nav);checker.base=_LazyMap(levels,base_at);checker.variants=_LazyMap(data['variant_keys'],variant_at)
    graph=RouteGraph.__new__(RouteGraph);graph.__dict__.update(data['graph']);graph.navigation=nav;graph.progress=progress
    for name in('centreline','repairs'):
        setattr(graph,name,_RouteMap(levels,{l:data['route_counts'][l][name]for l in levels},lambda level,n=name:level_data(level)['routes'][n]))
    nav._route_cache=_RouteMap(levels,{l:data['route_counts'][l]['navigation']for l in levels},lambda level:level_data(level)['routes']['navigation'])
    catalog=_restore_catalog(data['catalog'],nav)
    planner=MissionPlanner.__new__(MissionPlanner);planner.__dict__.update(data['planner']);planner.source=source;planner.nav=nav;planner.graph=graph
    planner.states={vehicle:{'queue':[],'seen':{},'completed':set(),'active':None,'terminal':None,'done':False,
        'requested':False,'admission_deferred':False,'home_confirmation':None}for vehicle in nav.homes}
    planner.port_paths=None
    if data['port_paths']is not None:
        planner.port_paths=PortPaths.__new__(PortPaths);planner.port_paths.__dict__.update(data['port_paths']);planner.port_paths.source=source;planner.port_paths.nav=nav
    def bound_segment(row,kind,key,geometry_sha):
        index=_restore_segment(row);index._runtime_static_index_binding=(report['source_config_sha256'],kind,key,geometry_sha);return index
    static=_LazyMap(levels,lambda level:bound_segment(level_data(level)['scan_index'],'static',level,report['files'][data['level_files'][level]]['sha256']))
    cabin={sides:bound_segment(row,'cabin',sides,_sha(_json(_pack(row))))for sides,row in data['cabin_indices'].items()}
    side_sets=model.lift_scan_side_sets(mesh.manifest['elevator']['ports'])
    if set(cabin)!=set(side_sets):raise ValueError('Prepared cabin scans must bind every source door state')
    landing_keys=[(level,sides)for level in levels for sides in side_sets]
    landings=_LazyMap(landing_keys,lambda key:bound_segment(level_data(key[0])['landing_indices'][key[1]],'landing',key,report['files'][data['level_files'][key[0]]]['sha256']))
    scan_geometry=(_LazyMap(levels,lambda level:static[level].segments),
        {sides:index.segments for sides,index in cabin.items()},_LazyMap(landing_keys,lambda key:landings[key].segments))
    token=object();mesh._runtime_static_cache_token=token;_CONTEXTS[token]={'source':copy.deepcopy(source),'report':report,'report_path':path,'surface_contract':data['surface_contract']}
    control.bind_prepared_perception_limit(source,nav.envelope['radius_mm'],data['perception_limit'])
    if 'scalar_stops'in data:control.bind_prepared_scalar_stops(data['scalar_stops'])
    if initial_level is None:
        for level in levels:base_at(level);static[level]
    else:
        _require(initial_level in levels,'Known initial source level required');base_at(initial_level);static[initial_level]
    if progress:progress({'phase':'compact_static_geometry_ready','loaded_levels':list(loaded),'native_bodies':len(mesh.scene['groups'])})
    rays=None
    if 'static-returns.json'in report['files']:
        ref=report['files']['static-returns.json'];raw=(path.parent/'static-returns.json').read_bytes()
        _require(len(raw)==ref['bytes']and _sha(raw)==ref['sha256'],'Static ray capsule changed')
        rays=_typed_bytes(raw)
    return{'nav':nav,'graph':graph,'catalog':catalog,'planner':planner,'geometry_checks':checker,
        'scan_geometry':scan_geometry,'scan_indices':{'static':static,'cabin':cabin,'landings':landings},
        'zone_regions':data['zone_regions'],'static_ray_cache':rays}


def _direction_fingerprint(world,yaw):
    raw=b''.join(struct.pack('>dd',math.cos(yaw+angle),math.sin(yaw+angle))for angle,_,_ in world._beam_angles)
    return _sha(raw)


def seed_static_rays(world,capsule):
    """Seed only exact, same-index, same-trig static math; never peer returns."""
    if capsule is None:return{'seeded':0,'trig_mismatches':0,'index_mismatches':0}
    from building_fleet_control import preparation_digest
    _require(capsule.get('format')=='solidcraftbot.building-fleet-static-rays/1'
        and capsule.get('no_peer_data')is True and capsule.get('no_observation_times')is True
        and capsule['settings_sha256']==preparation_digest(world.settings),'Source-bound pure static ray capsule required')
    stats={'seeded':0,'trig_mismatches':0,'index_mismatches':0};fingerprints={}
    for row in capsule['rows']:
        level=row['level'];x,y,yaw=row['pose_mm_rad'];static=world.static[level]
        landing=world.landings[level,row['landing_sides']]
        cabin=world.cabin[row['cabin_sides']]if row['cabin_sides']is not None else None
        actual=[getattr(index,'_runtime_static_index_binding',None)if index is not None else None for index in(static,landing,cabin)]
        if actual!=row['index_bindings']:stats['index_mismatches']+=1;continue
        key=world._exact_key(yaw)
        if key not in fingerprints:fingerprints[key]=_direction_fingerprint(world,yaw)
        if fingerprints[key]!=row['directions_sha256']:stats['trig_mismatches']+=1;continue
        values=tuple(row['distances_mm']);sensor_range=world.settings['range_mm']
        _require(len(values)==len(world._beam_angles)and all(type(v)in(int,float)and math.isfinite(v)and 0<=v<=sensor_range for v in values),'Complete finite static distances within source range required')
        cache_key=(world._exact_key((x,y,yaw,sensor_range)),static,landing,cabin)
        world._static_cache[cache_key]=values;world._static_cache.move_to_end(cache_key);stats['seeded']+=1
        if len(world._static_cache)>world._static_cache_limit:world._static_cache.popitem(last=False)
    return stats
