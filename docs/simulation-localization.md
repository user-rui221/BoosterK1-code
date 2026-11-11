# 仿真自身定位来源切换

brain 支持两种启动配置：

- vision（默认）：原有视觉地标定位与里程计更新。
- simulation_ground_truth：直接采用 Booster Studio 的物理真值，仅替换机器人自身定位；球、机器人、障碍物仍来自原有感知链路。

修改参数后必须重启 brain。localization.* 参数为只读参数，运行期间的 ros2 param set 会被拒绝，避免配置已改变但订阅仍未改变。

## 使用方法

以下命令在仿真容器的项目根目录执行。完整启动会按现有脚本先停止旧节点，再启动 vision、brain 和 game_controller：

~~~bash
./scripts/sim_start.sh localization_source:=simulation_ground_truth
~~~

回到视觉定位：

~~~bash
./scripts/sim_start.sh localization_source:=vision
~~~

只启动 brain（需先确保没有另一份 brain 正在控制同一机器人）：

~~~bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch brain launch.py sim:=true localization_source:=simulation_ground_truth
~~~

也可在 src/brain/config/config.yaml 的 brain_node.ros__parameters 下修改：

~~~yaml
localization:
  source: simulation_ground_truth
  ground_truth_topic: /soccer/sim/localization/robot_pose
  timeout_sec: 0.5
  translation_x: 0.0
  translation_y: 0.0
  rotation_yaw: 0.0
~~~

配置优先级从低到高为 config.yaml、config_local.yaml、~/agents/booster_soccer/brain.yaml、显式 launch 参数。sim:=true 仅启用仿真时间，不隐式选择真值。

所有配置均可通过 localization_ 前缀的 launch 参数覆盖，例如：

~~~bash
ros2 launch brain launch.py sim:=true \
  localization_source:=simulation_ground_truth \
  localization_ground_truth_topic:=/robot1/soccer/sim/localization/robot_pose \
  localization_rotation_yaw:=3.141592653589793
~~~

多机器人话题使用平台前缀，例如 /robot1/soccer/sim/localization/robot_pose；配置项是完整话题名，不会自动追加 robot.robot_name。请先用 ros2 topic list 核对实际名称。

## 坐标约定

平台的 pose_publisher_extension.py 从 MuJoCo root/freejoint 的 qpos 读取世界 x、y 和四元数 yaw，消息类型为 geometry_msgs/msg/Pose2D。单位为米、弧度。

brain 以本方球门位于 -X、对方球门位于 +X 为场地约定。输入转换为：

~~~text
x_field = cos(yaw_offset) * x_world - sin(yaw_offset) * y_world + translation_x
y_field = sin(yaw_offset) * x_world + cos(yaw_offset) * y_world + translation_y
theta_field = wrap(theta_world + yaw_offset)
~~~

上述 yaw_offset 对应 localization.rotation_yaw，不是行走补偿 robot.yaw_offset。进攻世界 -X 且原点相同的场景应设置 rotation_yaw=π。开球方不代表进攻方向；当前不会根据裁判信息自动换边，换边后需要调整配置并重启。零变换适用于世界坐标与本方场地坐标一致的场景，实际队伍方向需核实。

## 更新与失效行为

- 真值是场地位姿唯一来源。8 类 SelfLocate 节点和手动 CalibrateOdom 在此模式下不执行定位写入。
- 原始里程计仍接收；它不覆盖 robotPoseToField，只用于维持一致的 odomToField 变换。odom_factor 不缩放真值。
- 已观测到的球等对象保留场地坐标，机器人运动后重新计算相对位置；不会每帧用新机器人位姿搬移旧观测。
- 尚未收到真值、接收到 NaN/Inf、接收超时或发现仿真时钟回退时，禁止非零行走，并停止执行行为树。若有持续视觉踢球，会发送退出请求和行走模式请求。
- 真值恢复后重置旧感知缓存，等待新观测，行为树重新开始执行。
- 超时使用 steady_clock，即使 ROS 仿真时间暂停也会生效。Pose2D 没有 header，检测的是接收新鲜度，不能识别上游反复发布的过期数据，也不能保证与视觉严格同帧。
- 当前停止请求没有新增底层应答确认。发出零速和退出请求不等于已测得机器人停止；实际运动效果仍须在仿真中验证。

启动日志输出实际来源、话题、超时、坐标变换，以及等待真值、失效和恢复状态。真值有效时，原有 /booster_soccer/robot_pose 继续输出 brain 使用的场地坐标；失效时停止发布该位姿，避免消费者误认为旧坐标仍在更新。

## 构建与测试

在仿真容器项目根目录执行：

~~~bash
source install/setup.bash
CMAKE_BUILD_PARALLEL_LEVEL=2 ./scripts/build.sh --packages-select brain --parallel-workers 1
python3 tools/localization/test_ground_truth.py
~~~

集成测试使用独立 ROS_DOMAIN_ID=97、localhost 和专用机器人话题，不向当前仿真机器人发送控制请求。请确保该测试域未另作机器人控制用途。队友通信关闭；裁判回包目标为禁止发送的广播地址，不进入当前裁判状态。

测试覆盖：
1. 首帧等待、8 类视觉定位和手动校准隔离、里程计不覆盖、断流、非法值、恢复。
2. 平移、旋转和角度归一化。
3. vision 模式保持视觉/里程计链路，不订阅真值。
4. 视觉踢球断流退出并在恢复后重新启动。
5. 配置运行期修改被拒绝。
6. READY 使用真值判断到位并发出零速。
7. 球坐标转换与移动后的场地坐标记忆。
8. 仿真时钟回退恢复、仿真时间冻结时接收超时仍生效。

这些测试验证实际 brain 二进制的数据处理与控制请求，不验证物理机器人轨迹、底层停止应答、多机器人换边或完整比赛效果。
