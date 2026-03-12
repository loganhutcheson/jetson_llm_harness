#pragma once
#include <cstdint>
#include <string>
#include <variant>
#include <vector>

inline uint64_t now_ns();

struct CameraFrame {
    uint64_t seq = 0;
    uint64_t t_capture_ns = 0;
    int width = 640;
    int height = 480;
    // dummy payload (optional)
    std::vector<uint8_t> bytes;
};

struct ImuSample {
    uint64_t seq = 0;
    uint64_t t_capture_ns = 0;
    float ax = 0, ay = 0, az = 9.81f;
    float gx = 0, gy = 0, gz = 0;
};

struct LlmRequest {
    uint64_t seq = 0;
    uint64_t t_request_ns = 0;
    std::string prompt;
};

struct LlmResponse {
    uint64_t seq = 0;
    uint64_t t_response_ns = 0;
    std::string text;
    // later: tokens/sec, latency, etc.
};

// ---------- Input events ----------

struct PlannerTick {
    uint64_t t_ns = 0;
};

struct CameraObserved {
    CameraFrame frame;
};

struct ImuBatchReady {
    uint64_t t_ns = 0;
    std::vector<ImuSample> samples;
};

using InputEvent = std::variant<PlannerTick, CameraObserved, ImuBatchReady>;

// ---------- Output actions ----------

struct DisplayText {
    std::string line1;
    std::string line2;
};

struct PlayTone {
    int frequency_hz = 0;
    int duration_ms = 0;
};

struct LlmPrompt {
    std::string prompt;
};

struct LogLine {
    std::string text;
};

using OutputAction = std::variant<DisplayText, PlayTone, LlmPrompt, LogLine>;
