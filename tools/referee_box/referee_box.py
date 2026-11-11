#!/usr/bin/env python3
"""Minimal state-only referee for this project's 198-byte simulator protocol."""

import argparse
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import socket
import struct
import threading
import time
import uuid
from urllib.parse import parse_qs

STATES = ("INITIAL", "READY", "SET", "PLAYING", "FINISHED")
LABELS = ("初始化", "准备入场", "就绪 / 停止", "比赛开始", "比赛结束")


def make_packet(state, number, teams, players):
    # Little-endian, packed SimGameControlData in game_controller_node.cpp.
    header = struct.pack("<4s10Bhh", b"RGme", 19, number % 256, players,
                         0, 0, 0, state, 0, 1, teams[0], 600, 0)
    result = bytearray(header)
    for colour, team in enumerate(teams):
        result.extend(struct.pack("<6BHH", team, colour, colour, 1, 0, 0, 0, 0))
        for index in range(20):
            result.extend(struct.pack("4B", 0 if index < players else 11, 0, 0, 0))
    return bytes(result)


class Referee:
    def __init__(self, args):
        self.args = args
        self.state = 0
        self.number = 0
        self.sent = 0
        self.error = ""
        self.reset_id = None
        self.reset_deadline = 0.0
        self.reset_message = "未请求重置"
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setblocking(False)
        self.destination = (socket.gethostbyname(args.target), args.port)
        self.token = secrets.token_urlsafe(24)

    def send_locked(self):
        try:
            self.sock.sendto(make_packet(self.state, self.number,
                                        self.args.teams, self.args.players), self.destination)
            self.number = (self.number + 1) % 256
            self.sent += 1
            self.error = ""
            if self.reset_id and time.monotonic() < self.reset_deadline:
                self.sock.sendto(f"RBR1 {self.reset_id} {self.args.teams[0]} {getattr(self.args, 'reset_player', 1)}".encode(), self.destination)
        except OSError as error:
            self.error = str(error)

    def change(self, state):
        with self.lock:
            if self.reset_id:
                return False
            self.state = state
            self.send_locked()

    def reset_round(self):
        with self.lock:
            self.reset_id = self.reset_id or uuid.uuid4().hex
            self.state = 0
            self.reset_deadline = time.monotonic() + 8.0
            self.reset_message = "等待 brain 清理完成…"
            self.send_locked()

    def run(self):
        next_send = 0.0
        while not self.stop.is_set():
            with self.lock:
                now = time.monotonic()
                if now >= next_send:
                    self.send_locked()
                    next_send = now + 0.5
                try:
                    while True:
                        packet, peer = self.sock.recvfrom(512)
                        if peer != self.destination or not self.reset_id:
                            continue
                        prefix = f"RBA1 {self.reset_id} {self.args.teams[0]} {getattr(self.args, 'reset_player', 1)} "
                        text = packet.decode("ascii", errors="replace")
                        if text == prefix + "complete":
                            self.reset_id = None
                            self.reset_message = "brain 清理完成，保持 INITIAL，等待重新定位；未确认底层物理停车。"
                        elif text in (prefix + "busy", prefix + "agent_mode"):
                            self.reset_message = "brain 拒绝请求（忙碌或 agent 模式）；保持 INITIAL，请检查后重试。"
                            self.reset_deadline = 0
                except BlockingIOError:
                    pass
                if self.reset_id and self.reset_deadline and now >= self.reset_deadline:
                    self.reset_message = "未收到完成反馈，保持 INITIAL；检查接收端和目标球员后重试。"
                    self.reset_deadline = 0
            self.stop.wait(0.03)


def handler_for(referee):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            with referee.lock:
                state, sent, error = referee.state, referee.sent, referee.error
                resetting, reset_message = referee.reset_id is not None, referee.reset_message
            buttons = "".join(
                f'<button name="state" value="{i}" '
                f'class="{"selected" if i == state else ""}" {"disabled" if resetting else ""}>{name}<br>{LABELS[i]}</button>'
                for i, name in enumerate(STATES))
            status = html.escape(error) if error else f"已发送 {sent} 个 UDP 包（不代表接收端已收到）"
            page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="2">
<title>仿真裁判盒</title><style>
body{{font:17px system-ui;max-width:900px;margin:60px auto;padding:20px;background:#f3f5f8;color:#182333}}
form{{display:flex;flex-wrap:wrap;gap:12px}}button{{padding:20px;border:2px solid #ccd4df;border-radius:12px;background:white;cursor:pointer;font:inherit}}
.selected{{border-color:#176ad3;background:#e1edff}}p{{line-height:1.7}}
</style><h1>仿真裁判盒</h1><h2>当前状态：{STATES[state]} · {LABELS[state]}</h2>
<form method="post" action="/state"><input type="hidden" name="token" value="{referee.token}">{buttons}</form>
<form method="post" action="/reset"><input type="hidden" name="token" value="{referee.token}"><button>重置本轮 / 超时重试 → INITIAL</button></form>
<p>{html.escape(reset_message)}<br>重置队{referee.args.teams[0]}球员{getattr(referee.args, 'reset_player', 1)}；机器人和球的位置不会复位。</p>
<p>目标：{html.escape(referee.args.target)}:{referee.args.port} · 队号：{referee.args.teams} · 每队 {referee.args.players} 人<br>
每 0.5 秒重复发送当前状态，第一支队伍开球。</p><p>{status}</p>
<p>只控制机器人收到的比赛状态；不控制仿真内部判罚和摆球。停止程序不会自动发送结束状态，请先点击 FINISHED。</p>
<a href="/">刷新发送状态</a></html>'''
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path not in ("/state", "/reset"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError()
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                if form.get("token") != [referee.token]:
                    self.send_error(403)
                    return
                state = 0 if self.path == "/reset" else int(form["state"][0])
                if state not in range(len(STATES)):
                    raise ValueError()
            except (ValueError, KeyError, UnicodeError):
                self.send_error(400)
                return
            if self.path == "/reset":
                referee.reset_round()
            else:
                referee.change(state)
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    return Handler


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="127.0.0.1", help="Receiver IP or broadcast address")
    parser.add_argument("--port", type=int, default=38380, help="Receiver UDP port (default: 38380)")
    parser.add_argument("--teams", type=int, nargs=2, default=[1, 2], metavar=("TEAM1", "TEAM2"))
    parser.add_argument("--players", type=int, default=2, help="Players per team (1..11)")
    parser.add_argument("--reset-player", type=int, default=1, help="Player on first team to reset")
    parser.add_argument("--web-port", type=int, default=18080, help="Local web UI port")
    args = parser.parse_args()
    if any(not 1 <= port <= 65535 for port in (args.port, args.web_port)):
        parser.error("Ports must be 1..65535")
    if not 1 <= args.reset_player <= args.players:
        parser.error("Reset player must be 1..players")
    if not 1 <= args.players <= 11:
        parser.error("Players must be 1..11")
    if len(set(args.teams)) != 2 or any(not 1 <= team <= 255 for team in args.teams):
        parser.error("Team IDs must be distinct and in 1..255")
    return args


def main():
    args = parse_args()
    referee = Referee(args)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.web_port), handler_for(referee))
    except OSError:
        referee.sock.close()
        raise
    worker = threading.Thread(target=referee.run, daemon=True)
    worker.start()
    print(f"裁判盒：http://127.0.0.1:{args.web_port}  UDP → {args.target}:{args.port}", flush=True)
    print("初始状态 INITIAL；Ctrl+C 退出。退出前请先点击 FINISHED。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        referee.stop.set()
        worker.join()
        server.server_close()
        referee.sock.close()


if __name__ == "__main__":
    main()
