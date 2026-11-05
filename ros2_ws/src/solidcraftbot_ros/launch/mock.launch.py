from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument,RegisterEventHandler
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share=Path(get_package_share_directory("solidcraftbot_ros"))
    namespace=LaunchConfiguration("namespace")
    description=(share/"urdf/robot.urdf").read_text()
    state=Node(package="robot_state_publisher",executable="robot_state_publisher",namespace=namespace,
               parameters=[{"robot_description":description}],output="screen")
    manager=Node(package="controller_manager",executable="ros2_control_node",namespace=namespace,
                 parameters=[str(share/"config/controllers.yaml")],output="screen",
                 remappings=[("robot_description","robot_description")])
    broadcaster=Node(package="controller_manager",executable="spawner",namespace=namespace,
                     arguments=["joint_state_broadcaster","--controller-manager","controller_manager","--controller-manager-timeout","30"],output="screen")
    trajectory=Node(package="controller_manager",executable="spawner",namespace=namespace,
                    arguments=["arm_controller","--controller-manager","controller_manager","--param-file",str(share/"config/controllers.yaml")],output="screen")
    rviz=Node(package="rviz2",executable="rviz2",namespace=namespace,arguments=["-d",str(share/"config/robot.rviz")],
              condition=IfCondition(LaunchConfiguration("rviz")),output="screen")
    return LaunchDescription([DeclareLaunchArgument("namespace",default_value="umr"),DeclareLaunchArgument("rviz",default_value="true"),
                              state,manager,broadcaster,RegisterEventHandler(OnProcessExit(target_action=broadcaster,on_exit=[trajectory])),rviz])
