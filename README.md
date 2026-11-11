本仓库是在[https://github.com/BoosterRobotics/robocup_demo]()基础上进行的改进。
相关说明文档在[https://github.com/user-rui221/BoosterK1]()仓库中。

## 编译
`./scripts/build_no_cuda.sh`
## 运行自定义裁判盒+启动机器人
（1）启动裁判盒
[https://github.com/user-rui221/BoosterK1]()有介绍如何安装和启动自定义裁判盒
（2）启动机器人
关闭定位算法模式（直接调用平台提供的定位数据）：
```
GC_PORT=38380 bash scripts/sim_start.sh localization_source:=simulation_ground_truth
```
开启定位算法模式：
`GC_PORT=38380 bash scripts/sim_start.sh `
