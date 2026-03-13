#include "oled_display.hpp"

#include <cstdlib>
#include <iostream>
#include <optional>
#include <string>

static std::optional<std::string> read_env(const char *name) {
    if (const char *value = std::getenv(name)) {
        return std::string(value);
    }
    return std::nullopt;
}

static uint8_t parse_address(const std::optional<std::string> &value, uint8_t default_value) {
    if (!value || value->empty()) {
        return default_value;
    }
    const unsigned long parsed = std::stoul(*value, nullptr, 0);
    if (parsed > 0x7f) {
        throw std::runtime_error("OLED I2C address must be a 7-bit value");
    }
    return static_cast<uint8_t>(parsed);
}

int main() {
    try {
        OledConfig cfg;
        if (auto dev = read_env("JETSON_OLED_I2C_DEV")) {
            cfg.i2c_device = *dev;
        }
        cfg.i2c_address = parse_address(read_env("JETSON_OLED_I2C_ADDR"), cfg.i2c_address);

        OledDisplay display(cfg);
        display.initialize();
        display.clear();
        display.write_text("HAPPY ST PATTYS LOGAN");

        std::cout << "[oled_demo] wrote message to " << cfg.i2c_device << " addr=0x"
                  << std::hex << static_cast<int>(cfg.i2c_address) << std::dec << "\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "[oled_demo] error: " << e.what() << "\n";
        return 1;
    }
}
