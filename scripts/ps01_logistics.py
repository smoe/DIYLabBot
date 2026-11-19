"""Persistent synthetic PS01/TR01 logistics in the existing owner journal.

Typed inventory, consumable requests and local/mobile transfers share one root.
The existing async reducer owns every transfer. No network or motor is driven.
"""
import copy
import math
from pathlib import Path
import uuid

import async_transport_domain as domain
import async_transport_adapters as adapters
import pipetting_station as station
import pipetting_protocol
import transport_cargo as cargo
from async_transport import verify_sources
from manual_tasks import TaskError, digest, encoded

ROOT = station.ROOT
SOURCE = ROOT / 'model/ps01-logistics.shared.json'
FORMAT = 'solidcraftbot.ps01-logistics-state/1'
VARIANTS = ('tip_10_ul', 'tip_200_ul', 'tip_1000_ul')
require, exact, ident = domain.require, domain.exact, domain.ident
CHECKS = ('identity_confirmed', 'supported', 'gripper_empty', 'arm_clear',
          'stationary_hold', 'load_secured')


def definition(source=SOURCE):
    path = Path(source).resolve()
    require(path.is_relative_to(ROOT), 'Repository logistics source required')
    spec = domain._json(path.read_bytes())
    exact(spec, 'format id mode status sources owner_principal stations handoff_ports adapter fixture supply_station limitations', 'logistics source')
    require(spec['format'] == 'solidcraftbot.ps01-logistics/1' and spec['mode'] == 'synthetic_only',
            'Explicit synthetic logistics source required')
    exact(spec['sources'], 'setup handling vehicle tips transport', 'source bindings')
    for ref in spec['sources'].values():
        station.bound(ref)
    contract = station.bound(spec['sources']['transport'])
    exact(contract, 'format id mode base manifest_format payload_kinds limitations', 'cargo contract')
    require(contract['format'] == 'solidcraftbot.labware-transport-protocol/1'
            and contract['mode'] == 'synthetic_only' and contract['manifest_format'] == cargo.FORMAT
            and contract['payload_kinds'] == list(cargo.KINDS), 'Unsupported typed cargo contract')
    require(station.bound(contract['base']) == {k: v for k, v in domain.load_contract().items() if k != 'source_sha256'},
            'Unchanged base transport contract required')
    context = station.compile_setup(station.assembly.validate_reference(spec['sources']['setup']))
    require(context['handling']['source'] == station.bound(spec['sources']['handling'])
            and context['tip_source'] == station.bound(spec['sources']['tips']), 'One handling and tip source required')
    ids = set()
    for item in spec['stations']:
        exact(item, 'id worktop_xyz_mm dock_xy_mm', 'station instance'); ident(item['id'])
        require(item['id'] not in ids, 'Duplicate station'); ids.add(item['id'])
        for key, length in [('worktop_xyz_mm', 3), ('dock_xy_mm', 2)]:
            require(isinstance(item[key], list) and len(item[key]) == length
                    and all(type(v) in (int, float) and math.isfinite(v) for v in item[key]), 'Finite station placement required')
    require(len(ids) >= 2 and spec['supply_station'] in ids, 'Two stations and a known supply station required')
    require(len(spec['handoff_ports']) == 3 and {p['port'] for p in spec['handoff_ports']} == {'InfeedTips','InfeedRack','Outfeed'}, 'Three explicit handoff port poses required')
    for port in spec['handoff_ports']:
        exact(port, 'port xy_mm', 'handoff port pose')
        require(isinstance(port['xy_mm'], list) and len(port['xy_mm']) == 2
                and all(type(v) in (int,float) and math.isfinite(v) for v in port['xy_mm']), 'Finite port coordinates required')
    adapter = spec['adapter']
    exact(adapter, 'recipe bay_index base_thickness_mm locator_clearance_mm locator_height_mm locator_thickness_mm retention box_geometry_basis', 'TR01 adapter')
    require(adapter['recipe'] == 'tr01_lt01_supported_nest/1' and type(adapter['bay_index']) is int
            and adapter['bay_index'] in (0, 1) and adapter['retention'] == 'manual_fixture_confirmation'
            and adapter['box_geometry_basis'] == 'unmeasured_existing_LT01_envelope', 'Supported unqualified adapter required')
    require(all(type(adapter[k]) in (int, float) and math.isfinite(adapter[k]) and 0 < adapter[k] <= 20
                for k in ('base_thickness_mm', 'locator_clearance_mm', 'locator_height_mm', 'locator_thickness_mm')), 'Bounded adapter dimensions required')
    topology = {'owner_principal': spec['owner_principal'], 'protocol': spec['sources']['transport'],
                'racks': [], 'endpoints': [], 'agents': [{'id': 'TR01', 'kind': 'robot', 'principal': 'TR01.Mock'}]}
    ports = ['InfeedTips', 'InfeedRack', 'Outfeed', *('S%02d' % i for i in range(1, 10))]
    fixed_ports={host.split('.',1)[1] for host,occupant in context['handling']['occupied'].items()
                 if occupant.startswith('fixed:')}
    for identity in sorted(ids):
        topology['agents'].append({'id': identity + 'TransferArm', 'kind': 'robot', 'principal': identity + '.ArmMock'})
        for port in ports:
            if port in fixed_ports:
                continue
            topology['endpoints'].append({'id': identity + '.' + port, 'site_id': spec['id'], 'lab_id': identity,
                                         'holder_id': identity + '.Worktop', 'place_id': port,
                                         'principal': identity + '.Endpoint'})
    initial = {}
    for item in spec['fixture']:
        common = 'id prototype payload_id initial_endpoint kind'
        exact(item, common + (' variant used_tip_count' if item['kind'] == 'tip_box' else ' vessels' if item['kind'] == 'tube_rack' else ''), 'fixture carrier')
        for key in ('id', 'payload_id'):
            ident(item[key])
        require(item['id'] not in initial and item['kind'] in cargo.KINDS
                and item['prototype'] in context['handling']['carriers'], 'Unique known cargo prototype required')
        proto = context['handling']['carriers'][item['prototype']]
        proto_kind = proto['payload']['kind']
        require((item['kind'] == 'tip_box' and proto_kind in ('existing_tip_stock', 'tip_reserve'))
                or (item['kind'] == 'well_plate' and proto_kind == 'existing_labware')
                or (item['kind'] == 'tube_rack' and proto_kind == 'guided_rack'), 'Cargo/prototype kind mismatch')
        manifest = {'format': cargo.FORMAT, 'carrier_id': item['id'], 'payload_id': item['payload_id'],
                    'payload_kind': item['kind'], 'variant': item.get('variant'), 'content_revision': 0,
                    'vessels': copy.deepcopy(item.get('vessels', [])), 'wells': [], 'tips': []}
        if item['kind'] == 'tip_box':
            require(item['variant'] == proto['content']['variant'] and type(item['used_tip_count']) is int
                    and 0 <= item['used_tip_count'] <= 96, 'Matching tip variant and explicit used count required')
            slots = station.tips.slot_ids(context['tip_source'], item['variant'])
            manifest['tips'] = [{'place_id': place, 'tip_id': item['payload_id'] + '.' + place,
                                 'state': 'used' if index < item['used_tip_count'] else 'unused'} for index, place in enumerate(slots)]
        elif item['kind'] == 'well_plate':
            manifest['wells'] = [{'place_id': place, 'content_revision': 0, 'materials': []} for place in proto['content']['wells']]
        else:
            require(all(v['place_id'] in proto['content']['slots'] for v in manifest['vessels']), 'Unknown rack slot')
        manifest = cargo.normalize(manifest); domain._manifest(manifest)
        initial[item['id']] = {'manifest': manifest, 'closure': 'closed', 'quality': 'usable'}
        topology['racks'].append({'id': item['id'], 'initial_endpoint': item['initial_endpoint'], 'closed': True})
    domain._validate_topology(topology)
    # Capture transitive leading sources and the implementation, not native CAD.
    paths = set(station.source_paths()) | {path, domain.PROTOCOL, domain.CARGO_PROTOCOL,ROOT/'model/ps01-logistics.schema.json'}
    for ref in spec['sources'].values():
        paths.add(station.assembly.validate_reference(ref))
    paths.update(ROOT / 'scripts' / name for name in ('ps01_logistics.py', 'run_ps01_logistics.py',
        'transport_cargo.py', 'async_transport_domain.py', 'async_transport_adapters.py', 'async_transport.py',
        'manual_tasks.py', 'pipetting_protocol.py'))
    result = {'source': spec, 'topology': topology, 'initial_cargo': initial,
              'source_files_sha256': {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(paths)}}
    verify_sources(result)
    return result


def manifests(state):
    return {key: value['manifest'] for key, value in state['cargo'].items()}


def endpoint_station(state, endpoint):
    endpoints = domain._items(state['definition']['topology'], 'endpoints')
    require(endpoint in endpoints, 'Unknown endpoint')
    return endpoints[endpoint]['lab_id']


def on_deck(state, carrier, station_id):
    place = state['transport']['rack_placements'][carrier]
    return place['kind'] == 'endpoint' and place['endpoint_id'] in {station_id + '.S%02d' % n for n in range(1, 10)}


def idle_cargo(state, carrier):
    queue = state['transport']
    require(carrier in state['cargo'], 'Unknown carrier')
    require(not any(job['rack_id'] == carrier and (job['phase'] not in domain.TERMINAL or job['control'] == 'held')
                    for job in queue['jobs'].values()), 'Carrier has an active or unresolved transport')
    require(not any(use['carrier_id'] == carrier and use['status'] == 'intended' for use in state['tip_uses'].values()),
            'Unresolved tip-use intent holds this carrier')


def sync(state):
    if not state['admitted']:
        state['resources'] = []
        return
    state['resources'] = sorted(set(domain.embedded_resources(state['transport'], state['definition']['topology'], manifests(state))))
    state['resources'].append('fixture:' + state['definition']['source']['id'])
    zones={endpoint_station(state,job[key]) for job in state['transport']['jobs'].values()
           if job['phase'] not in domain.TERMINAL or job['control']=='held'
           for key in ('source_endpoint','target_endpoint')}
    zones.update(use['station'] for use in state['tip_uses'].values() if use['status']=='intended')
    state['resources'].extend('zone:'+state['definition']['source']['id']+':'+zone for zone in sorted(zones))
    state['resources'].sort()


def audit(state):
    exact(state, 'format run_id session definition admitted cargo transport demands tip_uses requests access resources', 'logistics root')
    require(state['format'] == FORMAT and type(state['admitted']) is bool, 'Logistics root version required')
    ident(state['run_id']); ident(state['session'])
    for key in ('cargo', 'demands', 'tip_uses', 'requests', 'access'):
        require(isinstance(state[key], dict), 'Root map required')
    if not state['admitted']:
        require(state['transport'] is None and not state['cargo'] and not state['resources'], 'Unadmitted root must hold no inventory')
        return
    require(state['transport']['session'] == state['session'], 'Root/queue session mismatch')
    initial = state['definition']['initial_cargo']
    require(set(state['cargo']) == set(initial), 'Cargo completeness mismatch')
    for cid, current in state['cargo'].items():
        exact(current, 'manifest closure quality', 'owned cargo'); domain._manifest(current['manifest'])
        require(current['closure'] in ('closed', 'open', 'unknown') and current['quality'] in ('usable', 'quarantined', 'unknown'), 'Explicit cargo condition required')
        require(cargo.identities(current['manifest']) == cargo.identities(initial[cid]['manifest']), 'Cargo identity drift')
        expected = copy.deepcopy(initial[cid]['manifest'])
        for use in state['tip_uses'].values():
            if use['carrier_id'] != cid or use['status'] != 'confirmed':
                continue
            for tip_id in use['tip_ids']:
                tip = next((t for t in expected['tips'] if t['tip_id'] == tip_id), None)
                require(tip is not None and tip['state'] == 'unused', 'Repeated or unknown tip consumption')
                tip['state'] = 'used'
            expected['content_revision'] += 1
        require(current['manifest'] == expected, 'Inventory differs from admitted stock plus confirmed consumption')
    domain.embedded_audit(state['transport'], state['definition']['topology'], manifests(state))
    assigned = []
    for demand in state['demands'].values():
        require(demand['variant'] in VARIANTS and type(demand['boxes']) is int and 1 <= demand['boxes'] <= 1000,
                'Invalid supply demand')
        require(len(demand['allocations']) <= demand['boxes'], 'Demand overallocated')
        for cid, jobs in demand['allocations'].items():
            require(cid in state['cargo'] and state['cargo'][cid]['manifest']['variant'] == demand['variant'], 'Wrong supply variant')
            require(all(j in state['transport']['jobs'] and state['transport']['jobs'][j]['rack_id'] == cid for j in jobs), 'Unbound supply job')
            assigned.append(cid)
    require(len(assigned) == len(set(assigned)), 'Box assigned to multiple demands')
    pending = []
    for use in state['tip_uses'].values():
        require(use['status'] in ('intended', 'confirmed', 'not_performed'), 'Unknown tip-use outcome')
        if use['status'] == 'intended':
            require(not any(j['rack_id'] == use['carrier_id'] and j['phase'] not in domain.TERMINAL for j in state['transport']['jobs'].values()), 'Transport overlaps unresolved consumption')
            pending.extend(use['tip_ids'])
    require(len(pending) == len(set(pending)), 'Overlapping tip-use reservations')
    expected = copy.deepcopy(state); sync(expected)
    require(state['resources'] == expected['resources'], 'Root holds differ from cargo/transport')


def available_tips(state, station_id):
    counts = dict.fromkeys(VARIANTS, 0)
    pending = {tip for use in state['tip_uses'].values() if use['status'] == 'intended' for tip in use['tip_ids']}
    for cid, record in state['cargo'].items():
        m = record['manifest']
        if m['payload_kind'] != 'tip_box' or record['quality'] != 'usable' or not on_deck(state, cid, station_id):
            continue
        if any(cid in demand['allocations'] and demand['station'] != station_id for demand in state['demands'].values()):
            continue
        try:
            idle_cargo(state, cid)
        except TaskError:
            continue
        counts[m['variant']] += sum(t['state'] == 'unused' and t['tip_id'] not in pending for t in m['tips'])
    return counts


def demand_status(state, demand):
    deliveries, ready, held = [], [], []
    for cid, job_ids in demand['allocations'].items():
        jobs = [state['transport']['jobs'][j] for j in job_ids]
        related = [j for j in state['transport']['jobs'].values() if j['rack_id'] == cid]
        if (any(j['control'] == 'held' for j in related) or state['cargo'][cid]['quality'] != 'usable'
                or any(j['phase'] in ('cancelled', 'cancelled_reconciled') for j in jobs)):
            held.append(cid); continue
        if any(j['agent_id'] == 'TR01' and j['phase'] == 'completed' and j['target_endpoint'] == demand['destination'] for j in jobs):
            deliveries.append(cid)
            # Fulfilment is historical. Later consumption/return does not reopen
            # this demand or let an old request cover a new need.
            if any(j['phase'] == 'completed' and j['source_endpoint'] == demand['destination']
                   and j['target_endpoint'] in {demand['station'] + '.S%02d' % n for n in range(1, 10)} for j in related):
                ready.append(cid)
    return {'delivered': deliveries, 'ready': ready, 'held': held,
            'status': 'cancelled' if demand['waiting_reason'] == 'cancelled' else 'needs_reconciliation' if held else 'ready' if len(ready) == demand['boxes'] else
                      'delivered' if len(deliveries) == demand['boxes'] else 'pending',
            'unallocated_boxes': demand['boxes'] - len(demand['allocations'])}


def forecast(state, station_id, protocol=None, context=None):
    require(state['admitted'], 'Admitted inventory required for a supply forecast')
    endpoint_station(state, station_id + '.InfeedTips')
    need = pipetting_protocol.compile_protocol(protocol=protocol, context=context, demand_only=True)
    available = available_tips(state, station_id)
    result = {}
    for variant in VARIANTS:
        outstanding = sum(d['boxes'] - len(demand_status(state, d)['ready']) for d in state['demands'].values()
                          if d['station'] == station_id and d['variant'] == variant and demand_status(state, d)['status'] not in ('cancelled', 'needs_reconciliation'))
        deficit = max(0, need['required_tips'][variant] - available[variant])
        result[variant] = {'required_tips': need['required_tips'][variant], 'available_on_deck': available[variant],
                           'deficit_tips': deficit, 'already_requested_boxes': outstanding,
                           'additional_full_boxes': math.ceil(max(0, deficit - outstanding * 96) / 96)}
    return {'format': 'solidcraftbot.ps01-supply-forecast/1', 'station': station_id, 'variants': result,
            'inventory_reserved': False, 'scope': 'Read-only demand; outstanding requests suppress duplicates but never count as pipettable stock.'}


class Logistics:
    def __init__(self, journal, run_id, session=None):
        self.journal, self.run_id, self.session = journal, run_id, session
        self._load(verify=True)

    def _load(self, verify=False):
        state, revision = self.journal.get_current(self.run_id, verify=verify)
        audit(state); verify_sources(state['definition'])
        return state, revision

    @property
    def state(self):
        return self._load()[0]

    @classmethod
    def create(cls, journal, run_id, source=SOURCE):
        ident(run_id); session = uuid.uuid4().hex
        state = {'format': FORMAT, 'run_id': run_id, 'session': session, 'definition': definition(source),
                 'admitted': False, 'cargo': {}, 'transport': None, 'demands': {}, 'tip_uses': {},
                 'requests': {}, 'access': {}, 'resources': []}
        audit(state); journal.create(run_id, state, immutable_definition=True)
        return cls(journal, run_id, session)

    @classmethod
    def open(cls, journal, run_id, *, resume=False):
        obj = cls(journal, run_id)
        if resume:
            before, revision = obj._load(verify=True); after = copy.deepcopy(before)
            after['session'] = uuid.uuid4().hex
            if after['admitted']:
                after['transport'] = domain.embedded_apply(after['transport'], 'resume', {'session': after['session']},
                    after['definition']['topology']['owner_principal'], after['definition']['topology'], manifests(after))
                after['access'] = {}
            sync(after); audit(after)
            journal.append(run_id, revision, 'logistics.resume', {'evidence': 'explicit_owner_resume'}, after)
            obj.session = after['session']
        return obj

    def _queue(self, state, operation, args, principal=None):
        topology = state['definition']['topology']
        state['transport'] = domain.embedded_apply(state['transport'], operation, args,
            principal or topology['owner_principal'], topology, manifests(state))

    def _clear(self, state, station_id):
        require(state['access'].get(station_id) == {'workspace_clear': True, 'pipetting_parked': True,
                'transfer_parked': True, 'evidence': 'test_fixture'}, 'Current explicit clear/park observations required for ' + station_id)

    def _prepare(self, state, cid, target, job_id, mobile):
        idle_cargo(state, cid)
        record = state['cargo'][cid]
        require(record['quality'] == 'usable' and record['closure'] == 'closed', 'Closed usable cargo required')
        place = state['transport']['rack_placements'][cid]
        require(place['kind'] == 'endpoint', 'Confirmed source endpoint required')
        source = place['endpoint_id']; a = endpoint_station(state, source); b = endpoint_station(state, target)
        self._clear(state, a); self._clear(state, b)
        require(not any(use['status']=='intended' and use['station'] in {a,b} for use in state['tip_uses'].values()),
                'Unresolved pipetting intent holds station workspace')
        for other in state['transport']['jobs'].values():
            if other['phase'] in domain.TERMINAL and other['control']!='held':continue
            occupied={endpoint_station(state,other[key]) for key in ('source_endpoint','target_endpoint')}
            require(not occupied & {a,b}, 'Station handoff/workspace zone already held')
        require((a != b) == mobile, 'Local/mobile station binding mismatch')
        if mobile:
            require(source.endswith('.Outfeed') and target.endswith(('.InfeedRack', '.InfeedTips', '.Outfeed')),
                    'Mobile transport uses the registered source outfeed and destination handoff')
        if target.endswith('.InfeedTips'):
            require(record['manifest']['payload_kind'] == 'tip_box', 'Tip entrance accepts only tip boxes')
        if target.endswith('.InfeedRack'):
            require(record['manifest']['payload_kind'] != 'tip_box', 'Rack entrance does not accept tip boxes')
        for op, args in [('request', {'job_id': job_id, 'rack_id': cid, 'target_endpoint': target,
                                     'agent_id': 'TR01' if mobile else a + 'TransferArm'}),
                         ('reserve', {'job_id': job_id}), ('prepare', {'job_id': job_id})]:
            self._queue(state, op, args)

    def _apply(self, state, operation, args, principal):
        owner = state['definition']['topology']['owner_principal']
        if operation not in ('observe', 'worker_claim'):
            require(principal == owner, 'Logistics owner required')
        if operation == 'admit':
            exact(args, 'evidence', 'admission'); require(args['evidence'] == 'test_fixture' and not state['admitted'], 'One explicit fixture admission required')
            state['cargo'] = copy.deepcopy(state['definition']['initial_cargo']); state['admitted'] = True
            state['transport'] = domain.embedded_initial(state['definition']['topology'], manifests(state), state['run_id'], state['session'])
            return {'admitted': True}
        require(state['admitted'], 'Admit the fixture before use')
        if operation == 'access':
            exact(args, 'station workspace_clear pipetting_parked transfer_parked evidence', 'access observation')
            require(args['station'] in {s['id'] for s in state['definition']['source']['stations']}
                    and args['evidence'] == 'test_fixture'
                    and all(type(args[k]) is bool for k in ('workspace_clear', 'pipetting_parked', 'transfer_parked')), 'Explicit fixture access observations required')
            state['access'][args['station']] = {k: v for k, v in args.items() if k != 'station'}
        elif operation == 'condition':
            exact(args, 'carrier_id closure quality evidence', 'cargo observation'); idle_cargo(state, args['carrier_id'])
            require(args['evidence'] == 'test_fixture' and args['closure'] in ('closed', 'open', 'unknown')
                    and args['quality'] in ('usable', 'quarantined', 'unknown'), 'Explicit fixture cargo condition required')
            state['cargo'][args['carrier_id']].update(closure=args['closure'], quality=args['quality'])
        elif operation == 'transfer':
            exact(args, 'carrier_id target job_id mobile', 'transfer request')
            require(type(args['mobile']) is bool, 'Explicit transfer mode required')
            allocated = {cid for d in state['demands'].values() for cid in d['allocations']}
            require(args['carrier_id'] not in allocated or any(args['carrier_id'] in demand_status(state, d)['delivered'] for d in state['demands'].values()),
                    'Supply allocation must be dispatched through its demand')
            self._prepare(state, args['carrier_id'], args['target'], args['job_id'], args['mobile'])
        elif operation == 'request_tips':
            exact(args, 'demand_id station variant boxes reason', 'tip request')
            ident(args['demand_id']); domain.reason_text(args['reason'])
            require(args['demand_id'] not in state['demands'] and args['variant'] in VARIANTS
                    and type(args['boxes']) is int and 1 <= args['boxes'] <= 1000, 'Unique demand, supported class and positive box count required')
            destination = args['station'] + '.InfeedTips'; endpoint_station(state, destination)
            require(args['station'] != state['definition']['source']['supply_station'], 'Supply must target a different station')
            state['demands'][args['demand_id']] = {**copy.deepcopy(args), 'destination': destination, 'allocations': {}, 'waiting_reason': 'not_scheduled'}
        elif operation == 'serve':
            exact(args, 'demand_id job_id', 'supply scheduling'); ident(args['job_id'])
            require(args['demand_id'] in state['demands'], 'Unknown demand')
            demand = state['demands'][args['demand_id']]; status = demand_status(state, demand)
            require(status['status'] != 'cancelled', 'Cancelled demand cannot be rescheduled')
            require(not status['held'], 'Supply has an unresolved prior attempt')
            assigned = {cid for d in state['demands'].values() for cid in d['allocations']}
            supply = state['definition']['source']['supply_station']
            for cid, record in sorted(state['cargo'].items()):
                if len(demand['allocations']) == demand['boxes']:
                    break
                place = state['transport']['rack_placements'][cid]; m = record['manifest']
                if cid in assigned or m['variant'] != demand['variant'] or record['quality'] != 'usable' or record['closure'] != 'closed':
                    continue
                if place['kind'] != 'endpoint' or endpoint_station(state, place['endpoint_id']) != supply or not all(t['state'] == 'unused' for t in m['tips']):
                    continue
                try:
                    idle_cargo(state, cid)
                except TaskError:
                    continue
                demand['allocations'][cid] = []; assigned.add(cid)
            pending = [cid for cid, jobs in demand['allocations'].items() if cid not in status['delivered']]
            demand['waiting_reason'] = 'stock_shortage' if not pending else 'transport_or_destination_busy'
            for cid in pending:
                place = state['transport']['rack_placements'][cid]
                if place['kind'] != 'endpoint':
                    continue
                target = demand['destination'] if place['endpoint_id'] == supply + '.Outfeed' else supply + '.Outfeed'
                # A failed scheduling proposal must not leave a requested job.
                proposal = copy.deepcopy(state)
                try:
                    self._prepare(proposal, cid, target, args['job_id'], target == demand['destination'])
                except TaskError as error:
                    demand['waiting_reason'] = str(error)
                    continue
                proposal['demands'][args['demand_id']]['allocations'][cid].append(args['job_id'])
                proposal['demands'][args['demand_id']]['waiting_reason'] = None
                state.clear(); state.update(proposal)
                return {'job_id': args['job_id'], 'carrier_id': cid}
            return {'job_id': None, 'waiting_reason': demand['waiting_reason']}
        elif operation == 'cancel_demand':
            exact(args, 'demand_id reason', 'demand cancellation'); domain.reason_text(args['reason'])
            require(args['demand_id'] in state['demands'], 'Unknown demand')
            demand = state['demands'][args['demand_id']]
            for jobs in demand['allocations'].values():
                require(not any(state['transport']['outbox'].get(j, {}).get('status') in ('dispatched', 'uncertain') for j in jobs), 'Dispatched supply requires explicit transport reconciliation')
                for job in jobs:
                    if state['transport']['jobs'][job]['phase'] not in domain.TERMINAL:
                        self._queue(state, 'cancel', {'job_id': job, 'reason': args['reason']})
            demand['allocations'] = {}; demand['waiting_reason'] = 'cancelled'
        elif operation == 'begin_tip_use':
            exact(args, 'use_id carrier_id station tip_ids', 'tip-use intent'); ident(args['use_id'])
            require(args['use_id'] not in state['tip_uses'], 'Tip-use intent already exists')
            cid = args['carrier_id']; idle_cargo(state, cid); self._clear(state, args['station'])
            require('zone:'+state['definition']['source']['id']+':'+args['station'] not in state['resources'],
                    'Station workspace is held by another operation')
            require(not any(cid in d['allocations'] and args['station'] != d['station'] for d in state['demands'].values()),
                    'Supply allocation holds these tips for the requesting station')
            record = state['cargo'][cid]
            require(on_deck(state, cid, args['station']) and record['closure'] == 'open' and record['quality'] == 'usable', 'Open, identified, seated tip box required')
            available = {t['tip_id'] for t in record['manifest']['tips'] if t['state'] == 'unused'}
            require(isinstance(args['tip_ids'], list) and args['tip_ids'] and len(args['tip_ids']) == len(set(args['tip_ids']))
                    and set(args['tip_ids']) <= available, 'Explicit unused tip identities required')
            state['tip_uses'][args['use_id']] = {**copy.deepcopy(args), 'status': 'intended'}
        elif operation == 'confirm_tip_use':
            exact(args, 'use_id outcome tip_ids evidence', 'tip-use observation')
            require(args['use_id'] in state['tip_uses'] and args['evidence'] == 'test_fixture', 'Explicit fixture observation required')
            use = state['tip_uses'][args['use_id']]
            require(use['status'] == 'intended' and args['tip_ids'] == use['tip_ids'] and args['outcome'] in ('performed', 'not_performed'), 'Matching unresolved tip-use intent required')
            if args['outcome'] == 'performed':
                m = state['cargo'][use['carrier_id']]['manifest']
                for tip in m['tips']:
                    if tip['tip_id'] in use['tip_ids']:
                        require(tip['state'] == 'unused', 'Tip already consumed'); tip['state'] = 'used'
                m['content_revision'] += 1
            use['status'] = 'confirmed' if args['outcome'] == 'performed' else 'not_performed'
        elif operation in ('mark_dispatched', 'worker_claim', 'observe', 'hold', 'cancel', 'reconcile'):
            data = copy.deepcopy(args)
            if operation == 'mark_dispatched':
                job = state['transport']['jobs'][args['job_id']]
                self._clear(state, endpoint_station(state, job['source_endpoint']))
                self._clear(state, endpoint_station(state, job['target_endpoint']))
            if operation == 'observe':
                exact(data, 'job_id observation checks', 'handover observation')
                checks = data.pop('checks'); exact(checks, (*CHECKS, 'evidence'), 'handover checks')
                require(checks['evidence'] == 'test_fixture' and all(type(checks[k]) is bool for k in CHECKS), 'Explicit fixture handover checks required')
                if not all(checks[k] for k in CHECKS):
                    env = domain.embedded_envelope(state['transport'], data['job_id'], state['definition']['topology'])
                    require(principal == domain.principal_for(env, data['observation']['role']), 'Unauthorized observation')
                    self._queue(state, 'hold', {'job_id': data['job_id'], 'reason': 'failed_handover_observation'})
                    return {'held': True}
            if operation == 'reconcile':
                exact(data, 'job_id outcome location manifest reason evidence', 'reconciliation')
                require(data.pop('evidence') == 'test_fixture', 'Explicit external fixture reconciliation required')
            self._queue(state, operation, data, principal)
        else:
            raise TaskError('Unknown logistics operation: ' + operation)
        return {'operation': operation, 'job_id': args.get('job_id')}

    def act(self, operation, request_id, *, principal=None, **args):
        ident(request_id)
        before, revision = self._load(); require(self.session is not None and self.session == before['session'], 'Explicit current owner session required')
        principal = principal or before['definition']['topology']['owner_principal']; ident(principal)
        fingerprint = domain.hashed({'operation': operation, 'principal': principal, 'args': args})
        previous = before['requests'].get(request_id)
        if previous:
            require(previous['fingerprint'] == fingerprint, 'Request ID reused with different arguments')
            return copy.deepcopy(previous['result'])
        after = copy.deepcopy(before); result = self._apply(after, operation, args, principal)
        after['requests'][request_id] = {'operation': operation, 'principal': principal, 'arguments': copy.deepcopy(args),
                                       'fingerprint': fingerprint, 'result': copy.deepcopy(result)}
        sync(after); audit(after); verify_sources(after['definition'])
        artifact = encoded({'principal': principal, 'operation': operation, 'arguments': args}).encode()
        self.journal.append(self.run_id, revision, 'logistics.' + operation,
            {'request_id': request_id, 'artifact_sha256': digest(artifact), 'evidence': 'synthetic_request'}, after, artifact=artifact)
        return result

    def dispatch_mock(self, job_id, request_id, *, order=None):
        # Only a committed first dispatch invokes the adapter. Read/replay never does.
        before = self.state
        replay = request_id in before['requests']
        self.act('mark_dispatched', request_id, job_id=job_id)
        if replay:
            return []
        current = self.state
        require(self.session == current['session'] and current['transport']['outbox'][job_id]['status'] == 'dispatched'
                and current['transport']['jobs'][job_id]['control'] == 'active', 'Dispatch superseded')
        env = domain.embedded_envelope(current['transport'], job_id, current['definition']['topology'])
        adapter = adapters.RobotTeleportMock(env['agent_id'], order=order)
        batch = adapter.submit(env)
        for message in batch:
            if message['operation'] == 'observe':
                message['args']['checks'] = {**dict.fromkeys(CHECKS, True), 'evidence': 'test_fixture'}
        return batch

    def ingest_mock(self, batch):
        require(isinstance(batch, list), 'Explicit fixture messages required')
        for message in batch:
            exact(message, 'principal request_id operation args', 'fixture message')
            require(message['operation'] in ('observe', 'worker_claim'), 'Fixture may only claim or attest')
            self.act(message['operation'], message['request_id'], principal=message['principal'], **message['args'])

    def report(self):
        with self.journal._reading():
            trace = self.journal.history(self.run_id)
            for event in trace:
                audit(event['state'])
                if event['payload'].get('artifact_sha256'):
                    self.journal.artifact(event['payload']['artifact_sha256'])
            state = trace[-1]['state']; verify_sources(state['definition'])
            held = {key for key, owner in self.journal.owners().items() if owner == self.run_id}
            require(held == set(state['resources']), 'Persisted resources differ from owner holds')
            return {'format': 'solidcraftbot.ps01-logistics-report/1', 'run_id': self.run_id,
                    'mode': 'synthetic_only', 'admitted': state['admitted'], 'journal_events': len(trace),
                    'jobs': copy.deepcopy(state['transport']['jobs']) if state['admitted'] else {},
                    'placements': copy.deepcopy(state['transport']['rack_placements']) if state['admitted'] else {},
                    'tip_availability': {s['id']: available_tips(state, s['id']) for s in state['definition']['source']['stations']} if state['admitted'] else {},
                    'demands': {key: {**copy.deepcopy(value), **demand_status(state, value)} for key, value in state['demands'].items()},
                    'source_files_sha256': state['definition']['source_files_sha256'],
                    'motion_executed': False, 'hardware_executed': False, 'network_executed': False,
                    'cross_run_stock_implemented': False, 'scope': 'One durable synthetic owner; zero-time transport receipts are separate from CAD/motion evidence.'}
