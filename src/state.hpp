#pragma once
#include "messages.hpp"

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

enum class Mode {
    Idle,
    Monitoring,
    Alert,
};

struct SystemState {
    Mode mode{Mode::Idle};

    uint64_t tick_count{0};

    bool have_camera{false};
    bool have_imu{false};

    uint64_t last_cam_seq{0};
    uint64_t last_imu_seq{0};

    double last_cam_age_ms{-1.0};
    double last_imu_age_ms{-1.0};

    double last_accel_mag{0.0};
    double last_motion_delta{0.0};
    bool last_motion_alert{false};
};

inline const char *to_string(Mode m) {
    switch (m) {
    case Mode::Idle:
        return "Idle";
    case Mode::Monitoring:
        return "Monitoring";
    case Mode::Alert:
        return "Alert";
    default:
        return "Unknown";
    }
}

inline bool detect_motion_alert(const std::vector<ImuSample> &samples, double *out_mag = nullptr,
                                double *out_max_delta = nullptr) {
    if (samples.empty()) {
        if (out_mag) {
            *out_mag = 0.0;
        }
        if (out_max_delta) {
            *out_max_delta = 0.0;
        }
        return false;
    }

    double max_delta = 0.0;
    double prev_mag = 0.0;
    for (size_t i = 0; i < samples.size(); ++i) {
        const auto &sample = samples[i];
        const double mag = std::sqrt(static_cast<double>(sample.ax) * sample.ax +
                                     static_cast<double>(sample.ay) * sample.ay +
                                     static_cast<double>(sample.az) * sample.az);
        if (i > 0) {
            max_delta = std::max(max_delta, std::fabs(mag - prev_mag));
        }
        prev_mag = mag;
    }

    const double mag = prev_mag;

    if (out_mag) {
        *out_mag = mag;
    }
    if (out_max_delta) {
        *out_max_delta = max_delta;
    }

    // Trigger on either a large deviation from gravity or a sharp in-batch acceleration change.
    return std::fabs(mag - 9.81) > 1.5 || max_delta > 0.75;
}

inline std::vector<OutputAction> handle_event(SystemState &st, const InputEvent &ev) {
    std::vector<OutputAction> actions;

    std::visit(
        [&](const auto &e) {
            using T = std::decay_t<decltype(e)>;

            if constexpr (std::is_same_v<T, PlannerTick>) {
                st.tick_count++;

                if (!st.have_imu && !st.have_camera) {
                    st.mode = Mode::Idle;
                    actions.push_back(DisplayText{
                        "WAITING",
                        "No sensors yet",
                    });
                    actions.push_back(LogLine{
                        "planner tick: waiting for first sensor data",
                    });
                    return;
                }

                if (st.last_motion_alert) {
                    st.mode = Mode::Alert;
                    actions.push_back(DisplayText{
                        "ALERT",
                        "Motion spike",
                    });
                    actions.push_back(LogLine{
                        "planner tick: system remains in ALERT",
                    });
                    return;
                }

                st.mode = Mode::Monitoring;
                actions.push_back(DisplayText{
                    "MONITORING",
                    "cam=" + std::to_string(st.last_cam_seq) +
                        " imu=" + std::to_string(st.last_imu_seq),
                });
                actions.push_back(LogLine{
                    "planner tick: monitoring, accel_mag=" + std::to_string(st.last_accel_mag),
                });
            } else if constexpr (std::is_same_v<T, CameraObserved>) {
                st.have_camera = true;
                st.last_cam_seq = e.frame.seq;
            } else if constexpr (std::is_same_v<T, ImuBatchReady>) {
                st.have_imu = !e.samples.empty();
                if (!e.samples.empty()) {
                    st.last_imu_seq = e.samples.back().seq;
                }

                double mag = 0.0;
                double max_delta = 0.0;
                const bool alert = detect_motion_alert(e.samples, &mag, &max_delta);
                st.last_accel_mag = mag;
                st.last_motion_delta = max_delta;
                st.last_motion_alert = alert;

                if (alert) {
                    st.mode = Mode::Alert;
                    actions.push_back(LogLine{
                        "imu alert: accel_mag=" + std::to_string(mag) +
                            " max_delta=" + std::to_string(max_delta),
                    });
                    actions.push_back(DisplayText{
                        "IMU ALERT",
                        "d=" + std::to_string(max_delta),
                    });
                    actions.push_back(PlayTone{
                        1200,
                        max_delta > 1.5 ? 180 : 90,
                    });
                    actions.push_back(LlmPrompt{
                        "The IMU detected a sudden motion event. "
                        "Produce a short robotic warning phrase.",
                    });
                }
            }
        },
        ev);

    return actions;
}
