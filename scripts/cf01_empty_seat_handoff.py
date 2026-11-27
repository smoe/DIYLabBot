"""Opt-in local CF01 empty-seat support handoff. No transport or hardware."""

import json
import time

import assembly_model as assembly
import centrifuge_model as model
from centrifuge_control import COMMAND_ARGUMENTS, Simulator, positive, require
from centrifuge_protocol import SOURCE as BASE_PROTOCOL


SOURCE = model.ROOT / 'model/cf01-empty-seat-handoff.protocol.json'
COMMANDS = {
    'begin_raise_empty_support': ('empty_confirmed',),
    'confirm_empty_support_extended': ('extended_confirmed',),
    'confirm_tube_on_support': ('rested_confirmed', 'released_confirmed', 'cap_closed_confirmed', 'mass_g'),
    'begin_lower_supported_tube': ('workspace_clear_confirmed',),
    'confirm_supported_tube_seated': ('seated_confirmed',),
    'confirm_empty_support_parked': ('parked_confirmed',),
}


class EmptySeatHandoffSimulator(Simulator):
    """Retain existing guards and keep a separate supported-tube state."""

    def __init__(self, spec=None, clock=time.monotonic, qualification=None, auto_feedback=True, initial_slots=None):
        contract = json.loads(SOURCE.read_text(encoding='utf-8'))
        if (contract['format'] != 'solidcraftbot.cf01-empty-seat-handoff/1'
                or set(contract['sources']) != {'station', 'protocol'}
                or assembly.validate_reference(contract['sources']['station']) != model.SOURCE
                or assembly.validate_reference(contract['sources']['protocol']) != BASE_PROTOCOL
                or COMMANDS.keys() & COMMAND_ARGUMENTS.keys()):
            raise ValueError('A separate handoff must bind the exact standard CF01 sources')
        station = model.load()
        if spec is not None and spec != station:
            raise ValueError('The empty-seat handoff requires the pinned CF01 model')
        self.handoff = None
        super().__init__(spec=station, clock=clock, qualification=qualification, auto_feedback=auto_feedback,
                         initial_slots=initial_slots)
        self.open_angle_deg = model.pose(self.spec, self.p, 'open')['Lid']

    def status(self):
        status = super().status()
        handoff = self.handoff
        status['pusher_handoff'] = None if handoff is None else dict(handoff)
        if handoff is not None:
            # Standard pickup targets do not confer ownership during this
            # opt-in lowering operation.
            status['grip_frame']['valid'] = False
        return status

    def execute(self, command, token=None, **args):
        if command not in COMMANDS:
            if self.handoff is not None and command in COMMAND_ARGUMENTS and command not in {
                    'status', 'events', 'rotation_feedback', 'heartbeat', 'stop'}:
                self._sync()
                self._owner(token)
                require(False, 'InvalidState', 'Finish the active supported handoff before other CF01 operations')
            return super().execute(command, token, **args)

        self._sync()
        self._owner(token)
        require(self.fault is None, 'RecoveryRequired', 'Latched fault requires explicit recovery')
        required = COMMANDS[command]
        slot, sample = args.get('slot'), args.get('sample_id')
        require(set(args) == {'slot', 'sample_id', *required}
                and type(slot) is int and slot in self.slots and isinstance(sample, str) and bool(sample.strip()),
                'InvalidArgument', 'A typed indexed slot, synthetic tube identity and action observations are required')
        self._access()
        require(slot == self.indexed_slot, 'IndexMismatch', 'Requested pocket must match the secured index')
        require(self.lid_angle_deg == self.open_angle_deg and not self.locked
                and self.pins_retracted_confirmed and self.latch_positions == [self.p['latch_travel']] * 2
                and self.brake_engage_confirmed,
                'LidAccessFault', 'Fully open held lid, retracted pins and confirmed parking brake required')
        require(all(args[key] is True for key in required if key != 'mass_g'),
                'UnconfirmedTransfer', 'Every synthetic observation for the support action must be confirmed')
        item = self.slots[slot]
        if command == 'begin_raise_empty_support':
            require(self.handoff is None, 'InvalidState', 'A supported handoff is already active')
            self._clear()
            self._parked()
            require(item == {'present': False, 'seated': False, 'mass_g': None},
                    'InvalidState', 'Selected pocket must be known empty before raising its support')
            self.handoff = {'slot': slot, 'sample_id': sample, 'phase': 'raising'}
        else:
            handoff = self.handoff
            require(handoff is not None and (handoff['slot'], handoff['sample_id']) == (slot, sample),
                    'UnconfirmedTransfer', 'Action must match the selected handoff identity')
            if command == 'confirm_empty_support_extended':
                self._require_phase('raising')
                self._clear()
                require(not item['present'], 'InvalidState', 'Pocket changed during empty support extension')
                self.lift_mm = self.p['lift_travel']
                handoff['phase'] = 'extended_empty'
            elif command == 'confirm_tube_on_support':
                self._require_phase('extended_empty')
                require(not item['present'] and self.lift_mm == self.p['lift_travel'],
                        'InvalidState', 'Tube transfer requires the free fully extended support')
                mass = positive(args['mass_g'], 'synthetic total tube mass_g')
                item.update(present=True, seated=False, mass_g=mass)
                handoff['phase'] = 'supported'
            elif command == 'begin_lower_supported_tube':
                self._require_phase('supported')
                self._clear()
                require(item['present'] and not item['seated'] and self.lift_mm == self.p['lift_travel'],
                        'InvalidState', 'Lowering requires the confirmed tube on the extended support')
                handoff['phase'] = 'lowering'
            elif command == 'confirm_supported_tube_seated':
                self._require_phase('lowering')
                self._clear()
                require(item['present'] and not item['seated'],
                        'InvalidState', 'Seating must agree with the observed supported tube')
                self.lift_mm = 0
                item['seated'] = True
                handoff['phase'] = 'pocket_seated'
            else:
                self._require_phase('pocket_seated')
                self._clear()
                require(item['present'] and item['seated'] and self.lift_mm == 0,
                        'InvalidState', 'Support park requires the tube to be seated in the pocket')
                self.handoff = None
        self.event('CF01.empty_seat_handoff.' + command, slot=slot, sample_id=sample)
        return self.status()

    def _require_phase(self, phase):
        require(self.handoff['phase'] == phase, 'InvalidState', 'Expected supported handoff phase: ' + phase)
