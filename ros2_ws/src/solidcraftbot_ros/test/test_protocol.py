"""Independent protocol cases run under colcon without starting a robot."""
import copy
from types import SimpleNamespace

import pytest
from solidcraftbot_ros.protocol import duration_parts, message_point, scenario


@pytest.fixture
def contract():
    def point(t, position):
        return {"time_s": t, "positions_rad": [position] * 6,
                "velocities_rad_s": [0.0] * 6, "accelerations_rad_s2": [0.0] * 6}
    return {
        "joint_names": [f"j{i}" for i in range(6)], "limits_rad": [[-1.0, 1.0]] * 6,
        "mode": "mock", "motion_limits": {
            "qualified": False, "velocity_rad_s": 1.0,
            "acceleration_rad_s2": 10.0, "jerk_rad_s3": 100.0,
        },
        "interpolation": {"method": "quintic", "controller_interpolation": "splines",
                          "live_configuration_verified": False},
        "scenarios": [{"id": "synthetic", "points": [point(0, 0), point(2, 0.1)]}],
    }


def test_valid_pva_contract_and_message_units(contract):
    selected = scenario(contract, "synthetic")
    knot = selected["points"][-1]
    factory = lambda: SimpleNamespace(time_from_start=SimpleNamespace(sec=0, nanosec=0))
    message = message_point(knot, factory)
    assert message.positions == [0.1] * 6
    assert message.velocities == message.accelerations == [0.0] * 6
    assert (message.time_from_start.sec, message.time_from_start.nanosec) == (2, 0)
    assert duration_parts(1.9999999999) == (2, 0)


@pytest.mark.parametrize("defect", ["time", "position", "nonfinite", "partial_pva", "joint_names"])
def test_invalid_contracts_fail_before_ros_execution(contract, defect):
    value = copy.deepcopy(contract)
    if defect == "time":
        value["scenarios"][0]["points"][-1]["time_s"] = 0
    elif defect == "position":
        value["scenarios"][0]["points"][-1]["positions_rad"][0] = 2
    elif defect == "nonfinite":
        value["scenarios"][0]["points"][-1]["velocities_rad_s"][0] = float("nan")
    elif defect == "partial_pva":
        value["scenarios"][0]["points"][0].pop("accelerations_rad_s2")
    else:
        value["joint_names"][1] = value["joint_names"][0]
    with pytest.raises(ValueError):
        scenario(value, "synthetic")


def test_between_knot_derivative_violation_is_not_hidden_by_rest_endpoints(contract):
    contract["motion_limits"]["velocity_rad_s"] = 0.08
    with pytest.raises(ValueError, match="interior.*velocity_rad_s"):
        scenario(contract, "synthetic")
