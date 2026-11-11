#!/usr/bin/env python3
"""UDP -> game_controller -> brain -> UDP integration, DDS domain 97 only.
Run in isolated build container; no simulator or physical controller required.
"""
import os
os.environ['ROS_DOMAIN_ID'] = '97'
os.environ['ROS_LOCALHOST_ONLY'] = '1'
import sys
import json
import signal
import socket
import subprocess
import time
import unittest
from pathlib import Path
import test_ground_truth as gt
sys.path.insert(0, str(gt.ROOT / 'tools/referee_box'))
from desktop_core import Connection, Sender
from referee_box import make_packet

class RoundResetTests(unittest.TestCase):
    setUpClass = classmethod(gt.GroundTruthTests.setUpClass.__func__)
    tearDownClass = classmethod(gt.GroundTruthTests.tearDownClass.__func__)
    start = gt.GroundTruthTests.start
    pump = gt.GroundTruthTests.pump
    moves = gt.GroundTruthTests.moves

    def setUp(self):
        gt.GroundTruthTests.setUp(self)
        self.status = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(('127.0.0.1', 0))
            self.port = s.getsockname()[1]
        self.bridge_out = (Path(self.tmp.name) / 'bridge.log').open('w')
        self.bridge = subprocess.Popen([str(gt.ROOT/'install/game_controller/lib/game_controller/game_controller_node'),
            '--ros-args', '-p', f'port:={self.port}'], stdout=self.bridge_out, stderr=subprocess.STDOUT)
        self.sender = Sender(Connection('127.0.0.1', self.port), lambda *_:None, lambda:None, self.status.append)
        self.raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.raw.settimeout(.1)

    def tearDown(self):
        self.sender.stop()
        if self.sender.ident: self.sender.join(2)
        self.raw.close()
        self.bridge.send_signal(signal.SIGINT)
        try: self.bridge.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.bridge.kill(); self.bridge.wait()
        self.bridge_out.close()
        gt.GroundTruthTests.tearDown(self)

    def start_game(self, **params):
        self.start(**{'tree_file_path':str(gt.ROOT/'src/brain/behavior_trees/game.xml'),
                      'RLVisionKick.enableAutoVisualKick':'false', **params})
        self.sender.start()
        self.pump(1, pose=(-4, 0, 0))

    def reset_and_wait(self, pose=None):
        self.status.clear()
        self.sender.reset_round()
        self.pump(.8, pose=pose)
        self.assertIn('complete', self.status, self.log.read_text()[-3000:])
        self.assertEqual(self.sender.state, 0)

    def assert_stopped(self, pose=None):
        self.requests.clear()
        self.pump(.25, pose=pose)
        self.assertTrue(self.moves())
        self.assertTrue(all(all(v == 0 for v in m.values()) for m in self.moves()), self.moves()[-10:])

    def test_three_rounds_and_repeat_initial(self):
        self.start_game()
        for _ in range(3):
            self.sender.change(1)
            self.requests.clear()
            self.pump(.5, pose=(-4, 0, 0))
            self.assertTrue(any(m.get('vx',0)>0 for m in self.moves()))
            self.pump(.3, pose=(-2, 0, 0))
            self.assert_stopped(pose=(-2, 0, 0))
            self.sender.change(3)
            self.pump(.4, pose=(-2, 0, 0))
            self.reset_and_wait(pose=(-4,0,0))
            self.assert_stopped(pose=(-4,0,0))
        n = self.log.read_text().count('Round reset complete:')
        self.pump(1, pose=(-4,0,0))
        self.assertEqual(self.log.read_text().count('Round reset complete:'), n)
        self.reset_and_wait(pose=(-4,0,0))
        self.assertEqual(self.log.read_text().count('Round reset complete:'), n+1)

    def test_retry_is_idempotent_and_wrong_player_ignored(self):
        self.start_game()
        n = self.log.read_text().count('Round reset complete:')
        req = b'RBR1 '+b'a'*32+b' 1 2'
        self.raw.sendto(req, ('127.0.0.1', self.port))
        self.pump(.3, pose=(-4,0,0))
        self.assertEqual(self.log.read_text().count('Round reset complete:'), n)
        req = b'RBR1 '+b'b'*32+b' 1 1'
        for _ in range(3):
            self.raw.sendto(req, ('127.0.0.1', self.port))
            self.pump(.25, pose=(-4,0,0))
        self.assertEqual(self.log.read_text().count('Round reset complete:'), n+1)
        reply, _ = self.raw.recvfrom(512)
        self.assertEqual(reply, b'RBA1 '+b'b'*32+b' 1 1 complete')

    def test_reset_requires_fresh_pose_and_clears_ball(self):
        self.start_game()
        from vision_interface.msg import Detections, DetectedObject
        pub = self.node.create_publisher(Detections, '/booster_soccer/detection/localization_test', 10)
        self.pump(.3, pose=(-4,0,0))
        for _ in range(8):
            det = Detections(detected_objects=[DetectedObject(label='Ball',confidence=100.,position_projection=[.4,0.,0.])],corner_pos=[0.]*10)
            det.header.stamp = self.node.get_clock().now().to_msg()
            pub.publish(det)
            self.pump(.05, pose=(-4,0,0))
        self.sender.change(3)
        self.pump(.25, pose=(-4,0,0))
        # This is ordinary Kick, with a fresh close ball directly ahead.
        self.assertTrue(any(m.get('vx',0)>0 for m in self.moves()))
        old_stamp = det.header.stamp
        self.reset_and_wait()
        self.assert_stopped()
        self.sender.change(1)
        self.assert_stopped()
        self.requests.clear()
        self.pump(.5, pose=(-4,0,0))
        self.assertTrue(any(m.get('vx',0)>0 for m in self.moves()))
        # Delayed detections from before reset must not repopulate ball memory.
        det.header.stamp = old_stamp
        pub.publish(det)
        self.pump(.2, pose=(-4,0,0))
        self.assertTrue(self.balls)
        self.assertEqual((self.balls[-1].x, self.balls[-1].y), (0., 0.))

    def test_visual_kick_reset_sends_stop(self):
        self.start(body="""<ReactiveSequence><RLVisionKick _while="gc_game_state=='PLAY'" min_msec_kick="100000"/><SetVelocity _while="gc_game_state!='PLAY'"/></ReactiveSequence>""")
        self.sender.start()
        self.pump(.7, pose=(-4,0,0))
        self.sender.change(3)
        self.pump(1, pose=(-4,0,0))
        kicks = lambda: [json.loads(m.body) for m in self.requests if json.loads(m.header)['api_id']==2038]
        self.assertTrue(any(k['start'] for k in kicks()))
        self.requests.clear()
        self.reset_and_wait(pose=(-4,0,0))
        self.assertTrue(any(not k['start'] and k['version']==0 for k in kicks()))
        self.assertFalse(any(k['start'] for k in kicks()))
        self.assert_stopped(pose=(-4,0,0))

    def test_vision_reset_needs_relocalization(self):
        self.start_game(**{'localization.source':'vision'})
        self.reset_and_wait()
        self.assert_stopped()
        self.sender.change(1)
        self.assert_stopped()  # No field markers: no movement permitted.
        self.sender.change(3)
        self.assert_stopped()

    def test_ordinary_initial_transition_resets_once(self):
        self.start_game()
        self.sender.change(1)
        self.pump(.4, pose=(-4,0,0))
        n = self.log.read_text().count('Round reset complete:')
        self.sender.change(0)
        self.pump(.7, pose=(-4,0,0))
        self.assertEqual(self.log.read_text().count('Round reset complete:'), n+1)
        self.assert_stopped(pose=(-4,0,0))
        self.pump(.7, pose=(-4,0,0))
        self.assertEqual(self.log.read_text().count('Round reset complete:'), n+1)

if __name__ == '__main__': unittest.main()
