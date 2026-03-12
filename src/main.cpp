#include "consumers.hpp"
#include "latest.hpp"
#include "llm.hpp"
#include "messages.hpp"
#include "producers.hpp"
#include "ringbuffer.hpp"
#include "state.hpp"
#include "time.hpp"

#include <chrono>
#include <fstream>
#include <iostream>
#include <thread>
#include <vector>

static void dispatch_action(const OutputAction &action, ConsoleLcdConsumer &lcd,
                            ConsoleSpeakerConsumer &speaker, ConsoleLogConsumer &logger,
                            LlmActionConsumer &llm_consumer) {
    std::visit(
        [&](const auto &a) {
            using T = std::decay_t<decltype(a)>;

            if constexpr (std::is_same_v<T, DisplayText>) {
                lcd.consume(a);
            } else if constexpr (std::is_same_v<T, PlayTone>) {
                speaker.consume(a);
            } else if constexpr (std::is_same_v<T, LogLine>) {
                logger.consume(a);
            } else if constexpr (std::is_same_v<T, LlmPrompt>) {
                const auto resp = llm_consumer.consume(a);
                logger.consume(LogLine{
                    "llm response: " + resp.text,
                });
                lcd.consume(DisplayText{
                    "LLM",
                    resp.text.substr(0, 28),
                });
            }
        },
        action);
}

int main() {
    Latest<CameraFrame> cam_latest;
    RingBuffer<ImuSample> imu_buf;

    CameraProducer cam(cam_latest, 30);
    ImuProducer imu(imu_buf, 200);

    StubLlmClient llm;
    LlmActionConsumer llm_consumer(llm);

    ConsoleLcdConsumer lcd;
    ConsoleSpeakerConsumer speaker;
    ConsoleLogConsumer logger;

    SystemState state;

    std::cout << "[main] " << imu.startup_status() << "\n";

    cam.start();
    imu.start();

    std::ofstream csv("results_mac.csv");
    csv << "t_ns,tick,mode,cam_seq,imu_seq,imu_cnt,accel_mag,motion_alert\n";

    for (int i = 0; i < 30; i++) {
        const uint64_t t0 = now_ns();

        // Pull latest camera snapshot into state as an event
        if (auto cam_opt = cam_latest.peek()) {
            auto cam_actions = handle_event(state, CameraObserved{*cam_opt});
            for (const auto &action : cam_actions) {
                dispatch_action(action, lcd, speaker, logger, llm_consumer);
            }
        }

        // Drain IMU queue and feed as batch
        std::vector<ImuSample> imu_samples;
        const size_t imu_cnt = imu_buf.popall(imu_samples);

        if (imu_cnt > 0) {
            auto imu_actions = handle_event(state, ImuBatchReady{t0, std::move(imu_samples)});
            for (const auto &action : imu_actions) {
                dispatch_action(action, lcd, speaker, logger, llm_consumer);
            }
        }

        // Planner tick drives high-level status updates
        auto tick_actions = handle_event(state, PlannerTick{t0});
        for (const auto &action : tick_actions) {
            dispatch_action(action, lcd, speaker, logger, llm_consumer);
        }

        csv << t0 << "," << state.tick_count << "," << to_string(state.mode) << ","
            << state.last_cam_seq << "," << state.last_imu_seq << "," << imu_cnt << ","
            << state.last_accel_mag << "," << (state.last_motion_alert ? 1 : 0) << "\n";

        std::cout << "[MAIN] tick=" << i << " mode=" << to_string(state.mode)
                  << " cam_seq=" << state.last_cam_seq << " imu_seq=" << state.last_imu_seq
                  << " imu_cnt=" << imu_cnt << " accel_mag=" << state.last_accel_mag
                  << " alert=" << state.last_motion_alert << "\n";

        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    cam.stop();
    imu.stop();

    std::cout << "wrote results_mac.csv\n";
    return 0;
}
