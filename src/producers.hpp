#pragma once
#include "latest.hpp"
#include "messages.hpp"
#include "mpu6050.hpp"
#include "ringbuffer.hpp"
#include "time.hpp"

#include <atomic>
#include <chrono>
#include <iostream>
#include <thread>

class CameraProducer {
  public:
    CameraProducer(Latest<CameraFrame> &out, int fps = 30)
        : out_(out), period_(std::chrono::microseconds(1'000'000 / fps)) {}

    void start() {
        running_.store(true, std::memory_order_release);
        th_ = std::thread([this] { run(); });
    }
    void stop() {
        running_.store(false, std::memory_order_release);
        if (th_.joinable())
            th_.join();
    }

  private:
    void run() {
        while (running_.load(std::memory_order_acquire)) {
            CameraFrame f;
            f.seq = seq_++;
            f.t_capture_ns = now_ns();
            // optional dummy payload
            f.bytes.resize(640 * 480, 0);
            out_.publish(std::move(f));
            std::this_thread::sleep_for(period_);
        }
    }

    Latest<CameraFrame> &out_;
    std::chrono::microseconds period_;
    std::atomic<bool> running_{false};
    std::thread th_;
    uint64_t seq_{0};
};

class ImuProducer {
  public:
    ImuProducer(RingBuffer<ImuSample> &out, int hz = 200,
                ImuRuntimeConfig cfg = load_imu_runtime_config())
        : out_(out), period_(std::chrono::microseconds(1'000'000 / hz)), config_(std::move(cfg)) {
        reader_ = make_imu_reader(config_, &startup_status_);
    }

    void start() {
        produced_.store(0, std::memory_order_relaxed);
        running_.store(true, std::memory_order_release);
        th_ = std::thread([this] { run(); });
        mth_ = std::thread([this] { measure(); });
    }
    void stop() {
        running_.store(false, std::memory_order_release);
        if (th_.joinable())
            th_.join();
        if (mth_.joinable())
            mth_.join();
    }

    const std::string &startup_status() const { return startup_status_; }

  private:
    void run() {
        while (running_.load(std::memory_order_acquire)) {
            try {
                ImuSample sample = reader_->read(seq_++);
                last_sample_seq_.store(sample.seq, std::memory_order_relaxed);
                last_ax_.store(sample.ax, std::memory_order_relaxed);
                last_ay_.store(sample.ay, std::memory_order_relaxed);
                last_az_.store(sample.az, std::memory_order_relaxed);
                last_gx_.store(sample.gx, std::memory_order_relaxed);
                last_gy_.store(sample.gy, std::memory_order_relaxed);
                last_gz_.store(sample.gz, std::memory_order_relaxed);
                out_.push(std::move(sample));
                produced_.fetch_add(1, std::memory_order_relaxed);
            } catch (const std::exception &ex) {
                std::cout << "[imu] read failure: " << ex.what() << "\n";
                running_.store(false, std::memory_order_release);
                break;
            }
            std::this_thread::sleep_for(period_);
        }
    }

    void measure() {
        uint64_t last_t = now_ns();
        uint64_t last_count = produced_.load(std::memory_order_relaxed);

        while (running_.load(std::memory_order_acquire)) {
            std::this_thread::sleep_for(std::chrono::seconds(1));
            const uint64_t now = now_ns();
            const uint64_t count = produced_.load(std::memory_order_relaxed);
            const double dt_s = (now - last_t) / 1e9;
            const double hz = dt_s > 0.0 ? (double)(count - last_count) / dt_s : 0.0;
            const uint64_t dropped = out_.dropped();
            std::cout << "[imu] hz=" << hz << " total=" << count << " dropped=" << dropped
                      << " sample.seq=" << last_sample_seq_.load(std::memory_order_relaxed)
                      << " accel=(" << last_ax_.load(std::memory_order_relaxed) << ","
                      << last_ay_.load(std::memory_order_relaxed) << ","
                      << last_az_.load(std::memory_order_relaxed) << ")"
                      << " gyro=(" << last_gx_.load(std::memory_order_relaxed) << ","
                      << last_gy_.load(std::memory_order_relaxed) << ","
                      << last_gz_.load(std::memory_order_relaxed) << ")\n";
            last_t = now;
            last_count = count;
        }
    }

    RingBuffer<ImuSample> &out_;
    std::chrono::microseconds period_;
    ImuRuntimeConfig config_;
    std::unique_ptr<IImuReader> reader_;
    std::string startup_status_;
    std::atomic<bool> running_{false};
    std::thread th_;
    uint64_t seq_{0};
    std::atomic<uint64_t> produced_{0};
    std::atomic<uint64_t> last_sample_seq_{0};
    std::atomic<float> last_ax_{0.0f};
    std::atomic<float> last_ay_{0.0f};
    std::atomic<float> last_az_{0.0f};
    std::atomic<float> last_gx_{0.0f};
    std::atomic<float> last_gy_{0.0f};
    std::atomic<float> last_gz_{0.0f};
    std::thread mth_;
};
