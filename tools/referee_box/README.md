# 简易仿真裁判盒

新增 Linux 独立桌面小窗口版本，见 [桌面版使用说明](DESKTOP_README.md)。下文为原网页版本。

Python 3 标准库实现，无需 pip 安装。浏览器中切换 INITIAL、READY、SET、PLAYING、FINISHED；程序每 0.5 秒发送一次当前状态，点击立即发送。启动状态为 INITIAL。

## 启动

以下命令均在项目根目录执行。先在运行 ROS 2 的仿真容器中加载环境并更新裁判接收节点的 launch 文件：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select game_controller --symlink-install
source install/setup.bash
```

使用独立 UDP 端口启动仿真节点（此脚本会按项目原有逻辑停止并重启节点）：

```bash
GC_PORT=38380 bash scripts/sim_start.sh
```

多机器人使用 `GC_PORT=38380 bash scripts/sim_start_multi.sh`。未设置 GC_PORT 时仍使用官方端口 3838。

如果自行管理节点，可停止原 game_controller 接收节点后，只启动替代接收实例，无需重新构建 launch 文件：

```bash
ros2 run game_controller game_controller_node --ros-args -p port:=38380
```

然后在宿主机新终端运行裁判盒（需能访问接收节点所在网络）：

```bash
python3 tools/referee_box/referee_box.py --target 127.0.0.1 --port 38380 --teams 1 2 --players 2
```

当前 Booster Studio 的 `vdc76-k1` 容器使用 Docker bridge 网络，宿主机的 `127.0.0.1` 不能直达容器的 38380。推荐在宿主机动态读取容器 IP 后启动：

```bash
REFEREE_TARGET=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' vdc76-k1)
python3 tools/referee_box/referee_box.py --target "$REFEREE_TARGET" --port 38380 --teams 1 2 --players 2
```

容器重建后 IP 可能变化，应重新执行上述命令。不要同时运行两份裁判盒。程序重启后须刷新网页再点击状态按钮。

在运行裁判盒的电脑浏览器打开 <http://127.0.0.1:18080>，按需点击状态。通常依次 INITIAL → READY → SET → PLAYING → FINISHED；也允许直接切换。READY 会让策略准备入场，SET 表示就绪等待，FINISHED 表示比赛结束；具体动作由行为树决定。

`127.0.0.1` 仅在裁判盒与接收端共享网络空间（例如容器使用 host 网络）时适用。桥接容器需要将 `--target` 改为可达容器 IP，或映射 UDP 38380 后向映射地址发送。若在容器内运行网页服务，可通过 SSH 本地端口转发访问，网页仅绑定回环地址。

默认队号与当前单机器人配置的队号 1 对应。多机器人脚本目前使用队号 29、30，各三人，应改为 `--teams 29 30 --players 3`。机器人 player_id 不应超过 `--players`。第一支队伍固定开球，在场球员无处罚，比分为 0，剩余时间固定 600 秒；本工具只切换主状态，不实现比赛计时和判罚。

## 检查

```bash
ros2 topic echo /booster_soccer/game_controller
```

点击按钮后，消息的 `state` 应分别是 0、1、2、3、4，且两队 `team_number` 正确。确保只有一个接收节点向此话题发布，brain 未开启忽略裁判消息的 agent mode。页面的发送计数只能证明本地发送调用成功，不能证明机器人已接收。

退出前先点击 FINISHED，并确认 ROS 话题已收到，再 Ctrl+C 停止程序；关闭网页不停止发送，Ctrl+C 不额外发送结束包。

独立端口隔离官方裁判状态，但不能关闭仿真器内部的自动处罚、摆球、重开等行为，也不负责切换机器人底层 WALK 模式。

本地测试（不启动仿真）：

```bash
python3 -m unittest discover -s tools/referee_box -p 'test_*.py' -v
```

## 重置本轮（桌面版与网页版）

网页新增“重置本轮 / 超时重试 → INITIAL”按钮，默认重置第一队1号球员，可用 `--reset-player 2` 选择第一队2号球员。页面每2秒刷新反馈。请求期间保持INITIAL并禁止切入运动状态；8秒未收到brain回执会提示重试。必须使用更新并重启后的brain及game_controller。

详细清理范围、定位前置条件、协议与故障排查见 [桌面版重置说明](DESKTOP_README.md#重置本轮测试)。反馈只确认brain内部清理；不确认底层物理停车，不自动复位机器人、球或仿真时钟。
