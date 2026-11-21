"""Check generated assets after a real ament_python package installation."""
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import struct
import subprocess

import pytest


def finite_vector(value, count):
    result = [float(v) for v in value.split()]
    assert len(result) == count and all(math.isfinite(v) for v in result)
    return result


def test_installed_assets_have_current_source_and_mock_contract(
    package_share, installed_config, installed_urdf, installed_home
):
    root = Path(__file__).resolve().parents[4]
    source_bytes = (root / "model/robot.json").read_bytes()
    source = json.loads(source_bytes)
    digest = hashlib.sha256(source_bytes).hexdigest()
    assert installed_config["spec_sha256"] == digest
    assert installed_config["mode"] == "mock"
    assert installed_config["limit_status"]
    assert installed_config["joint_names"] == [j["id"].lower() for j in source["joints"]]
    for actual, joint in zip(installed_home, source["joints"]):
        assert actual == pytest.approx(math.radians(joint["home_deg"]), abs=1e-12)
    assert installed_config["scenarios"][0]["points"][0]["positions_rad"] == pytest.approx(installed_home)
    assert installed_urdf.findtext("ros2_control/hardware/plugin") == "mock_components/GenericSystem"
    assert not installed_urdf.findall("link/inertial"), "This mock has no qualified dynamics"
    for name in ("geometry", "services", "cameras"):
        config = json.loads((package_share / f"config/{name}.json").read_text())
        assert config["spec_sha256"] == digest, name
    assert (package_share / "launch/mock.launch.py").is_file()


def test_urdf_is_one_rooted_tree_with_six_ordered_limited_joints(
    installed_config, installed_urdf, installed_home
):
    assert installed_urdf.tag == "robot"
    links = [node.get("name") for node in installed_urdf.findall("link")]
    assert len(links) == len(set(links)) and "tool0" in links
    joints = installed_urdf.findall("joint")
    names = [node.get("name") for node in joints]
    assert len(names) == len(set(names))
    children, edges = set(), {}
    for node in joints:
        parent, child = node.find("parent").get("link"), node.find("child").get("link")
        assert parent in links and child in links and child not in children
        children.add(child)
        edges.setdefault(parent, []).append(child)
        origin = node.find("origin")
        assert origin is not None
        finite_vector(origin.get("xyz", "0 0 0"), 3)
        finite_vector(origin.get("rpy", "0 0 0"), 3)
    roots = set(links) - children
    assert roots == {"base_link"}
    visited, pending = set(), list(roots)
    while pending:
        link = pending.pop()
        assert link not in visited, "URDF contains a cycle"
        visited.add(link)
        pending.extend(edges.get(link, []))
    assert visited == set(links)
    revolute = installed_urdf.findall("joint[@type='revolute']")
    assert [node.get("name") for node in revolute] == installed_config["joint_names"]
    for node, limits, home in zip(revolute, installed_config["limits_rad"], installed_home):
        axis = finite_vector(node.find("axis").get("xyz"), 3)
        assert sum(v * v for v in axis) == pytest.approx(1)
        limit = node.find("limit")
        actual = [float(limit.get(name)) for name in ("lower", "upper")]
        assert actual == pytest.approx(limits)
        assert actual[0] <= home <= actual[1]
        assert float(limit.get("velocity")) > 0 and float(limit.get("effort")) > 0


def test_every_installed_visual_mesh_exists_and_uses_metres(package_share, installed_urdf):
    referenced = set()
    for node in installed_urdf.findall("link/visual/geometry/mesh"):
        uri = node.get("filename")
        prefix = "package://solidcraftbot_ros/meshes/"
        assert uri.startswith(prefix), uri
        relative = PurePosixPath(uri[len(prefix):])
        assert relative.parts and not relative.is_absolute() and ".." not in relative.parts, uri
        # Symlink installations legitimately resolve meshes into the source tree.
        mesh = (package_share / "meshes" / Path(*relative.parts)).resolve()
        referenced.add(mesh)
    assert len(referenced) >= 7
    for mesh in referenced:
        data = mesh.read_bytes()
        assert len(data) >= 84, mesh
        count = struct.unpack_from("<I", data, 80)[0]
        assert count > 0 and len(data) == 84 + 50 * count, mesh
        largest = 0.0
        for record in struct.iter_unpack("<12fH", data[84:]):
            assert all(math.isfinite(v) for v in record[:12]), mesh
            largest = max(largest, *(abs(v) for v in record[3:12]))
        assert 0.005 < largest < 1.0, f"Mesh coordinate scale differs from metres: {mesh}"
    geometry = json.loads((package_share / "config/geometry.json").read_text())
    assert geometry["units"] == "m"
    declared = set()
    for link in geometry["links"].values():
        declared.add((package_share / "meshes" / link["mesh"]).resolve())
        if link.get("marking"):
            declared.add((package_share / "meshes" / link["marking"]["mesh"]).resolve())
        declared.update((package_share / "meshes" / camera["mesh"]).resolve()
                        for camera in link.get("camera_visuals", []))
    assert referenced == declared, "Installed geometry manifest and URDF mesh references differ"


def test_controller_config_binds_complete_position_interfaces(package_share, installed_config):
    controllers = json.loads((package_share / "config/controllers.yaml").read_text())
    manager = controllers["/**/controller_manager"]["ros__parameters"]
    assert manager["update_rate"] > 0
    assert manager["joint_state_broadcaster"]["type"] == "joint_state_broadcaster/JointStateBroadcaster"
    assert manager["arm_controller"]["type"] == "joint_trajectory_controller/JointTrajectoryController"
    arm = controllers["/**/arm_controller"]["ros__parameters"]
    assert arm["joints"] == installed_config["joint_names"]
    assert arm["command_interfaces"] == ["position"]
    assert arm["state_interfaces"] == ["position"]
    assert arm["allow_partial_joints_goal"] is False


def test_installed_run_protocol_entrypoint_dry_run_uses_installed_config(installed_config):
    from ament_index_python.packages import get_package_prefix

    executable = Path(get_package_prefix("solidcraftbot_ros")) / "lib/solidcraftbot_ros/run_protocol"
    assert executable.is_file() and os.access(executable, os.X_OK)
    selected = installed_config["scenarios"][0]
    result = subprocess.run(
        [str(executable), "--dry-run", "--scenario", selected["id"]],
        check=True, capture_output=True, text=True, timeout=20,
    )
    output = json.loads(result.stdout)
    assert output["joint_names"] == installed_config["joint_names"]
    assert output["scenario"] == selected
