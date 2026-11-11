import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from viewer import Frames, handler_for
class ViewerTests(unittest.TestCase):
    def test_match_uses_detection_frame(self):
        f=Frames();f.add_image(1,b'old');f.add_image(2,b'new');f.add_detection(1,[{'label':'LCross'}])
        self.assertEqual(f.snapshot()['stamp'],1);self.assertEqual(len(f.snapshot()['objects']),1)
    def test_mismatch_and_stale_hide_boxes(self):
        f=Frames();f.add_image(1,b'jpeg');f.add_detection(3,[{}]);self.assertEqual(f.snapshot()['objects'],[])
        f=Frames();f.add_image(1,b'jpeg');f.add_detection(1,[{}]);t,o,r=f.detection;f.detection=(t,o,r-3)
        self.assertEqual(f.snapshot()['objects'],[]);self.assertIn('中断',f.snapshot()['status'])
    def test_clock_reset(self):
        f=Frames();f.add_image(100,b'old');f.add_detection(100,[{}]);f.add_image(1,b'new')
        self.assertIsNone(f.detection);self.assertEqual(len(f.images),1)
        f.add_detection(100,[{}]);f.add_detection(1,[{}]);self.assertEqual(len(f.images),0)
    def test_http_readonly(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Frames(),{}));t=threading.Thread(target=server.serve_forever);t.start()
        try:
            root='http://127.0.0.1:'+str(server.server_port)
            with urllib.request.urlopen(root+'/') as r:self.assertIn(b'<canvas',r.read())
            with urllib.request.urlopen(root+'/api/frame') as r:self.assertEqual('等待相机',json.load(r)['status'])
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(urllib.request.Request(root+'/',data=b'x'))
            self.assertEqual(e.exception.code,501)
        finally:server.shutdown();server.server_close();t.join()
if __name__=='__main__':unittest.main()
