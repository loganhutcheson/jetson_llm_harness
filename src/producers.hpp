#pragma once
#include "latest.hpp"
#include "messages.hpp"
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
    ImuProducer(RingBuffer<ImuSample> &out, int hz = 200)
        : out_(out), period_(std::chrono::microseconds(1'000'000 / hz)) {}

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

  private:
    void run() {
        while (running_.load(std::memory_order_acquire)) {
            ImuSample s;
            s.seq = seq_++;
            s.t_capture_ns = now_ns();
            // dummy values; later you’ll read real IMU
            s.az = 9.81f;
            out_.push(std::move(s));
            produced_.fetch_add(1, std::memory_order_relaxed);
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
            std::cout << "[imu] hz=" << hz << " total=" << count << " dropped=" << dropped << "\n";
            last_t = now;
            last_count = count;
        }
    }

    RingBuffer<ImuSample> &out_;
    std::chrono::microseconds period_;
    std::atomic<bool> running_{false};
    std::thread th_;
    uint64_t seq_{0};
    std::atomic<uint64_t> produced_{0};
    std::thread mth_;
};
