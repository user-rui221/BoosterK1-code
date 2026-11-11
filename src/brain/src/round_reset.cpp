#include "brain.h"
#include <algorithm>
#include <cctype>
#include <sstream>

void Brain::roundResetCallback(const std_msgs::msg::String &msg) {
    std::lock_guard<std::recursive_mutex> lock(localizationMutex);
    std::istringstream input(msg.data);
    string id, extra;
    int team = 0, player = 0;
    if (!(input >> id >> team >> player) || (input >> extra) || id.size() != 32 ||
        !std::all_of(id.begin(), id.end(), [](unsigned char c) { return std::isxdigit(c); }) ||
        team != config->get_team_id() || player != config->get_player_id()) return;
    auto reply = [&](const string &status) {
        std_msgs::msg::String response;
        response.data = msg.data + " " + status;
        roundResetStatus->publish(response);
    };
    if (get_parameter(GAME_AGENT_MODE_PARAM).as_bool()) {
        reply("agent_mode");
        return;
    }
    if (std::find(completedResetIds.begin(), completedResetIds.end(), id) != completedResetIds.end()) {
        reply("complete");
        return;
    }
    if (!pendingResetId.empty() && pendingResetId != id) {
        reply("busy");
        return;
    }
    pendingResetId = id;
    roundResetPending = true;
}

void Brain::resetRound() {
    // Called under localizationMutex by tick(), never from a ROS callback.
    const auto now = get_clock()->now();
    tree->halt();
    client->setVelocity(0, 0, 0);
    // Always send an explicit stop, even if an interrupted BT node already stopped.
    client->RLVisionKick(false);
    client->robocupWalk();
    tree->resetRound();
    ++roundGeneration;
    roundResetTime = now;
    client->resetRound();

    data->ballDetected = false;
    data->ball = GameObject();
    data->tmBall = GameObject();
    data->ball.timePoint = data->tmBall.timePoint = now;
    data->robotBallAngleToField = 0;
    data->lose_ball = false;
    data->setRobots({});
    data->setObstacles({});
    data->setGoalposts({});
    data->setMarkings({});
    data->setFieldLines({});
    data->visionBox = VisionBox();
    data->camConnected = false;
    data->realGameSubState = "NONE";
    data->kickDir = 0;
    data->kickType = "shoot";
    data->isDirectShoot = data->isKickingOff = data->isFreekickKickingOff = false;
    data->kickoffStartTime = data->freekickKickoffStartTime = now;
    lastScore = data->score;
    kickoffBallPos = {};
    kickoffWaitTime = lastTmBallPosTime = now;
    lastSeenRealBallTime = rclcpp::Time(0, 0, RCL_ROS_TIME);
    data->tmCmdId = data->tmMyCmd = data->tmMyCmdId = data->tmReceivedCmd = 0;
    data->tmImLead = true;
    data->tmImAlive = false;
    data->tmMyCost = 0;
    data->tmMyCostRank = data->myStrikerIDRank = 0;
    data->tmImInVisualKick = data->shouldExitRLVisionKick = false;
    data->tmLastCmdChangeTime = now;
    for (auto &tm : data->tmStatus) {
        tm = TMStatus();
        tm.timeLastCom = now;
    }
    data->recoveryPerformed = false;
    data->recoveryPerformedRetryCount = 0;
    // Keep real sensor state (odom, IMU/head, recovery state/mode), not old field calibration.
    data->odomToField = {};
    data->robotPoseToField = data->robotPoseToOdom;
    data->lastSuccessfulLocalizeTime = now;
    data->timeLastDet = data->timeLastLineDet = now;
    data->groundTruthReceived = false;
    data->groundTruthBlocked = true;
    data->groundTruthKickActive = false;
    roundNeedsLocalization = true;
    roundResetPending = false;
    RCLCPP_INFO(get_logger(), "Round reset complete: generation=%lu; INITIAL, waiting for fresh localization", roundGeneration);
    if (!pendingResetId.empty()) {
        completedResetIds.push_back(pendingResetId);
        if (completedResetIds.size() > 256) completedResetIds.pop_front();
        std_msgs::msg::String status;
        status.data = pendingResetId + " " + std::to_string(config->get_team_id()) + " " +
            std::to_string(config->get_player_id()) + " complete";
        roundResetStatus->publish(status);
        pendingResetId.clear();
    }
}
