#pragma once
#include "llm.hpp"
#include "messages.hpp"
#include "oled_display.hpp"
#include "time.hpp"

#include <cstdlib>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>

class OledLcdConsumer {
  public:
    OledLcdConsumer() {
        if (const char *value = std::getenv("JETSON_OLED_ENABLE")) {
            const std::string v(value);
            enabled_ = v == "1" || v == "true" || v == "TRUE" || v == "yes" || v == "on";
        }

        if (!enabled_) {
            return;
        }

        OledConfig cfg;
        if (const char *value = std::getenv("JETSON_OLED_I2C_DEV")) {
            cfg.i2c_device = value;
        }
        if (const char *value = std::getenv("JETSON_OLED_I2C_ADDR")) {
            cfg.i2c_address = static_cast<uint8_t>(std::stoul(value, nullptr, 0));
        }

        try {
            display_ = std::make_unique<OledDisplay>(cfg);
            display_->initialize();
            display_->clear();
        } catch (const std::exception &ex) {
            enabled_ = false;
            display_.reset();
            std::cerr << "[OLED] init failed: " << ex.what() << "\n";
        }
    }

    void consume(const DisplayText &msg) {
        std::cout << "[LCD]\n";
        std::cout << "  " << msg.line1 << "\n";
        std::cout << "  " << msg.line2 << "\n";

        if (!display_) {
            return;
        }

        try {
            display_->clear();
            display_->write_text(msg.line1 + " " + msg.line2);
        } catch (const std::exception &ex) {
            std::cerr << "[OLED] write failed: " << ex.what() << "\n";
        }
    }

    bool enabled() const { return enabled_ && display_ != nullptr; }

  private:
    bool enabled_{false};
    std::unique_ptr<OledDisplay> display_;
};

class ConsoleSpeakerConsumer {
  public:
    void consume(const PlayTone &msg) {
        std::cout << "[SPEAKER] tone freq=" << msg.frequency_hz << "Hz dur=" << msg.duration_ms
                  << "ms\n";
    }
};

class GpioBuzzerConsumer {
  public:
    GpioBuzzerConsumer() {
        if (const char *value = std::getenv("JETSON_BUZZER_ENABLE")) {
            const std::string v(value);
            enabled_ = v == "1" || v == "true" || v == "TRUE" || v == "yes" || v == "on";
        }

        if (const char *value = std::getenv("JETSON_BUZZER_PIN")) {
            pin_ = std::stoi(value);
        }

        if (const char *value = std::getenv("JETSON_BUZZER_ACTIVE_LOW")) {
            const std::string v(value);
            active_low_ = v == "1" || v == "true" || v == "TRUE" || v == "yes" || v == "on";
        }
    }

    void consume(const PlayTone &msg) {
        if (!enabled_) {
            return;
        }

        const char *initial_level = active_low_ ? "GPIO.HIGH" : "GPIO.LOW";
        const char *on_level = active_low_ ? "GPIO.LOW" : "GPIO.HIGH";
        const char *off_level = active_low_ ? "GPIO.HIGH" : "GPIO.LOW";

        std::ostringstream cmd;
        cmd << "python3 -c '"
            << "import Jetson.GPIO as GPIO, time; "
            << "GPIO.setwarnings(False); "
            << "GPIO.setmode(GPIO.BOARD); "
            << "GPIO.setup(" << pin_ << ", GPIO.OUT, initial=" << initial_level << "); "
            << "GPIO.output(" << pin_ << ", " << on_level << "); "
            << "time.sleep(" << (static_cast<double>(msg.duration_ms) / 1000.0) << "); "
            << "GPIO.output(" << pin_ << ", " << off_level << "); "
            << "GPIO.cleanup(" << pin_ << ")'";
        const int rc = std::system(cmd.str().c_str());
        if (rc != 0) {
            std::cerr << "[BUZZER] command failed with rc=" << rc << "\n";
        }
    }

    bool enabled() const { return enabled_; }
    int pin() const { return pin_; }

  private:
    bool enabled_{false};
    int pin_{12};
    bool active_low_{true};
};

class ConsoleLogConsumer {
  public:
    void consume(const LogLine &msg) { std::cout << "[LOG] " << msg.text << "\n"; }
};

class LlmActionConsumer {
  public:
    explicit LlmActionConsumer(ILlmClient &llm) : llm_(llm) {}

    LlmResponse consume(const LlmPrompt &msg) {
        LlmRequest req;
        req.seq = seq_++;
        req.t_request_ns = now_ns();
        req.prompt = msg.prompt;
        return llm_.infer(req);
    }

  private:
    ILlmClient &llm_;
    uint64_t seq_{0};
};
