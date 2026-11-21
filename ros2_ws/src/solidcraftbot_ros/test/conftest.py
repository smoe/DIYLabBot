"""Fixtures use the installed ROS share directory, never source-tree assets."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


@pytest.fixture(scope="session")
def package_share():
    from ament_index_python.packages import get_package_share_directory

    share = Path(get_package_share_directory("solidcraftbot_ros"))
    assert share.is_dir(), "Build the package and source install/setup.bash first"
    return share


@pytest.fixture(scope="session")
def installed_config(package_share):
    return json.loads((package_share / "config/scenarios.json").read_text())


@pytest.fixture(scope="session")
def installed_urdf(package_share):
    return ET.parse(package_share / "urdf/robot.urdf").getroot()


@pytest.fixture(scope="session")
def installed_home(installed_config, installed_urdf):
    values = {}
    for joint in installed_urdf.findall("ros2_control/joint"):
        value = joint.find("state_interface[@name='position']/param[@name='initial_value']")
        assert value is not None, joint.get("name")
        values[joint.get("name")] = float(value.text)
    names = installed_config["joint_names"]
    assert len(names) == 6 and set(names) == set(values)
    return [values[name] for name in names]
