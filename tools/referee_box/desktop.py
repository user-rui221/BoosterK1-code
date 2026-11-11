#!/usr/bin/env python3
"""Linux desktop referee box; run directly or package with PyInstaller."""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QVBoxLayout, QWidget)

from desktop_core import Connection, Sender
from referee_box import LABELS, STATES


class Events(QObject):
    report = Signal(int, str)
    finished = Signal()
    reset_status = Signal(str)


class SettingsDialog(QDialog):
    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("连接设置")
        self.resize(450, 340)
        self.connection = connection
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.finished.connect(self.docker_result)
        self.process.errorOccurred.connect(self.docker_error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.docker_timeout)
        self.phase = ""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.target = QLineEdit()
        self.target.setPlaceholderText("接收端 IPv4 地址或主机名")
        self.discover = QPushButton("从 Docker 选择…")
        self.discover.clicked.connect(self.docker_list)
        row = QHBoxLayout()
        row.addWidget(self.target)
        row.addWidget(self.discover)
        form.addRow("目标地址", row)
        self.port = self.spin(1, 65535)
        self.team1 = self.spin(1, 255)
        self.team2 = self.spin(1, 255)
        self.players = self.spin(1, 11)
        self.reset_player = self.spin(1, 11)
        self.kickoff = QComboBox()
        self.kickoff.addItems(["第一队", "第二队"])
        for label, field in (("UDP 端口", self.port), ("第一队队号", self.team1),
                             ("第二队队号", self.team2), ("每队人数", self.players), ("开球队", self.kickoff),
                             ("重置第一队球员编号", self.reset_player)):
            form.addRow(label, field)
        layout.addLayout(form)
        self.note = QLabel("端口需与接收节点一致。Docker bridge 模式下，\n宿主机的 127.0.0.1 通常不能直接访问容器。")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        files = QHBoxLayout()
        load = QPushButton("导入配置…")
        load.clicked.connect(self.import_config)
        save = QPushButton("导出配置…")
        save.clicked.connect(self.export_config)
        files.addWidget(load)
        files.addWidget(save)
        layout.addLayout(files)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept_config)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.fill(connection)

    @staticmethod
    def spin(lo, hi):
        result = QSpinBox()
        result.setRange(lo, hi)
        return result

    def fill(self, c):
        self.target.setText(c.target)
        for key in ("port", "team1", "team2", "players", "reset_player"):
            getattr(self, key).setValue(getattr(c, key))
        self.kickoff.setCurrentIndex(c.kickoff)

    def value(self):
        return Connection(self.target.text().strip(), self.port.value(), self.team1.value(),
                          self.team2.value(), self.players.value(), self.kickoff.currentIndex(), self.reset_player.value()).validate()

    def accept_config(self):
        try:
            self.connection = self.value()
        except ValueError as error:
            QMessageBox.warning(self, "配置无效", str(error))
            return
        self.accept()

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入连接配置", "", "JSON (*.json)")
        if path:
            try:
                self.fill(Connection.read(path))
            except (OSError, ValueError, TypeError) as error:
                QMessageBox.warning(self, "导入失败", str(error))

    def export_config(self):
        try:
            value = self.value()
        except ValueError as error:
            QMessageBox.warning(self, "配置无效", str(error))
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出连接配置", "referee-connection.json", "JSON (*.json)")
        if path:
            try:
                value.save(path)
            except OSError as error:
                QMessageBox.warning(self, "导出失败", str(error))

    def docker_list(self):
        self.phase = "list"
        self.docker_run(["ps", "--format", "{{.ID}}\t{{.Names}}"])

    def docker_run(self, args):
        self.discover.setEnabled(False)
        self.note.setText("正在读取 Docker…")
        self.timer.start(5000)
        self.process.start("docker", args)

    def docker_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.timer.stop()
            self.discover.setEnabled(True)
            self.note.setText("未找到 Docker。可手动填写地址；不需要安装 Docker。")

    def docker_timeout(self):
        self.phase = "timeout"
        self.process.kill()

    def docker_result(self, code, _status):
        self.timer.stop()
        self.discover.setEnabled(True)
        output = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        if self.phase == "timeout":
            self.note.setText("Docker 查询超时，请检查服务或手动填写地址。")
            return
        if code != 0:
            self.note.setText("Docker 查询失败（请检查服务或访问权限）：\n" + output[:300])
            return
        if self.phase == "list":
            entries = [line for line in output.splitlines() if "\t" in line]
            if not entries:
                self.note.setText("没有运行中的容器，请启动仿真或手动填写地址。")
                return
            labels = [line.split("\t", 1)[1] for line in entries]
            name, ok = QInputDialog.getItem(self, "选择仿真容器", "容器", labels, 0, False)
            if ok:
                container_id = entries[labels.index(name)].split("\t", 1)[0]
                self.phase = "inspect"
                self.docker_run(["inspect", "--format", "{{json .NetworkSettings.Networks}}", container_id])
        else:
            try:
                networks = json.loads(output)
                choices = [f"{key}  —  {value['IPAddress']}" for key, value in networks.items() if value.get("IPAddress")]
                if not choices:
                    self.note.setText("该容器没有独立 IPv4 地址，可能使用 host 网络；请手动填写地址。")
                    return
                choice, ok = (choices[0], True) if len(choices) == 1 else QInputDialog.getItem(self, "选择网络", "容器网络", choices, 0, False)
                if ok:
                    self.target.setText(choice.split("  —  ", 1)[1])
                    self.note.setText("已读取容器 IP。请核对接收端口；容器重建后应重新选择。")
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                self.note.setText("无法解析 Docker 网络信息：" + str(error))

    def done(self, result):
        self.timer.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        super().done(result)


class RefereeWindow(QWidget):
    def __init__(self, config_path=None):
        super().__init__()
        self.setWindowTitle("RoboCup 裁判盒")
        self.resize(460, 330)
        self.config_path = Path(config_path) if config_path else Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)) / "connection.json"
        self.connection = Connection()
        config_error = ""
        if self.config_path.exists():
            try:
                self.connection = Connection.read(self.config_path)
            except (OSError, ValueError, TypeError) as error:
                config_error = "配置加载失败，请重新设置：" + str(error)
        self.sender = None
        self.events = Events(self)
        self.events.report.connect(self.report)
        self.events.finished.connect(self.finished)
        self.events.reset_status.connect(self.reset_status)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.pin = QCheckBox("窗口置顶")
        self.pin.toggled.connect(self.set_pinned)
        self.settings = QPushButton("连接设置…")
        self.settings.clicked.connect(self.configure)
        top.addWidget(self.pin)
        top.addStretch()
        top.addWidget(self.settings)
        layout.addLayout(top)
        self.current = QLabel("INITIAL · 尚未发送")
        self.current.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current.setStyleSheet("font-size:22px;font-weight:600;padding:10px;")
        layout.addWidget(self.current)
        grid = QGridLayout()
        self.buttons = []
        for i, (state, label) in enumerate(zip(STATES, LABELS)):
            button = QPushButton(f"{state}\n{label}")
            button.setMinimumHeight(58)
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, i=i: self.change(i))
            grid.addWidget(button, i // 3, i % 3, 1, 2 if i == 4 else 1)
            self.buttons.append(button)
        layout.addLayout(grid)
        self.reset_button = QPushButton("重置本轮 → INITIAL")
        self.reset_button.setEnabled(False)
        self.reset_button.clicked.connect(self.reset_round)
        layout.addWidget(self.reset_button)
        self.reset_label = QLabel("清理指定机器人的本轮状态；机器人和球的位置不会复位。")
        self.reset_label.setWordWrap(True)
        layout.addWidget(self.reset_label)
        self.toggle = QPushButton("开始发送 INITIAL")
        self.toggle.clicked.connect(self.toggle_send)
        layout.addWidget(self.toggle)
        self.target_label = QLabel()
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)
        self.status = QLabel(config_error or "未发送 · 先检查连接设置，再开始发送")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        hint = QLabel("发送计数不代表机器人已收到。停止发送不会让机器人停车。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;font-size:11px;")
        layout.addWidget(hint)
        self.update_target()

    def update_target(self):
        c = self.connection
        self.target_label.setText(f"目标：{c.target or '未设置'}:{c.port}  |  队号 {c.team1} / {c.team2}  |  {c.players} 人/队  |  重置：队{c.team1} / 球员{c.reset_player}")

    def set_pinned(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def configure(self):
        dialog = SettingsDialog(self.connection, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                dialog.connection.save(self.config_path)
            except OSError as error:
                QMessageBox.warning(self, "保存失败", str(error))
                return
            self.connection = dialog.connection
            self.update_target()
            self.status.setText("连接配置已保存 · 尚未发送")

    def toggle_send(self):
        if self.sender:
            self.sender.stop()
            self.reset_button.setEnabled(False)
            self.toggle.setEnabled(False)
            for button in self.buttons:
                button.setEnabled(False)
            self.status.setText("正在停止发送…")
            return
        try:
            self.connection.validate()
        except ValueError:
            self.configure()
            return
        self.sender = Sender(self.connection, self.events.report.emit, self.events.finished.emit,
                             self.events.reset_status.emit)
        self.reset_button.setEnabled(True)
        self.settings.setEnabled(False)
        self.toggle.setText("停止发送")
        self.status.setText("正在解析目标地址…")
        self.select(0)
        for button in self.buttons:
            button.setEnabled(True)
        self.sender.start()

    def select(self, state):
        self.current.setText(f"{STATES[state]} · {LABELS[state]}")
        for i, button in enumerate(self.buttons):
            colour = "#15803d" if state == 3 else "#2563eb"
            button.setStyleSheet(f"background:{colour};color:white;font-weight:600;" if i == state else "")

    def change(self, state):
        if self.sender:
            self.sender.change(state)
            self.select(state)

    def reset_round(self):
        if self.sender:
            self.sender.reset_round()
            self.select(0)
            self.reset_status("pending")

    def reset_status(self, status):
        if not self.sender:
            return
        messages = {
            "pending": "正在等待 brain 清理完成…",
            "complete": "brain 清理完成，保持 INITIAL；等待重新定位。未确认底层物理停车。",
            "timeout": "未收到 brain 完成反馈。保持 INITIAL；检查接收端/队号/球员编号后重试。",
            "agent_mode": "brain 处于 agent 模式，拒绝裁判盒重置。保持 INITIAL。",
            "busy": "brain 正在处理另一个重置请求。保持 INITIAL，请重试。",
        }
        self.reset_label.setText(messages.get(status, status))
        self.reset_button.setEnabled(status != "pending")
        self.reset_button.setText("重试本轮重置" if status in ("timeout", "agent_mode", "busy") else "重置本轮 → INITIAL")
        for button in self.buttons:
            button.setEnabled(status == "complete")

    def report(self, count, error):
        self.status.setText(f"发送失败：{error}" if error else f"正在发送 · {count} 个 UDP 包 · 每 0.5 秒发送")
        self.status.setStyleSheet("color:#b91c1c;" if error else "")

    def finished(self):
        self.sender = None
        self.reset_button.setEnabled(False)
        self.toggle.setEnabled(True)
        self.toggle.setText("开始发送 INITIAL")
        self.settings.setEnabled(True)
        for button in self.buttons:
            button.setEnabled(False)
        if not self.status.text().startswith("发送失败"):
            self.status.setText("已停止发送 · 接收端可能仍保留最后状态")
        self.current.setText("已停止发送")

    def closeEvent(self, event):
        if self.sender:
            self.sender.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("RoboCupTools")
    app.setApplicationName("RefereeBox")
    app.setStyle("Fusion")
    window = RefereeWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
