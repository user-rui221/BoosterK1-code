#!/usr/bin/env python3
"""Integration checks for the installed brain binary, isolated from robot DDS.
Run inside the simulator after sourcing ROS and install/setup.bash.
Uses domain 97, localhost only, a unique robot name, and disables team UDP.
"""
import os
os.environ['ROS_DOMAIN_ID'] = '97'
os.environ['ROS_LOCALHOST_ONLY'] = '1'
import json
import math
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
import rclpy
from geometry_msgs.msg import Pose2D, Point
from vision_interface.msg import Detections, DetectedObject
from rosgraph_msgs.msg import Clock
from booster_interface.msg import Odometer
from booster_msgs.msg import RpcReqMsg
from rcl_interfaces.srv import SetParameters
from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType

ROOT = Path(__file__).resolve().parents[2]
ALL_LOCATORS = ''.join(f'<{n} msecs_interval="0"/>' for n in [
    'SelfLocate', 'SelfLocateEnterField', 'SelfLocate1M', 'SelfLocate2X',
    'SelfLocate2T', 'SelfLocateLT', 'SelfLocatePT', 'SelfLocateBorder'])

class GroundTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='brain-localization-')
        self.node = rclpy.create_node('localization_test')
        self.poses, self.requests, self.balls = [], [], []
        self.subs = [
            self.node.create_subscription(Point, "/booster_soccer/ball_position/localization_test", self.balls.append, 100),
            self.node.create_subscription(Pose2D, '/booster_soccer/robot_pose/localization_test',
                                          self.poses.append, 100),
            self.node.create_subscription(RpcReqMsg, '/LocoApiTopic/localization_testReq',
                                          self.requests.append, 100)]
        self.gt = self.node.create_publisher(Pose2D, '/test/localization/pose', 10)
        self.odom = self.node.create_publisher(Odometer, '/odometer_state/localization_test', 10)
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.node.destroy_node()
        if hasattr(self, 'out'):
            self.out.close()
        self.tmp.cleanup()

    def start(self, source='simulation_ground_truth', body=None, **params):
        if body is None:
            body = ALL_LOCATORS + '<CalibrateOdom x="99" y="98" theta="1"/><SetVelocity x="0.4"/>'
        tree = Path(self.tmp.name) / 'tree.xml'
        tree.write_text(f'<root BTCPP_format="4"><BehaviorTree ID="MainTree"><Sequence>{body}</Sequence></BehaviorTree></root>')
        settings = {
            'localization.source': source,
            'localization.ground_truth_topic': '/test/localization/pose',
            'localization.timeout_sec': '0.25',
            'robot.robot_name': 'localization_test', 'enable_com': 'false',
            # inet_addr -> broadcast; this socket has no SO_BROADCAST, so UDP sends fail locally.
            'game_control_ip': '255.255.255.255',
            'tree_file_path': str(tree),
            'vision_config_path': str(ROOT / 'src/vision/config/vision.yaml')}
        settings.update(params)
        cmd = [str(ROOT / 'install/brain/lib/brain/brain_node'), '--ros-args',
               '--params-file', str(ROOT / 'src/brain/config/config.yaml')]
        for key, value in settings.items():
            cmd += ['-p', f'{key}:={value}']
        self.log = Path(self.tmp.name) / 'brain.log'
        self.out = self.log.open('w')
        self.proc = subprocess.Popen(cmd, stdout=self.out, stderr=subprocess.STDOUT, cwd=self.tmp.name)
        self.pump(1.5)
        self.assertIsNone(self.proc.poll(), self.log.read_text()[-4000:])

    def pump(self, seconds, pose=None, odom=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if pose is not None:
                self.gt.publish(Pose2D(x=float(pose[0]), y=float(pose[1]), theta=float(pose[2])))
            if odom is not None:
                self.odom.publish(Odometer(x=float(odom[0]), y=float(odom[1]), theta=float(odom[2])))
            # Drain all streams faster than brain publishes (100 Hz per topic).
            for _ in range(30):
                rclpy.spin_once(self.node, timeout_sec=0.0)
            time.sleep(0.005)
        if self.proc:
            self.assertIsNone(self.proc.poll(), self.log.read_text()[-4000:])

    def moves(self):
        # kMove = 2001 in the bundled SDK.
        return [json.loads(m.body) for m in self.requests if json.loads(m.header)['api_id'] == 2001]

    def assert_pose(self, expected):
        self.assertTrue(self.poses, self.log.read_text()[-2000:])
        actual = self.poses[-1]
        for a, b in zip((actual.x, actual.y, actual.theta), expected):
            self.assertAlmostEqual(a, b, places=5)

    def test_authority_timeout_invalid_recovery(self):
        self.start()
        self.assertFalse(self.poses)  # No uninitialized field pose is published.
        self.assertTrue(self.moves())
        self.assertTrue(all(all(v == 0 for v in m.values()) for m in self.moves()))
        self.pump(0.7, pose=(1, 2, 0.3), odom=(20, 30, -1))
        self.assert_pose((1, 2, 0.3))  # all 8 locators and manual calibration executed
        self.assertTrue(any(m.get('vx', 0) > 0 for m in self.moves()))
        self.pump(0.55)  # stop publishing truth
        self.requests.clear()
        self.pump(0.15, odom=(-60, 80, 2))
        self.assertTrue(self.moves())
        self.assertTrue(all(all(v == 0 for v in m.values()) for m in self.moves()))
        self.pump(0.4, pose=(-2, 1, -0.5))
        self.assert_pose((-2, 1, -0.5))
        self.pump(0.2, pose=(float('nan'), 1, 0))
        self.requests.clear()
        self.pump(0.1, pose=(float('nan'), 1, 0))
        self.assertTrue(self.moves())
        self.assertTrue(all(all(v == 0 for v in m.values()) for m in self.moves()))
        self.pump(0.3, pose=(3, 0, 0))
        self.assert_pose((3, 0, 0))

    def test_transform_and_angle_wrap(self):
        self.start(**{'localization.translation_x': '2.0', 'localization.translation_y': '-1.0',
                      'localization.rotation_yaw': str(math.pi / 2)})
        self.pump(0.6, pose=(1, 2, math.pi))
        self.assert_pose((0, 0, -math.pi / 2))

    def test_vision_mode_ignores_ground_truth(self):
        self.start(source='vision', body='<CalibrateOdom x="4" y="3" theta="0.2"/>')
        self.pump(0.5, pose=(99, 88, 2), odom=(3, 2, 0))
        self.assert_pose((4, 3, 0.2))
        self.assertEqual(self.node.count_subscribers('/test/localization/pose'), 0)

    def test_visual_kick_stops_on_loss_and_restarts(self):
        self.start(body='<RLVisionKick min_msec_kick="100000"/>')
        self.pump(1.2, pose=(1, 0, 0))
        kicks = lambda: [json.loads(m.body) for m in self.requests if json.loads(m.header)['api_id'] == 2038]
        self.assertTrue(any(m['start'] for m in kicks()))
        self.pump(0.6)
        self.assertTrue(any(not m['start'] and m['version'] == 0 for m in kicks()))
        self.requests.clear()
        self.pump(1.2, pose=(1, 0, 0))
        self.assertTrue(any(m['start'] for m in kicks()))

    def test_ready_stops_at_ground_truth_target(self):
        self.start(body='<Script code="gc_is_kickoff_side:=true"/><GoToReadyPosition/>')
        self.pump(0.5, pose=(-4, 0, 0))
        self.assertTrue(any(m.get('vx', 0) > 0 for m in self.moves()))
        self.pump(0.3, pose=(-2, 0, 0), odom=(100, 100, 2))
        self.requests.clear()
        self.pump(0.2, pose=(-2, 0, 0), odom=(100, 100, 2))
        self.assertTrue(self.moves())
        self.assertTrue(all(all(v == 0 for v in m.values()) for m in self.moves()))

    def test_ball_field_memory_survives_robot_motion(self):
        self.start(body='<SetVelocity/>')
        self.pump(0.4, pose=(1, 2, math.pi / 2))
        pub = self.node.create_publisher(Detections, '/booster_soccer/detection/localization_test', 10)
        self.pump(0.2, pose=(1, 2, math.pi / 2))
        obj = DetectedObject(label='Ball', confidence=100.0, position_projection=[1.0, 0.0, 0.0])
        det = Detections(detected_objects=[obj], corner_pos=[0.0]*10)
        for _ in range(10):
            det.header.stamp = self.node.get_clock().now().to_msg()
            pub.publish(det)
            self.pump(0.02, pose=(1, 2, math.pi / 2))
        self.assertTrue(self.balls)
        self.assertAlmostEqual(self.balls[-1].x, 1.0, places=5)
        self.assertAlmostEqual(self.balls[-1].y, 3.0, places=5)
        self.pump(0.3, pose=(2, 2, 0), odom=(88, 99, 1))
        self.assertAlmostEqual(self.balls[-1].x, 1.0, places=5)
        self.assertAlmostEqual(self.balls[-1].y, 3.0, places=5)

    def test_clock_rollback_recovers(self):
        clock_pub = self.node.create_publisher(Clock, '/clock', 10)
        self.start(**{'use_sim_time': 'true'})
        clock_msg = Clock()
        clock_msg.clock.sec = 100
        for _ in range(10):
            clock_pub.publish(clock_msg)
            self.pump(0.03, pose=(1, 0, 0))
        clock_msg.clock.sec = 10
        for _ in range(10):
            clock_pub.publish(clock_msg)
            self.pump(0.03, pose=(2, 0, 0))
        self.assert_pose((2, 0, 0))
        self.assertIn('actions halted', self.log.read_text())
        self.pump(0.5)
        self.requests.clear()
        self.pump(0.1)
        self.assertTrue(self.moves())
        self.assertTrue(all(all(v == 0 for v in m.values()) for m in self.moves()))

    def test_source_change_requires_restart(self):
        self.start()
        client = self.node.create_client(SetParameters, '/brain_node/set_parameters')
        self.assertTrue(client.wait_for_service(timeout_sec=2))
        request = SetParameters.Request(parameters=[Parameter(name='localization.source',
            value=ParameterValue(type=ParameterType.PARAMETER_STRING, string_value='vision'))])
        future = client.call_async(request)
        self.pump(0.3)
        self.assertTrue(future.done())
        self.assertFalse(future.result().results[0].successful)

if __name__ == '__main__':
    unittest.main(verbosity=2)
