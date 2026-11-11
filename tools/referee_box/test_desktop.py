import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from desktop import RefereeWindow
from desktop_core import Connection

class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def pump(self, until):
        end = time.monotonic() + 2
        while time.monotonic() < end:
            self.app.processEvents()
            if until():
                return
            time.sleep(.01)
        self.fail('Timed out waiting for GUI event')

    def test_portable_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'nested' / 'config.json'
            config = Connection('simulator.local', 38380, 29, 30, 3, 1)
            config.save(path)
            self.assertEqual(Connection.read(path), config)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                Connection('host', team1=2, team2=2).save(path)
            self.assertEqual(path.read_bytes(), original)
            path.write_text('{"schema_version":1,"connection":{}}')
            with self.assertRaises(ValueError):
                Connection.read(path)

    def test_window_to_udp_and_stop(self):
        with tempfile.TemporaryDirectory() as folder, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(('127.0.0.1', 0))
            receiver.settimeout(2)
            path = Path(folder) / 'config.json'
            Connection('127.0.0.1', receiver.getsockname()[1], 29, 30, 3, 1).save(path)
            window = RefereeWindow(path)
            window.show()
            try:
                self.assertIsNone(window.sender)
                self.assertFalse(window.buttons[3].isEnabled())
                receiver.settimeout(.05)
                with self.assertRaises(socket.timeout):
                    receiver.recv(1024)
                receiver.settimeout(2)
                window.toggle.click()
                first = receiver.recv(1024)
                self.assertEqual(first[10], 0)
                self.assertEqual(first[13], 30)
                self.assertEqual((first[18], first[108], first[6]), (29, 30, 3))
                self.assertFalse(window.settings.isEnabled())
                for state in range(5):
                    window.buttons[state].click()
                    packet = receiver.recv(1024)
                    self.assertEqual(len(packet), 198)
                    self.assertEqual(packet[10], state)
                self.assertEqual(receiver.recv(1024)[10], 4)
                window.toggle.click()
                self.pump(lambda: window.sender is None)
                self.assertTrue(window.settings.isEnabled())
                receiver.settimeout(.65)
                with self.assertRaises(socket.timeout):
                    receiver.recv(1024)
                window.toggle.click()
                receiver.settimeout(2)
                self.assertEqual(receiver.recv(1024)[10], 0)
                sender = window.sender
                window.close()
                sender.join(1)
                self.assertFalse(sender.is_alive())
            finally:
                window.close()
                if window.sender:
                    window.sender.join(1)
                self.app.processEvents()

    def test_dns_failure_is_visible_and_ui_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            window = RefereeWindow(Path(folder) / 'missing.json')
            window.connection = Connection('invalid.local')
            with patch('desktop_core.socket.gethostbyname', side_effect=socket.gaierror('test DNS failure')):
                window.toggle.click()
                self.pump(lambda: window.sender is None)
            self.assertIn('test DNS failure', window.status.text())
            self.assertTrue(window.toggle.isEnabled())
            self.assertTrue(window.settings.isEnabled())
            window.close()

if __name__ == '__main__':
    unittest.main()
