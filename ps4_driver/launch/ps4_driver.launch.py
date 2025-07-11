from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    ps4_driver_cmd = Node(
        package="ps4_driver",
        executable="ps4_driver",
        output="screen",
    )

    joy_node = Node(
        package="joy",
        executable="joy_node",
        output="screen",
    )

    ld = LaunchDescription()
    ld.add_action(ps4_driver_cmd)
    ld.add_action(joy_node)

    return ld