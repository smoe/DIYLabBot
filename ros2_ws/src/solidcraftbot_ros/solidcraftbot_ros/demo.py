"""Send a generated protocol through FollowJointTrajectory, with result handling."""
import argparse
import json
import time
from pathlib import Path

from .protocol import scenario,message_point


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario",default="base_sweep_return")
    parser.add_argument("--config",type=Path)
    parser.add_argument("--dry-run",action="store_true")
    args,ros_args=parser.parse_known_args()
    if args.config is None:
        from ament_index_python.packages import get_package_share_directory
        args.config=Path(get_package_share_directory("solidcraftbot_ros"))/"config/scenarios.json"
    config=json.loads(args.config.read_text(encoding="utf-8")); selected=scenario(config,args.scenario)
    if args.dry_run:
        print(json.dumps({"joint_names":config["joint_names"],"scenario":selected},indent=2)); return 0
    import rclpy
    from rclpy.action import ActionClient
    from control_msgs.action import FollowJointTrajectory
    from sensor_msgs.msg import JointState
    from trajectory_msgs.msg import JointTrajectoryPoint
    rclpy.init(args=ros_args)
    node=rclpy.create_node("umr_protocol_client")
    client=ActionClient(node,FollowJointTrajectory,"arm_controller/follow_joint_trajectory")
    state={}; handle=None
    subscription=node.create_subscription(JointState,"joint_states",lambda msg: state.update(zip(msg.name,msg.position)),10)
    try:
        if not client.wait_for_server(timeout_sec=10): raise RuntimeError("Trajectory action server unavailable")
        deadline=time.monotonic()+10
        while not all(name in state for name in config["joint_names"]) and time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=0.1)
        if not all(name in state for name in config["joint_names"]): raise RuntimeError("No complete six-axis joint state")
        if any(abs(state[name]-value)>0.05 for name,value in zip(config["joint_names"],selected["points"][0]["positions_rad"])):
            raise RuntimeError("Current pose differs from protocol start; return to the declared home pose first")
        goal=FollowJointTrajectory.Goal(); goal.trajectory.joint_names=config["joint_names"]
        for point in selected["points"]:
            goal.trajectory.points.append(message_point(point,JointTrajectoryPoint))
        future=client.send_goal_async(goal); rclpy.spin_until_future_complete(node,future,timeout_sec=10)
        if not future.done() or future.result() is None: raise RuntimeError("No action goal response")
        handle=future.result()
        if not handle.accepted: raise RuntimeError("Trajectory rejected by controller")
        result=handle.get_result_async()
        rclpy.spin_until_future_complete(node,result,timeout_sec=selected["points"][-1]["time_s"]+10)
        if not result.done(): raise RuntimeError("Trajectory execution timeout")
        response=result.result()
        if response.status!=4 or response.result.error_code!=0:
            raise RuntimeError("Trajectory failed: "+response.result.error_string)
        node.get_logger().info("Protocol completed: "+selected["id"])
        return 0
    except (RuntimeError,KeyboardInterrupt) as error:
        if handle is not None and handle.accepted:
            cancel=handle.cancel_goal_async(); rclpy.spin_until_future_complete(node,cancel,timeout_sec=2)
        node.get_logger().error(str(error)); return 1
    finally:
        node.destroy_node(); rclpy.shutdown()


if __name__=="__main__": raise SystemExit(main())
