"""Exercise the extended synthetic scan and checked drive at corridor speed."""
from pathlib import Path as FilePath
import sys
import unittest

sys.path.insert(0, str(FilePath(__file__).resolve().parents[1] / 'scripts'))
import building_fleet_model as model
from building_fleet_control import Controller, source_perception_limit
from building_fleet_geometry import vehicle_envelope
from building_fleet_motion import Path, compile_motion
from building_fleet_sim import SensorWorld


class CorridorSpeedTests(unittest.TestCase):
    def test_walking_speed_uses_the_checked_step_and_brake_controller(self):
        source = model.load()
        sensor = model.resolved_sensor(source)
        path = Path([[0., 0.], [0., 15000.]])
        radius = vehicle_envelope()['radius_mm']
        perception = source_perception_limit(source, radius)
        self.assertLess(perception['required_range_mm'], sensor['range_mm'])
        program = compile_motion(path, source, perception['applied_velocity_mm_s'])
        controller = Controller(path, source, motion_program=program)

        # Each empty scan is a fresh clear view down this obstacle-free test
        # straight. Delayed delivery follows the actual source sensor cadence.
        scan_stride = round(sensor['period_s'] / .05)
        latency_steps = round(sensor['latency_s'] / .05)
        scan = None
        for step in range(120):
            now = round(step * .05, 3)
            end = round(now + .05, 3)
            if step >= latency_steps and (step - latency_steps) % scan_stride == 0:
                scan = {'captured_s': round(now - sensor['latency_s'], 3),
                        'returns_local_mm': []}
            controller.decide(now, scan, grant_permits=True, step_end_s=end)
            controller.advance(now, end)
            if controller.v >= 1400:
                break
        self.assertGreaterEqual(controller.v, 1400)
        self.assertGreater(controller.perception_audit['minimum_range_margin_mm'], 0)
        self.assertIsNotNone(controller._fallback)

        at = controller.now
        blocked = {'captured_s': at, 'returns_local_mm': [[0., 4500.]]}
        decision = controller.decide(at, blocked, grant_permits=True, step_end_s=round(at + .05, 3))
        self.assertEqual(decision['mode'], 'braking')
        self.assertIsNotNone(controller.continuation_stop_clock)

    def test_scan_emits_the_complete_fractional_beam_grid(self):
        sensor = model.resolved_sensor(model.load())
        box = [[[-10., -10.], [10., -10.]], [[10., -10.], [10., 10.]],
               [[10., 10.], [-10., 10.]], [[-10., 10.], [-10., -10.]]]
        world = SensorWorld(sensor, {'EG': box})
        scan = world.scan('BF01', {'BF01': {'pose_mm': [0., 0., 0.], 'level': 'EG', 'z_mm': 0.}},
                          0., {'doors_open': False})
        self.assertEqual(len(scan['returns_local_mm']), 1000)
        self.assertEqual(world.statistics()['rays'], 1000)


if __name__ == '__main__':
    unittest.main()
