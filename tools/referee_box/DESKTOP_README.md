# Linux 桌面裁判盒

独立 Qt 小窗口，支持置顶及五种比赛主状态。无需 ROS 环境；连接配置不包含固定项目路径、用户名或容器名。启动后不自动发包，点击“开始发送 INITIAL”才开始每 0.5 秒发送。

## 使用打包版

解压 `RefereeBox-linux-x86_64.tar.gz`，双击目录里的 `RefereeBox`，或在该目录运行 `./RefereeBox`。整个目录（包括 `_internal` 依赖目录）必须一起保留，不能只复制可执行文件。可将目录移到任意有执行权限的位置。

此包为 Linux x86_64 构建，不适用于 ARM。不同发行版仍依赖 glibc 和基本桌面图形库；建议在与构建系统相同或较新的 Ubuntu 桌面使用。若启动失败，从终端启动以查看错误。若提示 Qt xcb 依赖缺失，检查发行版的 `libxcb-cursor0` 等桌面库。其他发行版/ARM 用户可用源码在本机运行或重新打包。

## 首次连接

1. 点击“连接设置”，填写接收端 IP/主机名、UDP 端口、队号、人数及开球队。
2. 本机 Docker bridge 仿真可点“从 Docker 选择”，选择运行中的容器和网络；此操作只读取 Docker，不会修改容器，也不会申请 sudo。没有 Docker 或无权限时手动填写即可。远程容器的内部 IP 不一定可达，应使用实际可达地址和映射端口。
3. 接收节点必须监听相同端口。建议使用独立的 `38380`，避免与官方 `3838` 状态混用。接收端示例：`ros2 run game_controller game_controller_node --ros-args -p port:=38380`，应先停止向同一话题发布的旧接收节点。
4. 保存设置后点击“开始发送 INITIAL”，再点击所需比赛状态。通常按 INITIAL → READY → SET → PLAYING → FINISHED 操作。
5. 勾选“窗口置顶”，即可边看仿真边按按钮。桌面环境可能限制窗口置顶行为。

容器重建后 IP 可能变化，应重新使用 Docker 选择功能。保存配置不会自动追踪容器地址。

## 配置分享

设置窗口支持导入、导出 JSON。队友导入后应确认其本机可达的地址、端口和队号，再保存。配置自动保存在 Qt 标准用户配置目录；Linux 通常为 `$XDG_CONFIG_HOME/RoboCupTools/RefereeBox/connection.json`，未设置 XDG_CONFIG_HOME 时为 `~/.config/RoboCupTools/RefereeBox/connection.json`。不在程序安装目录保存个人配置。

发送期间连接设置锁定，防止状态中途被发往其他目标。停止发送后可以修改。每次重新开始均从 INITIAL 开始，不恢复上一次 PLAYING。

## 状态含义与边界

- UDP 采用本项目已实现的 packed 198 字节 v19 协议；其他版本接收器不保证兼容。
- 第一版不提供计时、判罚或比分编辑：时间固定600秒，比分0:0，在场球员无处罚，人数范围1～11。开球队可选。
- “已发送”只是本机 UDP 发送调用成功，不证明机器人已收到。应在接收端检查日志或 `/booster_soccer/game_controller` ROS 话题。
- **停止发送和关闭窗口均不会额外发送 FINISHED，也不会让机器人自动停车。** 需要结束时先点击 FINISHED，确认接收端处理后再停止发送。INITIAL 也不等于紧急停止，动作行为由机器人策略决定。
- 本程序不关闭仿真内部自动判罚、摆球、重开等规则，也不切换底层 WALK 模式。
- 不要同时运行指向同一接收节点的网页裁判盒和桌面裁判盒，否则比赛状态会互相覆盖。

## 从源码运行 / 构建

整个 `tools/referee_box` 目录可以单独复制给队友，不需要其他项目文件。需要 Python 3.10+；建议使用 uv，或者系统安装 Python venv 与 pip。

```bash
./setup_linux.sh
./run_desktop.sh
```

安装依赖需要联网。若系统缺少 ensurepip，可使用 uv，或安装发行版的 python3-venv 包。脚本根据自身所在目录定位文件，不依赖终端当前目录。

测试与打包：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s . -p 'test_*.py' -v
./build_linux.sh
```

构建产物位于 `dist/RefereeBox-linux-<架构>.tar.gz`。源码依赖固定为 PySide6-Essentials 6.8.3（Qt for Python）和 PyInstaller 6.22.3；分发时请保留整个包及第三方许可证。

构建基线：Ubuntu 22.04 / glibc 2.35 / x86_64。当前分发包包含私有 libxcb-cursor 运行库及其版权说明。源码安装脚本在 Ubuntu/Debian 缺少该库时，会通过 apt-get download 下载到程序私有目录，无需管理员权限，不修改系统。其他发行版应自行安装对应桌面库。

## 重置本轮测试

更新后的 `brain` 和 `game_controller` 必须重新启动，旧进程不会加载新功能。

1. 在连接设置中核对目标地址/UDP端口、第一队队号，以及“重置第一队球员编号”（默认1）。旧版连接配置自动补充球员编号1。
2. 开始发送后，点击 **重置本轮 → INITIAL**。该操作只重置所指定的一台 brain；普通比赛状态包仍发送给两队。
3. 等待 **brain 清理完成**。等待或超时时，比赛状态按钮禁用，持续发送 INITIAL；8秒没有反馈显示超时，可点“重试本轮重置”，重试沿用同一个请求编号。
4. 保持 INITIAL，等待新定位，再进入 READY → SET → PLAYING。真值模式必须收到新的有效位姿；vision 模式需要重新获得入场定位，机器人应摆在支持的己方边线入场位置。定位未建立时不允许本轮行走。

已经处于 INITIAL 时可以再次点击“重置本轮”，会创建新的重置请求。普通 INITIAL 按钮只在从其他状态切入时触发一次自动清理，重复广播 INITIAL 不会反复清空定位。

清理内容包括当前行为树动作、球和视觉缓存、协作决策、开球等待、定位标定、动作与避障计时。保留机器人实时里程计/姿态传感器、静态配置和裁判提供的队号、开球方、判罚等信息。发送视觉踢球停止、切回 WALK 和零速度指令；INITIAL 持续零速度。

**反馈代表 brain 已完成内部清理并发布停止请求，不代表底层已应答或实际身体已停稳，也不代表重新定位成功。机器人、球及仿真时钟不会自动复位。** 需要相同物理起点时，先停车并在仿真界面摆回机器人和球，再请求重置；不要把单独重启 brain 当作停车操作。

若超时，核对两个 ROS 节点是否使用新构建、UDP目标是否可达、第一队/球员编号是否匹配，以及 `game_controller` 的 `enable_test_reset` 是否开启。agent 模式下 brain 会拒绝裁判盒重置。停止发送不会取消已经发出的重置请求。

协议通过现有裁判 UDP 端口发送 `RBR1 <32位十六进制请求ID> <队号> <球员号>`，经 `/booster_soccer/round_reset/request` 转发到 brain，完成状态通过 `/booster_soccer/round_reset/status` 返回，再从同一 UDP 端口回复 `RBA1 ... complete`。同一 brain 进程保留最近256个已完成ID用于去重；重启进程后不承诺跨进程去重。普通198字节裁判协议保持不变。此扩展与原裁判协议一样没有身份认证，适用于受信任调试网络，可设置 `enable_test_reset:=false` 禁用；已有IP白名单同样适用。
