#pragma once

#include "messages.hpp"
#include "time.hpp"

#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>

#ifdef __linux__
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <unistd.h>
#endif

struct ImuRuntimeConfig {
    std::string source = "stub";
    std::string i2c_device = "/dev/i2c-7";
    uint8_t i2c_address = 0x68;
    bool enable = false;
};

inline std::optional<std::string> read_env(const char *name) {
    if (const char *value = std::getenv(name)) {
        return std::string(value);
    }
    return std::nullopt;
}

inline bool parse_bool_env(const std::optional<std::string> &value, bool default_value) {
    if (!value) {
        return default_value;
    }

    const std::string &v = *value;
    return v == "1" || v == "true" || v == "TRUE" || v == "yes" || v == "on";
}

inline uint8_t parse_i2c_address(const std::optional<std::string> &value, uint8_t default_value) {
    if (!value || value->empty()) {
        return default_value;
    }

    const unsigned long parsed = std::stoul(*value, nullptr, 0);
    if (parsed > 0x7f) {
        throw std::runtime_error("JETSON_IMU_I2C_ADDR must be a 7-bit I2C address");
    }
    return static_cast<uint8_t>(parsed);
}

inline ImuRuntimeConfig load_imu_runtime_config() {
    ImuRuntimeConfig cfg;
    if (auto source = read_env("JETSON_IMU_SOURCE")) {
        cfg.source = *source;
    }
    if (auto device = read_env("JETSON_IMU_I2C_DEV")) {
        cfg.i2c_device = *device;
    }
    cfg.i2c_address = parse_i2c_address(read_env("JETSON_IMU_I2C_ADDR"), cfg.i2c_address);

    if (cfg.source == "mpu6050") {
        cfg.enable = true;
    } else if (cfg.source == "stub") {
        cfg.enable = false;
    } else {
        throw std::runtime_error("JETSON_IMU_SOURCE must be either 'stub' or 'mpu6050'");
    }

    cfg.enable = parse_bool_env(read_env("JETSON_IMU_ENABLE"), cfg.enable);
    return cfg;
}

class IImuReader {
  public:
    virtual ~IImuReader() = default;
    virtual ImuSample read(uint64_t seq) = 0;
    virtual std::string describe() const = 0;
};

class StubImuReader final : public IImuReader {
  public:
    ImuSample read(uint64_t seq) override {
        ImuSample s;
        s.seq = seq;
        s.t_capture_ns = now_ns();
        s.az = 9.81f;
        return s;
    }

    std::string describe() const override { return "stub"; }
};

#ifdef __linux__
class Mpu6050Reader final : public IImuReader {
  public:
    explicit Mpu6050Reader(const ImuRuntimeConfig &cfg)
        : device_path_(cfg.i2c_device), address_(cfg.i2c_address) {
        fd_ = ::open(device_path_.c_str(), O_RDWR);
        if (fd_ < 0) {
            throw std::runtime_error("failed to open " + device_path_ + ": " +
                                     std::strerror(errno));
        }

        if (ioctl(fd_, I2C_SLAVE, address_) < 0) {
            const std::string err = std::strerror(errno);
            ::close(fd_);
            throw std::runtime_error("failed to select I2C address 0x" + hex_byte(address_) +
                                     ": " + err);
        }

        initialize();
    }

    ~Mpu6050Reader() override {
        if (fd_ >= 0) {
            ::close(fd_);
        }
    }

    ImuSample read(uint64_t seq) override {
        const auto raw = read_burst();

        ImuSample sample;
        sample.seq = seq;
        sample.t_capture_ns = now_ns();

        sample.ax = raw.accel_x / kAccelLsbPerG * kGravity;
        sample.ay = raw.accel_y / kAccelLsbPerG * kGravity;
        sample.az = raw.accel_z / kAccelLsbPerG * kGravity;

        sample.gx = raw.gyro_x / kGyroLsbPerDegPerSec;
        sample.gy = raw.gyro_y / kGyroLsbPerDegPerSec;
        sample.gz = raw.gyro_z / kGyroLsbPerDegPerSec;
        return sample;
    }

    std::string describe() const override {
        return "mpu6050(" + device_path_ + ", addr=0x" + hex_byte(address_) + ")";
    }

  private:
    struct RawSample {
        float accel_x;
        float accel_y;
        float accel_z;
        float gyro_x;
        float gyro_y;
        float gyro_z;
    };

    static constexpr float kAccelLsbPerG = 16384.0f;
    static constexpr float kGyroLsbPerDegPerSec = 131.0f;
    static constexpr float kGravity = 9.80665f;
    static constexpr uint8_t kRegisterPowerMgmt1 = 0x6B;
    static constexpr uint8_t kRegisterAccelConfig = 0x1C;
    static constexpr uint8_t kRegisterGyroConfig = 0x1B;
    static constexpr uint8_t kRegisterSampleRateDivider = 0x19;
    static constexpr uint8_t kRegisterConfig = 0x1A;
    static constexpr uint8_t kRegisterAccelStart = 0x3B;

    static std::string hex_byte(uint8_t value) {
        constexpr char digits[] = "0123456789abcdef";
        std::string out(2, '0');
        out[0] = digits[(value >> 4) & 0x0f];
        out[1] = digits[value & 0x0f];
        return out;
    }

    void initialize() {
        write_register(kRegisterPowerMgmt1, 0x00);
        write_register(kRegisterSampleRateDivider, 0x04);
        write_register(kRegisterConfig, 0x03);
        write_register(kRegisterGyroConfig, 0x00);
        write_register(kRegisterAccelConfig, 0x00);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    void write_register(uint8_t reg, uint8_t value) {
        const uint8_t payload[2] = {reg, value};
        const ssize_t written = ::write(fd_, payload, sizeof(payload));
        if (written != static_cast<ssize_t>(sizeof(payload))) {
            throw std::runtime_error("failed writing MPU-6050 register 0x" + hex_byte(reg) +
                                     ": " + std::strerror(errno));
        }
    }

    RawSample read_burst() {
        uint8_t start = kRegisterAccelStart;
        if (::write(fd_, &start, 1) != 1) {
            throw std::runtime_error("failed selecting MPU-6050 data register: " +
                                     std::string(std::strerror(errno)));
        }

        uint8_t data[14] = {};
        if (::read(fd_, data, sizeof(data)) != static_cast<ssize_t>(sizeof(data))) {
            throw std::runtime_error("failed reading MPU-6050 sample: " +
                                     std::string(std::strerror(errno)));
        }

        return RawSample{
            .accel_x = static_cast<float>(decode_i16(data[0], data[1])),
            .accel_y = static_cast<float>(decode_i16(data[2], data[3])),
            .accel_z = static_cast<float>(decode_i16(data[4], data[5])),
            .gyro_x = static_cast<float>(decode_i16(data[8], data[9])),
            .gyro_y = static_cast<float>(decode_i16(data[10], data[11])),
            .gyro_z = static_cast<float>(decode_i16(data[12], data[13])),
        };
    }

    static int16_t decode_i16(uint8_t hi, uint8_t lo) {
        return static_cast<int16_t>((static_cast<uint16_t>(hi) << 8) | static_cast<uint16_t>(lo));
    }

    std::string device_path_;
    uint8_t address_;
    int fd_{-1};
};
#endif

inline std::unique_ptr<IImuReader> make_imu_reader(const ImuRuntimeConfig &cfg,
                                                   std::string *status_message) {
    if (!cfg.enable) {
        if (status_message) {
            *status_message = "IMU source=stub";
        }
        return std::make_unique<StubImuReader>();
    }

#ifdef __linux__
    try {
        auto reader = std::make_unique<Mpu6050Reader>(cfg);
        if (status_message) {
            *status_message = "IMU source=" + reader->describe();
        }
        return reader;
    } catch (const std::exception &ex) {
        if (status_message) {
            *status_message = "MPU-6050 init failed (" + std::string(ex.what()) +
                              "); falling back to stub";
        }
        return std::make_unique<StubImuReader>();
    }
#else
    if (status_message) {
        *status_message = "MPU-6050 requested but this build target is not Linux; falling back to stub";
    }
    return std::make_unique<StubImuReader>();
#endif
}
