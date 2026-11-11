"""Portable settings and UDP sender. No ROS, Docker or GUI dependency."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import socket
import threading
import time
import uuid

from referee_box import make_packet


@dataclass(frozen=True)
class Connection:
    target: str = ""
    port: int = 38380
    team1: int = 1
    team2: int = 2
    players: int = 2
    kickoff: int = 0  # Index into the two teams, not a fixed team number.
    reset_player: int = 1  # Reset addresses one player on team1.

    def validate(self):
        if not isinstance(self.target, str) or not self.target.strip() or any(c.isspace() for c in self.target):
            raise ValueError("请填写目标 IPv4 地址或主机名，不要包含空格或端口。")
        for key, lo, hi in (("port", 1, 65535), ("team1", 1, 255),
                            ("team2", 1, 255), ("players", 1, 11), ("kickoff", 0, 1), ("reset_player", 1, 11)):
            value = getattr(self, key)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{key} 必须是 {lo}～{hi} 之间的整数。")
        if self.reset_player > self.players:
            raise ValueError("重置球员编号不能超过每队人数。")
        if self.team1 == self.team2:
            raise ValueError("两支队伍的队号不能相同。")
        return self

    @classmethod
    def read(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("不支持的配置格式，需要 schema_version=1。")
        fields = data.get("connection")
        if isinstance(fields, dict) and "reset_player" not in fields:
            fields["reset_player"] = 1  # Migrate existing schema v1 files.
        if not isinstance(fields, dict) or set(fields) != set(cls.__dataclass_fields__):
            raise ValueError("连接配置字段不完整或含未知字段。")
        return cls(**fields).validate()

    def save(self, path):
        self.validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps({"schema_version": 1, "connection": asdict(self)},
                                        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)


class Sender(threading.Thread):
    """Each session starts in INITIAL. Callbacks run on this daemon thread."""
    def __init__(self, connection, report, finished, reset_report=lambda status: None):
        super().__init__(daemon=True)
        self.connection = connection.validate()
        self.report = report
        self.finished = finished
        self.condition = threading.Condition()
        self.stopping = False
        self.state = 0
        self.revision = 0
        self.reset_report = reset_report
        self.reset_id = None
        self.reset_deadline = 0.0
        self.reset_timed_out = False

    def change(self, state):
        if type(state) is not int or state not in range(5):
            raise ValueError("Invalid match state")
        with self.condition:
            if self.reset_id is not None:
                return False
            self.state = state
            self.revision += 1
            self.condition.notify_all()

    def reset_round(self):
        with self.condition:
            # Retry the SAME operation after timeout; never create a second reset by retrying.
            self.reset_id = self.reset_id or uuid.uuid4().hex
            self.state = 0
            self.reset_timed_out = False
            self.reset_deadline = time.monotonic() + 8.0
            self.revision += 1
            self.reset_report("pending")
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()

    def run(self):
        sent = 0
        try:
            c = self.connection
            target = (socket.gethostbyname(c.target), c.port)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.setblocking(False)
                next_send, last_revision = 0.0, -1
                while True:
                    with self.condition:
                        if self.stopping:
                            break
                        now = time.monotonic()
                        if now >= next_send or last_revision != self.revision:
                            last_revision = self.revision
                            try:
                                packet = bytearray(make_packet(self.state, sent, [c.team1, c.team2], c.players))
                                packet[13] = (c.team1, c.team2)[c.kickoff]
                                sock.sendto(packet, target)
                                sent += 1
                                self.report(sent, "")
                                if self.reset_id and not self.reset_timed_out:
                                    request = f"RBR1 {self.reset_id} {c.team1} {c.reset_player}".encode("ascii")
                                    sock.sendto(request, target)
                            except OSError as error:
                                self.report(sent, str(error))
                            next_send = now + 0.5
                        try:
                            while True:
                                packet, peer = sock.recvfrom(512)
                                if peer != target or not self.reset_id:
                                    continue
                                prefix = f"RBA1 {self.reset_id} {c.team1} {c.reset_player} "
                                reply = packet.decode("ascii", errors="replace")
                                if reply == prefix + "complete":
                                    self.reset_id = None
                                    self.reset_report("complete")
                                elif reply in (prefix + "agent_mode", prefix + "busy"):
                                    self.reset_timed_out = True
                                    self.reset_report(reply[len(prefix):])
                        except BlockingIOError:
                            pass
                        if self.reset_id and not self.reset_timed_out and now >= self.reset_deadline:
                            self.reset_timed_out = True
                            self.reset_report("timeout")
                        self.condition.wait(timeout=0.03)
        except OSError as error:
            self.report(sent, str(error))
        finally:
            self.finished()
