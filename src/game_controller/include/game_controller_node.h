#pragma once

#include <iostream>
#include <string>
#include <vector>
#include <map>
#include <mutex>
#include <atomic>
#include <chrono>
#include <netinet/in.h>
#include <std_msgs/msg/string.hpp>
#include <rclcpp/rclcpp.hpp>

#include "RoboCupGameControlData.h"

#include "game_controller_interface/msg/game_control_data.hpp"

using namespace std;

class GameControllerNode : public rclcpp::Node
{
public:
    GameControllerNode(string name);
    ~GameControllerNode();

    void init();

    void spin();

private:
    bool check_ip_white_list(string ip);

    void handle_packet(HlRoboCupGameControlData &data, game_controller_interface::msg::GameControlData &msg);

    struct ResetPeer {
        sockaddr_in address;
        std::chrono::steady_clock::time_point seen;
    };
    std::mutex resetMutex;
    std::map<string, ResetPeer> resetPeers;
    std::atomic<bool> stopping{false};
    bool enableTestReset = true;
    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr resetPublisher;
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr resetStatus;
    int _port;
    bool _enable_ip_white_list;
    vector<string> _ip_white_list;

    // UDP Socket
    int _socket;
    // thread
    
    thread _thread;

    // Ros2 publisher
    rclcpp::Publisher<game_controller_interface::msg::GameControlData>::SharedPtr _publisher;
};