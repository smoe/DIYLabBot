"""Opt-in live ROS test: actual mock controllers accept a stationary hold.

This intentionally does not execute the legacy moving scenario. It proves
package, launch, state and action wiring, not motion or hardware qualification.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import traceback

import pytest


@pytest.mark.skipif(
    os.environ.get("SOLIDCRAFTBOT_ROS_INTEGRATION_TESTS") != "1",
    reason="Set SOLIDCRAFTBOT_ROS_INTEGRATION_TESTS=1 in a sourced ROS 2 Jazzy installation",
)
def test_live_mock_stationary_hold(
    package_share, installed_config, installed_urdf, installed_home, tmp_path
):
    import rclpy
    from action_msgs.msg import GoalStatus
    from control_msgs.action import FollowJointTrajectory
    from controller_manager_msgs.srv import ListControllers
    from rclpy.action import ActionClient
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import JointState
    from trajectory_msgs.msg import JointTrajectoryPoint

    assert os.name == "posix", "The live test requires bounded POSIX process-group cleanup"
    assert os.environ.get("ROS_DISTRO") == "jazzy", "Source the Jazzy environment before this test"
    assert installed_urdf.findtext("ros2_control/hardware/plugin") == "mock_components/GenericSystem"
    ros2 = shutil.which("ros2")
    assert ros2 is not None, "The sourced ROS installation must provide the ros2 CLI"
    names = installed_config["joint_names"]
    assert len(names) == 6 and all(math.isfinite(value) for value in installed_home)
    namespace = f"ros_ci_{os.getpid()}"
    prefix = "/" + namespace
    evidence = Path(os.environ.get("SOLIDCRAFTBOT_ROS_EVIDENCE_DIR", str(tmp_path)))
    evidence.mkdir(parents=True, exist_ok=True)
    launch_log = evidence / "mock-launch.log"
    report_path = evidence / "mock-hold-report.json"
    environment = {**os.environ, "ROS_LOG_DIR": str((evidence / "ros-logs").resolve())}
    report = {
        "passed": False, "ros_distro": os.environ["ROS_DISTRO"],
        "namespace": namespace, "joint_names": names, "urdf_home_rad": installed_home,
        "spec_sha256": installed_config["spec_sha256"],
        "installed_assets_sha256": {
            name: hashlib.sha256((package_share / name).read_bytes()).hexdigest()
            for name in ("urdf/robot.urdf", "config/controllers.yaml")
        },
        "scope": "Real ROS mock controller/state/action wiring with a stationary hold only; no moving robot, dynamics, hardware or safety qualification.",
    }
    process = node = context = executor = action = controller_client = handle = None
    states = []
    passed = False
    shutdown = "not_started"
    with launch_log.open("w", encoding="utf-8") as log:
        try:
            process = subprocess.Popen(
                [ros2, "launch", "solidcraftbot_ros", "mock.launch.py",
                 f"namespace:={namespace}", "rviz:=false"],
                env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            context = Context()
            rclpy.init(context=context)
            node = rclpy.create_node("hold_probe", namespace=prefix, context=context)
            executor = SingleThreadedExecutor(context=context)
            executor.add_node(node)

            def receive_state(message):
                assert len(message.name) == len(message.position), "Malformed joint state"
                assert len(message.name) == len(set(message.name)), "Duplicate joint names"
                observed = dict(zip(message.name, message.position))
                if not all(name in observed for name in names):
                    return
                values = [observed[name] for name in names]
                assert all(math.isfinite(value) for value in values), "Nonfinite joint feedback"
                states.append({"positions_rad": values, "received_monotonic_s": time.monotonic()})

            subscription = node.create_subscription(
                JointState, "joint_states", receive_state, qos_profile_sensor_data
            )
            controller_client = node.create_client(
                ListControllers, "controller_manager/list_controllers"
            )

            def wait_until(predicate, seconds, label):
                deadline = time.monotonic() + seconds
                while not predicate():
                    assert process.poll() is None, (
                        f"ROS launch exited with {process.returncode} while waiting for {label}; see {launch_log}"
                    )
                    assert context.ok(), f"ROS context stopped while waiting for {label}"
                    assert time.monotonic() < deadline, f"Timed out waiting for {label}; see {launch_log}"
                    executor.spin_once(timeout_sec=0.1)

            def await_future(future, seconds, label):
                wait_until(future.done, seconds, label)
                assert future.exception() is None, f"{label}: {future.exception()}"
                value = future.result()
                assert value is not None, f"Missing {label} response"
                return value

            wait_until(lambda: controller_client.service_is_ready(), 45, "controller manager service")
            readiness_deadline = time.monotonic() + 45
            expected_types = {
                "joint_state_broadcaster": "joint_state_broadcaster/JointStateBroadcaster",
                "arm_controller": "joint_trajectory_controller/JointTrajectoryController",
            }
            while True:
                response = await_future(
                    controller_client.call_async(ListControllers.Request()), 5, "controller state query"
                )
                controllers = {controller.name: controller for controller in response.controller}
                report["controllers"] = [
                    {"name": controller.name, "state": controller.state, "type": controller.type}
                    for controller in response.controller
                ]
                if all(name in controllers and controllers[name].state == "active"
                       for name in expected_types):
                    for name, expected_type in expected_types.items():
                        assert controllers[name].type == expected_type
                    break
                assert time.monotonic() < readiness_deadline, (
                    f"Controllers did not become active: {report['controllers']}; see {launch_log}"
                )
                executor.spin_once(timeout_sec=0.1)
            wait_until(lambda: len(states) >= 3, 10, "complete six-axis mock joint feedback")
            for sample in states:
                assert sample["positions_rad"] == pytest.approx(installed_home, abs=1e-9)
            report["initial_state_rad"] = states[-1]["positions_rad"]
            action = ActionClient(node, FollowJointTrajectory, "arm_controller/follow_joint_trajectory")
            wait_until(lambda: action.server_is_ready(), 10, "FollowJointTrajectory action server")
            goal = FollowJointTrajectory.Goal()
            goal.trajectory.joint_names = names
            hold = JointTrajectoryPoint()
            hold.positions = installed_home
            hold.velocities = [0.0] * 6
            hold.accelerations = [0.0] * 6
            hold.time_from_start.nanosec = 500_000_000
            goal.trajectory.points = [hold]
            goal.goal_time_tolerance.sec = 2
            handle = await_future(action.send_goal_async(goal), 10, "hold goal acceptance")
            assert handle.accepted, "The real mock controller rejected the stationary hold"
            report["goal_accepted"] = True
            report["goal_positions_rad"] = list(hold.positions)
            report["hold_duration_s"] = 0.5
            state_count = len(states)
            result = await_future(handle.get_result_async(), 10, "hold action result")
            report["action_status"] = result.status
            report["controller_error_code"] = result.result.error_code
            report["controller_error_string"] = result.result.error_string
            assert result.status == GoalStatus.STATUS_SUCCEEDED
            assert result.result.error_code == FollowJointTrajectory.Result.SUCCESSFUL
            wait_until(lambda: len(states) >= state_count + 2, 5, "fresh feedback after hold")
            errors = [abs(value - expected) for sample in states
                      for value, expected in zip(sample["positions_rad"], installed_home)]
            report["joint_state_samples"] = len(states)
            report["maximum_home_error_rad"] = max(errors)
            assert report["maximum_home_error_rad"] <= 1e-9
            passed = True
        except BaseException:
            report["failure"] = traceback.format_exc()
            raise
        finally:
            if not passed and handle is not None and handle.accepted and node is not None:
                try:
                    cancel = handle.cancel_goal_async()
                    deadline = time.monotonic() + 2
                    while not cancel.done() and context.ok() and time.monotonic() < deadline:
                        executor.spin_once(timeout_sec=0.1)
                    report["cancel_response_received"] = cancel.done()
                except Exception as error:
                    report["cancel_error"] = str(error)
            cleanup_errors = []

            def cleanup_step(label, callback):
                try:
                    return callback()
                except Exception as error:
                    cleanup_errors.append({"step": label, "error": str(error)})
                    return None

            if executor is not None:
                if cleanup_step("shutdown_executor", lambda: executor.shutdown(timeout_sec=2)) is not True:
                    cleanup_errors.append({"step": "shutdown_executor", "error": "Executor did not stop"})
            if action is not None:
                cleanup_step("destroy_action", action.destroy)
            if controller_client is not None and node is not None:
                cleanup_step("destroy_controller_client", lambda: node.destroy_client(controller_client))
            if node is not None:
                cleanup_step("destroy_node", node.destroy_node)
            if context is not None and context.ok():
                cleanup_step("shutdown_context", context.shutdown)
            group_gone = process is None
            if process is not None:
                shutdown = "already_exited"

                def group_exists():
                    try:
                        os.killpg(process.pid, 0)
                        return True
                    except ProcessLookupError:
                        return False

                def stop_group():
                    nonlocal shutdown
                    # A launcher may exit before its children. Inspect and stop
                    # the entire new session's process group even in that case.
                    process.poll()
                    for sig, timeout, label in (
                        (signal.SIGINT, 10, "sigint"),
                        (signal.SIGTERM, 5, "sigterm"),
                        (signal.SIGKILL, 5, "sigkill"),
                    ):
                        if not group_exists():
                            break
                        try:
                            os.killpg(process.pid, sig)
                        except ProcessLookupError:
                            break
                        shutdown = label
                        deadline = time.monotonic() + timeout
                        while time.monotonic() < deadline:
                            process.poll()
                            if not group_exists():
                                break
                            time.sleep(0.05)
                    process.poll()
                    return not group_exists()

                group_gone = cleanup_step("stop_launch_process_group", stop_group) is True
                report["launch_exit_code"] = process.poll()
            report["shutdown"] = shutdown
            report["process_group_gone"] = group_gone
            report["cleanup_errors"] = cleanup_errors
            report["passed"] = (passed and not cleanup_errors and group_gone
                                and shutdown in {"sigint", "already_exited"})
            report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
            log.flush()
            if not report["passed"]:
                print(f"ROS launch log ({launch_log}):\n" + launch_log.read_text()[-16000:])
    assert report["passed"], f"Mock launch required forced cleanup; see {report_path}"
