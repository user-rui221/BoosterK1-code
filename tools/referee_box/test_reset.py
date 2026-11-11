"""Reset handshake tests against a loopback fake receiver; no robot traffic."""
import socket
import tempfile
import time
import unittest
from pathlib import Path
from desktop_core import Connection, Sender

class ResetTests(unittest.TestCase):
    def setUp(self):
        self.receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receiver.bind(('127.0.0.1', 0))
        self.receiver.settimeout(2)
        self.status = []
        self.sender = Sender(Connection('127.0.0.1', self.receiver.getsockname()[1]),
                             lambda *_: None, lambda: None, self.status.append)
        self.sender.start()

    def tearDown(self):
        self.sender.stop()
        self.sender.join(2)
        self.assertFalse(self.sender.is_alive())
        self.receiver.close()

    def request(self):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            packet, peer = self.receiver.recvfrom(512)
            if packet.startswith(b'RBR1 '):
                return packet, peer
        self.fail('Missing reset request')

    def wait(self, predicate):
        end = time.monotonic() + 2
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.01)
        self.fail(str(self.status))

    def test_ack_matching_and_block_movement(self):
        self.sender.reset_round()
        packet, peer = self.request()
        self.sender.change(3)
        self.assertEqual(self.sender.state, 0)
        # Wrong UUID must not count as a completed reset.
        self.receiver.sendto(b'RBA1 ' + b'0'*32 + b' 1 1 complete', peer)
        time.sleep(.1)
        self.assertNotIn('complete', self.status)
        # Right content, wrong UDP sender must not count either.
        ack = packet.replace(b'RBR1', b'RBA1', 1) + b' complete'
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
            other.sendto(ack, peer)
        time.sleep(.1)
        self.assertNotIn('complete', self.status)
        self.receiver.sendto(ack, peer)
        self.wait(lambda: 'complete' in self.status)
        self.sender.change(3)
        self.assertEqual(self.sender.state, 3)
        # Another reset while already in INITIAL gets a new operation ID.
        self.sender.reset_round()
        again, _ = self.request()
        self.assertNotEqual(packet, again)

    def test_timeout_retry_preserves_operation_id(self):
        self.sender.reset_round()
        first, peer = self.request()
        with self.sender.condition:
            self.sender.reset_deadline = time.monotonic() - 1
        self.wait(lambda: 'timeout' in self.status)
        self.sender.change(1)
        self.assertEqual(self.sender.state, 0)
        self.sender.reset_round()
        second, _ = self.request()
        self.assertEqual(first, second)
        self.receiver.sendto(second.replace(b'RBR1', b'RBA1', 1) + b' complete', peer)
        self.wait(lambda: 'complete' in self.status)

    def test_legacy_configuration_migrates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'old.json'
            path.write_text('{"schema_version":1,"connection":{"target":"localhost","port":38380,"team1":1,"team2":2,"players":2,"kickoff":0}}')
            self.assertEqual(Connection.read(path).reset_player, 1)


class ResetUiTests(unittest.TestCase):
    def test_desktop_reset_feedback_controls_buttons(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from desktop import RefereeWindow
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(('127.0.0.1', 0)); receiver.settimeout(2)
            path = Path(folder)/'config.json'
            Connection('127.0.0.1', receiver.getsockname()[1]).save(path)
            window = RefereeWindow(path)
            try:
                window.toggle.click()
                window.reset_button.click()
                self.assertFalse(window.buttons[3].isEnabled())
                while True:
                    packet, peer = receiver.recvfrom(512)
                    if packet.startswith(b'RBR1 '): break
                receiver.sendto(packet.replace(b'RBR1', b'RBA1', 1)+b' complete', peer)
                until = time.monotonic()+2
                while time.monotonic()<until and not window.buttons[3].isEnabled():
                    app.processEvents(); time.sleep(.01)
                self.assertTrue(window.buttons[3].isEnabled())
                self.assertIn('清理完成', window.reset_label.text())
                self.assertTrue(window.reset_button.isEnabled())
            finally:
                worker = window.sender
                window.close()
                if worker: worker.join(2)
                app.processEvents()

    def test_web_reset_feedback(self):
        import argparse
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.parse import urlencode
        from urllib.request import urlopen
        from referee_box import Referee, handler_for
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(('127.0.0.1', 0)); receiver.settimeout(2)
            referee = Referee(argparse.Namespace(target='127.0.0.1',port=receiver.getsockname()[1],teams=[1,2],players=2,reset_player=1))
            server = ThreadingHTTPServer(('127.0.0.1',0),handler_for(referee))
            worker = threading.Thread(target=referee.run)
            http = threading.Thread(target=server.serve_forever)
            worker.start(); http.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}'
                with urlopen(url+'/reset',data=urlencode({'token':referee.token}).encode()) as response:
                    self.assertIn('等待 brain', response.read().decode())
                while True:
                    packet, peer = receiver.recvfrom(512)
                    if packet.startswith(b'RBR1 '): break
                referee.change(3)
                self.assertEqual(referee.state,0)
                receiver.sendto(packet.replace(b'RBR1',b'RBA1',1)+b' complete',peer)
                until = time.monotonic()+2
                while time.monotonic()<until and referee.reset_id: time.sleep(.01)
                with urlopen(url) as response:
                    self.assertIn('清理完成',response.read().decode())
                referee.change(3)
                self.assertEqual(referee.state,3)
            finally:
                referee.stop.set(); worker.join(2)
                server.shutdown(); http.join(2)
                server.server_close(); referee.sock.close()

if __name__ == '__main__':
    unittest.main()
