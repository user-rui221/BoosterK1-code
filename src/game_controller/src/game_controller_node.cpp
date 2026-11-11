#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <algorithm>
#include <sstream>
#include <cctype>

#include "game_controller_node.h"

// Booster Studio simulator broadcasts the compact RoboCup v19 packet (198 bytes).
#pragma pack(push, 1)
struct SimRobotInfo
{
    uint8_t penalty;
    uint8_t secsTillUnpenalised;
    uint8_t warnings;
    uint8_t cautions;
};
struct SimTeamInfo
{
    uint8_t teamNumber;
    uint8_t fieldPlayerColour;
    uint8_t goalkeeperColour;
    uint8_t goalkeeper;
    uint8_t score;
    uint8_t penaltyShot;
    uint16_t singleShots;
    uint16_t messageBudget;
    SimRobotInfo players[20];
};
struct SimGameControlData
{
    char header[4];
    uint8_t version;
    uint8_t packetNumber;
    uint8_t playersPerTeam;
    uint8_t competitionType;
    uint8_t stopped;
    uint8_t gamePhase;
    uint8_t state;
    uint8_t setPlay;
    uint8_t firstHalf;
    uint8_t kickingTeam;
    int16_t secsRemaining;
    int16_t secondaryTime;
    SimTeamInfo teams[2];
};
#pragma pack(pop)
static_assert(sizeof(SimGameControlData) == 198, "Unexpected simulator GameControl packet size");

static uint8_t simSetPlayToHumanoidState(uint8_t setPlay)
{
    switch (setPlay) {
    case 0: return STATE2_NORMAL;
    case 1: return STATE2_DIRECT_FREEKICK;
    case 2: return STATE2_INDIRECT_FREEKICK;
    case 3: return STATE2_PENALTYKICK;
    case 4: return STATE2_THROW_IN;
    case 5: return STATE2_GOAL_KICK;
    case 6: return STATE2_CORNER_KICK;
    default: return STATE2_NORMAL;
    }
}

static uint8_t simGamePhaseToHumanoidState(uint8_t gamePhase)
{
    switch (gamePhase) {
    case 1: return STATE2_PENALTYSHOOT;
    case 2: return STATE2_OVERTIME;
    case 3: return STATE2_TIMEOUT;
    default: return STATE2_NORMAL;
    }
}

static void convertSimPacket(const SimGameControlData &sim, HlRoboCupGameControlData &data)
{
    data = {};
    std::memcpy(data.header, sim.header, sizeof(data.header));
    data.version = HL_GAMECONTROLLER_STRUCT_VERSION;
    data.packetNumber = sim.packetNumber;
    data.playersPerTeam = std::min<int>(sim.playersPerTeam, HL_MAX_NUM_PLAYERS);
    data.gameType = 0;
    data.state = sim.stopped && sim.state == STATE_PLAYING ? STATE_SET : sim.state;
    data.firstHalf = sim.firstHalf;
    data.kickOffTeam = sim.kickingTeam;
    data.secondaryState = sim.gamePhase == 0
        ? simSetPlayToHumanoidState(sim.setPlay)
        : simGamePhaseToHumanoidState(sim.gamePhase);
    data.secondaryStateInfo[0] = static_cast<char>(sim.kickingTeam);
    data.secondaryStateInfo[1] = 0;
    data.secsRemaining = static_cast<uint16_t>(std::max<int>(0, sim.secsRemaining));
    data.secondaryTime = static_cast<uint16_t>(std::max<int>(0, sim.secondaryTime));
    for (int i = 0; i < 2; ++i) {
        const auto &src = sim.teams[i];
        auto &dst = data.teams[i];
        dst.teamNumber = src.teamNumber;
        dst.fieldPlayerColour = src.fieldPlayerColour;
        dst.score = src.score;
        dst.penaltyShot = src.penaltyShot;
        dst.singleShots = src.singleShots;
        for (int j = 0; j < HL_MAX_NUM_PLAYERS; ++j) {
            // The legacy strategy always reads 11 slots, even in a 2-player match.
            dst.players[j].penalty = j < data.playersPerTeam
                ? (src.players[j].penalty == 11 ? PENALTY_SUBSTITUTE : src.players[j].penalty)
                : PENALTY_SUBSTITUTE;
            dst.players[j].secsTillUnpenalised = src.players[j].secsTillUnpenalised;
            dst.players[j].numberOfWarnings = src.players[j].warnings;
            dst.players[j].yellowCardCount = src.players[j].cautions;
            dst.players[j].redCardCount = src.players[j].penalty == 10 ? 1 : 0;
            dst.players[j].goalKeeper = (j + 1 == src.goalkeeper);
        }
    }
}

GameControllerNode::GameControllerNode(string name) : rclcpp::Node(name)
{
    _socket = -1;

    declare_parameter<int>("port", 3838);
    enableTestReset = declare_parameter<bool>("enable_test_reset", true);
    resetPublisher = create_publisher<std_msgs::msg::String>("/booster_soccer/round_reset/request", 10);
    resetStatus = create_subscription<std_msgs::msg::String>("/booster_soccer/round_reset/status", 10,
        [this](const std_msgs::msg::String &msg) {
            const auto pos = msg.data.rfind(' ');
            if (pos == string::npos) return;
            std::lock_guard<std::mutex> lock(resetMutex);
            auto peer = resetPeers.find(msg.data.substr(0, pos));
            if (peer == resetPeers.end() || stopping) return;
            const string reply = "RBA1 " + msg.data;
            sendto(_socket, reply.data(), reply.size(), 0,
                reinterpret_cast<const sockaddr *>(&peer->second.address), sizeof(sockaddr_in));
        });
    declare_parameter<bool>("enable_ip_white_list", false);
    declare_parameter<vector<string>>("ip_white_list", vector<string>{});

    get_parameter("port", _port);
    RCLCPP_INFO(get_logger(), "[get_parameter] port: %d", _port);
    get_parameter("enable_ip_white_list", _enable_ip_white_list);
    RCLCPP_INFO(get_logger(), "[get_parameter] enable_ip_white_list: %d", _enable_ip_white_list);
    get_parameter("ip_white_list", _ip_white_list);
    RCLCPP_INFO(get_logger(), "[get_parameter] ip_white_list(len=%ld)", _ip_white_list.size());
    for (size_t i = 0; i < _ip_white_list.size(); i++)
    {
        RCLCPP_INFO(get_logger(), "[get_parameter]     --[%ld]: %s", i, _ip_white_list[i].c_str());
    }

    _publisher = create_publisher<game_controller_interface::msg::GameControlData>("/booster_soccer/game_controller", 10);
}

GameControllerNode::~GameControllerNode()
{
    stopping = true;
    if (_thread.joinable()) _thread.join();
    if (_socket >= 0) close(_socket);
}


void GameControllerNode::init()
{
    _socket = socket(AF_INET, SOCK_DGRAM, 0);
    if (_socket < 0)
    {
        RCLCPP_ERROR(get_logger(), "socket failed: %s", strerror(errno));
        throw runtime_error(strerror(errno));
    }

    timeval timeout{0, 200000};
    setsockopt(_socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(_port);

    if (bind(_socket, (sockaddr *)&addr, sizeof(addr)) < 0)
    {
        RCLCPP_ERROR(get_logger(), "bind failed: %s (port=%d)", strerror(errno), _port);
        throw runtime_error(strerror(errno));
    }

    RCLCPP_INFO(get_logger(), "Listening for UDP broadcast on 0.0.0.0:%d", _port);
    RCLCPP_INFO(get_logger(), "Expected HlRoboCupGameControlData size: %ld", sizeof(HlRoboCupGameControlData));

    _thread = thread(&GameControllerNode::spin, this);
}

void GameControllerNode::spin()
{
    sockaddr_in remote_addr;
    socklen_t remote_addr_len = sizeof(remote_addr);

    HlRoboCupGameControlData data;
    game_controller_interface::msg::GameControlData msg;

    while (rclcpp::ok() && !stopping)
    {
        char buffer[sizeof(data) + 1]{};
        remote_addr_len = sizeof(remote_addr);
        ssize_t ret = recvfrom(_socket, buffer, sizeof(buffer), 0, (sockaddr *)&remote_addr, &remote_addr_len);
        if (ret < 0)
        {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) continue;
            RCLCPP_ERROR(get_logger(), "receiving UDP message failed: %s", strerror(errno));
            continue;
        }

        string remote_ip = inet_ntoa(remote_addr.sin_addr);
        if (!check_ip_white_list(remote_ip)) continue;
        if (ret >= 5 && std::memcmp(buffer, "RBR1 ", 5) == 0) {
            if (!enableTestReset || ret > 128) continue;
            std::istringstream input(string(buffer + 5, ret - 5));
            string id, extra;
            int team = 0, player = 0;
            if (!(input >> id >> team >> player) || (input >> extra) || id.size() != 32 ||
                !std::all_of(id.begin(), id.end(), [](unsigned char c) { return std::isxdigit(c); }) ||
                team < 1 || team > 255 || player < 1 || player > HL_MAX_NUM_PLAYERS) continue;
            const string key = id + " " + std::to_string(team) + " " + std::to_string(player);
            {
                std::lock_guard<std::mutex> lock(resetMutex);
                const auto now = std::chrono::steady_clock::now();
                for (auto it = resetPeers.begin(); it != resetPeers.end();) {
                    if (now - it->second.seen > std::chrono::seconds(30)) it = resetPeers.erase(it);
                    else ++it;
                }
                if (!resetPeers.count(key) && resetPeers.size() >= 64) continue;
                resetPeers[key] = {remote_addr, now};
            }
            std_msgs::msg::String request;
            request.data = key;
            resetPublisher->publish(request);
            continue;
        }
        if (ret != sizeof(SimGameControlData) && ret != sizeof(data)) continue;
        std::memcpy(&data, buffer, ret);

        if (ret == sizeof(SimGameControlData))
        {
            SimGameControlData sim;
            std::memcpy(&sim, &data, sizeof(sim));
            if (std::memcmp(sim.header, GAMECONTROLLER_STRUCT_HEADER, 4) != 0 || sim.version != 19)
            {
                RCLCPP_INFO(get_logger(), "packet from %s invalid simulator header or version=%u", remote_ip.c_str(), sim.version);
                continue;
            }
            convertSimPacket(sim, data);
        }
        else if (ret != sizeof(data))
        {
            RCLCPP_INFO(get_logger(), "packet from %s invalid length=%ld, expected=%ld or %ld", remote_ip.c_str(), ret, sizeof(data), sizeof(SimGameControlData));
            continue;
        }

        if (data.version != HL_GAMECONTROLLER_STRUCT_VERSION)
        {
            RCLCPP_INFO(get_logger(), "packet from %s invalid version: %d", remote_ip.c_str(), data.version);
            continue;
        }

        if (!check_ip_white_list(remote_ip))
        {
            RCLCPP_INFO(get_logger(), "received packet from %s, but not in ip white list, ignore it", remote_ip.c_str());
            continue;
        }

        handle_packet(data, msg);

        _publisher->publish(msg);

        RCLCPP_INFO(get_logger(), "handle packet successfully ip=%s, packet_number=%d", remote_ip.c_str(), data.packetNumber);
    }
}


bool GameControllerNode::check_ip_white_list(string ip)
{
    if (!_enable_ip_white_list)
    {
        return true;
    }
    for (size_t i = 0; i < _ip_white_list.size(); i++)
    {
        if (ip == _ip_white_list[i])
        {
            return true;
        }
    }
    return false;
}

void GameControllerNode::handle_packet(HlRoboCupGameControlData &data, game_controller_interface::msg::GameControlData &msg)
{

    // header is fixed length 4
    for (int i = 0; i < 4; i++)
    {
        msg.header[i] = data.header[i];
    }
    msg.version = data.version;
    msg.packet_number = data.packetNumber;
    msg.players_per_team = data.playersPerTeam;
    msg.game_type = data.gameType;
    msg.state = data.state;
    msg.first_half = data.firstHalf;
    msg.kick_off_team = data.kickOffTeam;
    msg.secondary_state = data.secondaryState;
    // secondary_state_info is fixed length 4
    for (int i = 0; i < 4; i++)
    {
        msg.secondary_state_info[i] = data.secondaryStateInfo[i];
    }
    msg.drop_in_team = data.dropInTeam;
    msg.drop_in_time = data.dropInTime;
    msg.secs_remaining = data.secsRemaining;
    msg.secondary_time = data.secondaryTime;

    // teams is fixed length 2
    for (int i = 0; i < 2; i++)
    {
        msg.teams[i].team_number = data.teams[i].teamNumber;
        msg.teams[i].field_player_colour = data.teams[i].fieldPlayerColour;
        msg.teams[i].score = data.teams[i].score;
        msg.teams[i].penalty_shot = data.teams[i].penaltyShot;
        msg.teams[i].single_shots = data.teams[i].singleShots;
        msg.teams[i].coach_sequence = data.teams[i].coachSequence;

        int coach_message_len = sizeof(data.teams[i].coachMessage) / sizeof(data.teams[i].coachMessage[0]);
        msg.teams[i].coach_message.clear(); // because msg is reused, remember to clear it
        for (int j = 0; j < coach_message_len; j++)
        {
            msg.teams[i].coach_message.push_back(data.teams[i].coachMessage[j]);
        }

        // msg.teams[i].cocah
        msg.teams[i].coach.penalty = data.teams[i].coach.penalty;
        msg.teams[i].coach.secs_till_unpenalised = data.teams[i].coach.secsTillUnpenalised;
        msg.teams[i].coach.number_of_warnings = data.teams[i].coach.numberOfWarnings;
        msg.teams[i].coach.yellow_card_count = data.teams[i].coach.yellowCardCount;
        msg.teams[i].coach.red_card_count = data.teams[i].coach.redCardCount;
        msg.teams[i].coach.goal_keeper = data.teams[i].coach.goalKeeper;

        // msg.teams[i].coach_message is defined as a variable-length array, note the difference from fixed-length arrays
        int players_len = sizeof(data.teams[i].players) / sizeof(data.teams[i].players[0]);
        msg.teams[i].players.clear(); // because msg is reused, remember to clear it
        for (int j = 0; j < players_len; j++)
        {
            game_controller_interface::msg::RobotInfo rf;
            rf.penalty = data.teams[i].players[j].penalty;
            rf.secs_till_unpenalised = data.teams[i].players[j].secsTillUnpenalised;
            rf.number_of_warnings = data.teams[i].players[j].numberOfWarnings;
            rf.yellow_card_count = data.teams[i].players[j].yellowCardCount;
            rf.red_card_count = data.teams[i].players[j].redCardCount;
            rf.goal_keeper = data.teams[i].players[j].goalKeeper;
            msg.teams[i].players.push_back(rf);
        }
    }
}