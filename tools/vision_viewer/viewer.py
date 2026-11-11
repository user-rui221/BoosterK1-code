#!/usr/bin/env python3
"""Read-only ROS camera/detection viewer. No robot publishers or control endpoints."""
import argparse
import base64
import errno
import sys
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time


class Frames:
    def __init__(self, tolerance=.10):
        self.lock = threading.Lock()
        self.images = deque(maxlen=90)
        self.detection = None
        self.tolerance = tolerance
        self.last_image_stamp = None
        self.last_detection_stamp = None
        self.error = ''

    def add_image(self, stamp, jpeg):
        with self.lock:
            if self.last_image_stamp is not None and stamp < self.last_image_stamp - 1:
                self.images.clear()
                self.detection = None
                self.last_detection_stamp = None
            self.last_image_stamp = stamp
            self.images.append((stamp, jpeg, time.monotonic()))
            self.error = ''

    def add_detection(self, stamp, objects):
        with self.lock:
            if self.last_detection_stamp is not None and stamp < self.last_detection_stamp - 1:
                self.images.clear()
            self.last_detection_stamp = stamp
            self.detection = (stamp, objects, time.monotonic())

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            out = {'image': None, 'objects': [], 'status': '等待相机', 'error': self.error,
                   'image_age': None, 'detection_age': None, 'delta_ms': None}
            if not self.images:
                return out
            frame = self.images[-1]
            out['image_age'] = round(now - frame[2], 2)
            out['status'] = '等待检测：仅显示原图'
            if self.detection:
                stamp, objects, received = self.detection
                age = now - received
                out['detection_age'] = round(age, 2)
                match = min(self.images, key=lambda f: abs(f[0] - stamp))
                delta = match[0] - stamp
                out['delta_ms'] = round(delta * 1000, 2)
                if age > 2:
                    out['status'] = '检测已中断：隐藏旧框'
                elif abs(delta) > self.tolerance:
                    out['status'] = '图像与检测时间不匹配：隐藏检测框'
                else:
                    frame = match
                    out['objects'] = objects
                    out['status'] = '检测与图像已匹配' if objects else '已匹配：本帧无检测目标'
            if out['image_age'] > 2:
                out['status'] = '相机已中断：显示最后画面'
                out['objects'] = []
            out['image'] = base64.b64encode(frame[1]).decode('ascii')
            out['stamp'] = frame[0]
            out['display_age'] = round(now - frame[2], 2)
            return out


def handler_for(frames, config):
    page = Path(__file__).with_name('index.html').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                body, mime = page, 'text/html; charset=utf-8'
            elif self.path == '/api/frame':
                body = json.dumps(dict(frames.snapshot(), config=config), allow_nan=False).encode()
                mime = 'application/json'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=18081)
    parser.add_argument('--image-topic', default='/rgbd_camera/rgb/image_compressed')
    parser.add_argument('--detection-topic', default='/booster_soccer/detection')
    parser.add_argument('--raw', action='store_true', help='Subscribe sensor_msgs/Image instead of CompressedImage')
    parser.add_argument('--max-delta-ms', type=float, default=100)
    args = parser.parse_args()
    if args.max_delta_ms < 0:
        parser.error('--max-delta-ms must be nonnegative')
    import math
    import cv2
    import numpy as np
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image, CompressedImage
    from vision_interface.msg import Detections
    frames = Frames(args.max_delta_ms / 1000)
    rclpy.init()
    node = rclpy.create_node('browser_vision_viewer')
    bridge = None
    if args.raw:
        from cv_bridge import CvBridge
        bridge = CvBridge()
    def stamp(msg):
        return msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
    def image_cb(msg):
        try:
            img = bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8') if bridge else cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError('图像解码失败')
            ok, jpg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                raise ValueError('JPEG编码失败')
            frames.add_image(stamp(msg), jpg.tobytes())
        except Exception as exc:
            with frames.lock:
                frames.error = str(exc)
    def finite(values):
        return [float(x) if math.isfinite(float(x)) else None for x in values]
    def detection_cb(msg):
        objects = [{'label': x.label, 'confidence': finite([x.confidence])[0],
                    'box': [x.xmin, x.ymin, x.xmax, x.ymax],
                    'position': finite(x.position), 'projection': finite(x.position_projection)}
                   for x in msg.detected_objects]
        frames.add_detection(stamp(msg), objects)
    node.create_subscription(Image if args.raw else CompressedImage, args.image_topic, image_cb, qos_profile_sensor_data)
    node.create_subscription(Detections, args.detection_topic, detection_cb, qos_profile_sensor_data)
    config = {'image_topic': args.image_topic, 'detection_topic': args.detection_topic,
              'max_delta_ms': args.max_delta_ms}
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler_for(frames, config))
    except OSError as exc:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        if exc.errno == errno.EADDRINUSE:
            print(f"端口 {args.host}:{args.port} 已被占用，未启动新实例。"
                  "如果已有查看器，请直接打开宿主机 http://127.0.0.1:18081；"
                  "无需重复运行启动命令。", file=sys.stderr)
            return 1
        raise
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f'Vision viewer: http://{args.host}:{args.port}', flush=True)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
