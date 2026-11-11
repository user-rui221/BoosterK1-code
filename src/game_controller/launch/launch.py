# coding: utf8

import launch
import os
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.parameter_descriptions import ParameterValue
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("port", default_value="3838"),
        DeclareLaunchArgument("enable_test_reset", default_value="true"),
        Node(
            package ='game_controller',
            executable='game_controller_node',
            name='game_controller',
            output='screen',
            parameters=[
                {
                    # The port to listen on, default is the GameController broadcast port 3838
                    "port": ParameterValue(LaunchConfiguration("port"), value_type=int),
                    "enable_test_reset": ParameterValue(LaunchConfiguration("enable_test_reset"), value_type=bool),

                    # control if to enable IP white list check, default False, if True, only packets from IPs in ip_white_list will be accepted
                    "enable_ip_white_list": False,

                    # only accept packets from these IP addresses if enable_ip_white_list is True, default empty
                    "ip_white_list": [
                        "127.0.0.1",
                    ],
                }
            ]
        ),
    ])
