#!/usr/bin/env python3
"""Loopback-only host relay to loopback-only Docker viewer; no exposed container port."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--container',default='vdc76-k1');p.add_argument('--port',type=int,default=18081)
a=p.parse_args()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/':body=Path(__file__).with_name('index.html').read_bytes();mime='text/html; charset=utf-8'
        elif self.path=='/api/frame':
            try:
                result=subprocess.run(['docker','exec',a.container,'python3','-c',"import urllib.request,sys;sys.stdout.buffer.write(urllib.request.urlopen('http://127.0.0.1:18081/api/frame',timeout=3).read())"],capture_output=True,timeout=5,check=True)
                body=result.stdout;mime='application/json'
            except (subprocess.SubprocessError,OSError):self.send_error(502,'Container viewer unavailable');return
        else:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*args):pass
print(f'Local viewer: http://127.0.0.1:{a.port}',flush=True)
server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
try:server.serve_forever()
except KeyboardInterrupt:pass
finally:server.server_close()
