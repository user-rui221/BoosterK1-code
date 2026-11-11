# 浏览器视觉检测查看器

只读订阅相机与 `/booster_soccer/detection`，不发布 ROS 消息、不控制机器人。无需 DISPLAY、X11 或额外 pip 安装；ROS、消息包、OpenCV、NumPy使用现有仿真容器依赖。

## 启动

以下两个命令分别保持在两个宿主机终端中运行。在项目根目录执行。示例容器名 `vdc76-k1` 和容器内项目路径 `/root/workspace/robocup_demo` 请按实际环境替换；代理的 `--container` 参数也需保持一致：

```bash
docker exec -it vdc76-k1 bash -lc 'cd /root/workspace/robocup_demo; bash tools/vision_viewer/run.sh'
```

```bash
python3 tools/vision_viewer/local_proxy.py --container vdc76-k1
```

打开 http://127.0.0.1:18081 。两端默认都只绑定回环地址：宿主机转接通过 `docker exec` 读取容器回环HTTP，不需要开放Docker端口或暴露局域网服务。宿主机用户需已有Docker访问权限。查看器不随仿真自动重启；端口占用时不要重复启动。

分别 Ctrl+C 退出两个前台进程。若关闭网页，服务仍继续运行。当前开发会话启动的容器查看器日志为 `/tmp/vision_viewer.log`，宿主机转接运行在独立终端会话中。

## 端口已被占用

如果之前已启动服务，直接打开 http://127.0.0.1:18081 ，不要再次启动同一服务。
`Address already in use`表示第二个进程无法监听同一个端口，不表示原有查看器崩溃。
新版启动遇到此情况会给出中文提示并退出，不会停止已有进程。

只读确认容器查看器：

```bash
docker exec vdc76-k1 pgrep -af '[v]ision_viewer/viewer.py'
```

## 功能与状态

- 检测框使用约1px屏幕线宽、12px标签，图中显示“#序号 简称”（L/T/X/P/Post等），完整类别和置信度保留在列表；标签尽量错开并用引线对应检测框。
- 图中编号与列表一一对应，过滤地标不重编号；编号只对应当前帧，不代表跨帧跟踪ID。支持只看 L/T/X/P 定位地标、暂停与继续、保存带框截图。
- 右侧显示 `position_projection` 投影估计，可展开 `position` 深度估计；单位米，为视觉节点基座相对坐标，不是球场坐标。
- 图像缓冲最近90帧，选取与最新检测时间戳最接近的图像，默认允许100ms差值。匹配成功时显示对应的历史图像，不把旧框硬套到最新图像。
- 超过时间差、检测中断超过2秒、相机中断超过2秒时隐藏旧框；提示等待相机、等待检测或无目标。检测时间差是ROS消息header之差；消息新鲜度使用单调墙钟。
- 相机或检测时间戳回退超过1秒时清理相关缓冲。网页约每200ms请求一次，实际刷新率取决于Docker转接和图像编码耗时。
- 查看器不会自动启动vision；缺少检测节点时只显示原图。

检测节点未运行时，可在容器中单独启动视觉，不必启动brain（先确认没有已有vision节点，避免重复实例）：

```bash
cd /root/workspace/robocup_demo
source install/setup.bash
export FASTRTPS_DEFAULT_PROFILES_FILE=/opt/booster/BoosterRos2/fastdds_profile_udp_only.xml
ros2 launch vision launch.py sim:=true save_data:=false
```

2026-11-10首次启动曾因vision在save_data=false时解引用空日志对象而以-11退出；现已修复vision_node.cpp并重新构建。相同参数运行持续发布检测，浏览器真实识别框、类别和坐标已验证，采样图像与检测时间差0ms。修复后日志 `/tmp/vision_viewer_vision_fixed.log`。显示正常不代表视觉测距或场地定位精度已验证。

## 其他话题

在容器的启动命令末尾添加参数：

```bash
bash tools/vision_viewer/run.sh --image-topic /my/image --raw --detection-topic /my/detection --max-delta-ms 100
```

默认相机 `/rgbd_camera/rgb/image_compressed` 使用 `sensor_msgs/CompressedImage`；`--raw`改用`sensor_msgs/Image`和cv_bridge。检测消息固定为`vision_interface/Detections`，不直接支持仿真器`vision_msgs/Detection2DArray`。两类订阅均采用sensor-data QoS。

## 验证

```bash
python3 -m unittest discover -s tools/vision_viewer -v
bash -n tools/vision_viewer/run.sh
```
