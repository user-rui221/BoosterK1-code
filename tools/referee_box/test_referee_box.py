"""Local HTTP -> UDP integration checks; no ROS or simulator required."""
import argparse
import socket
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from referee_box import Referee, handler_for, make_packet


class RefereeTests(unittest.TestCase):
    def test_wire_layout(self):
        packet = make_packet(3, 256, [29, 30], 3)
        self.assertEqual(len(packet), 198)
        self.assertEqual(packet[:7], b"RGme\x13\x00\x03")
        self.assertEqual(packet[8:14], bytes([0, 0, 3, 0, 1, 29]))
        self.assertEqual(packet[14:18], b"\x58\x02\x00\x00")
        self.assertEqual(packet[18], 29)
        self.assertEqual(packet[108], 30)
        for start in (28, 118):
            self.assertEqual(packet[start:start + 12], bytes(12))
            self.assertEqual(packet[start + 12:start + 16], bytes([11, 0, 0, 0]))

    def test_buttons_and_repeated_udp(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(2)
            args = argparse.Namespace(target="127.0.0.1", port=receiver.getsockname()[1],
                                      teams=[1, 2], players=2)
            referee = Referee(args)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(referee))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            idle = socket.create_connection(("127.0.0.1", server.server_port))
            try:
                with urlopen(url, timeout=2) as response:
                    self.assertIn("比赛开始", response.read().decode())
                for state in range(5):
                    body = urlencode({"state": state, "token": referee.token}).encode()
                    with urlopen(url + "/state", data=body) as response:
                        self.assertEqual(response.status, 200)
                    packet = receiver.recv(1024)
                    self.assertEqual(len(packet), 198)
                    self.assertEqual(packet[10], state)
                    self.assertEqual(packet[5], state)
                for fields, code in (({"state": 5, "token": referee.token}, 400),
                                     ({"state": 3, "token": "wrong"}, 403)):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(url + "/state", data=urlencode(fields).encode())
                    self.assertEqual(error.exception.code, code)
                self.assertEqual(referee.state, 4)
                sender = threading.Thread(target=referee.run)
                sender.start()
                try:
                    first = receiver.recv(1024)
                    second = receiver.recv(1024)
                    self.assertEqual(first[10], 4)
                    self.assertEqual(second[10], 4)
                    self.assertEqual(second[5], (first[5] + 1) % 256)
                finally:
                    referee.stop.set()
                    sender.join()
            finally:
                idle.close()
                server.shutdown()
                thread.join()
                server.server_close()
                referee.sock.close()


if __name__ == "__main__":
    unittest.main()
