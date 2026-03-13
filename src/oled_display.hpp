#pragma once

#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#ifdef __linux__
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <unistd.h>
#endif

struct OledConfig {
    std::string i2c_device = "/dev/i2c-7";
    uint8_t i2c_address = 0x3c;
    int width = 128;
    int height = 64;
    int column_offset = 0;
};

class OledDisplay {
  public:
    explicit OledDisplay(OledConfig cfg) : cfg_(std::move(cfg)) {
#ifdef __linux__
        fd_ = ::open(cfg_.i2c_device.c_str(), O_RDWR);
        if (fd_ < 0) {
            throw std::runtime_error("failed to open " + cfg_.i2c_device + ": " +
                                     std::strerror(errno));
        }

        if (::ioctl(fd_, I2C_SLAVE, cfg_.i2c_address) < 0) {
            const std::string err = std::strerror(errno);
            ::close(fd_);
            fd_ = -1;
            throw std::runtime_error("failed to select OLED address 0x" +
                                     hex_byte(cfg_.i2c_address) + ": " + err);
        }
#else
        throw std::runtime_error("OLED display is only supported on Linux");
#endif
    }

    ~OledDisplay() {
#ifdef __linux__
        if (fd_ >= 0) {
            ::close(fd_);
        }
#endif
    }

    void initialize() {
        command({
            0xAE, 0xD5, 0x80, 0xA8, static_cast<uint8_t>(cfg_.height - 1), 0xD3, 0x00, 0x40,
            0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA,
            static_cast<uint8_t>(cfg_.height == 64 ? 0x12 : 0x02), 0x81, 0xCF, 0xD9, 0xF1,
            0xDB, 0x40, 0xA4, 0xA6, 0x2E, 0xAF,
        });
    }

    void clear() { show(std::vector<uint8_t>(cfg_.width * page_count(), 0x00)); }

    void write_text(const std::string &text) {
        auto framebuffer = render_text(text);
        show(framebuffer);
    }

  private:
    static constexpr int kGlyphWidth = 5;
    static constexpr int kGlyphSpacing = 1;
    static constexpr int kGlyphHeight = 7;
    static constexpr int kTextWrapColumns = 16;

    static std::string hex_byte(uint8_t value) {
        constexpr char digits[] = "0123456789abcdef";
        std::string out(2, '0');
        out[0] = digits[(value >> 4) & 0x0f];
        out[1] = digits[value & 0x0f];
        return out;
    }

    int page_count() const { return cfg_.height / 8; }

    void command(std::initializer_list<uint8_t> values) {
        std::vector<uint8_t> payload;
        payload.reserve(values.size() + 1);
        payload.push_back(0x00);
        payload.insert(payload.end(), values.begin(), values.end());
        write_all(payload);
    }

    void data(const uint8_t *bytes, size_t count) {
        std::vector<uint8_t> payload;
        payload.reserve(count + 1);
        payload.push_back(0x40);
        payload.insert(payload.end(), bytes, bytes + count);
        write_all(payload);
    }

    void show(const std::vector<uint8_t> &framebuffer) {
        const int pages = page_count();
        if (static_cast<int>(framebuffer.size()) != cfg_.width * pages) {
            throw std::runtime_error("invalid OLED framebuffer size");
        }

        for (int page = 0; page < pages; ++page) {
            const int start = cfg_.column_offset;
            const int end = cfg_.column_offset + cfg_.width - 1;
            command({
                static_cast<uint8_t>(0xB0 + page),
                static_cast<uint8_t>(start & 0x0F),
                static_cast<uint8_t>(0x10 | (start >> 4)),
                0x21,
                static_cast<uint8_t>(start),
                static_cast<uint8_t>(end),
            });

            const uint8_t *row = framebuffer.data() + (page * cfg_.width);
            for (int i = 0; i < cfg_.width; i += 16) {
                data(row + i, static_cast<size_t>(std::min(16, cfg_.width - i)));
            }
        }
    }

    std::vector<uint8_t> render_text(const std::string &text) const {
        const int pages = page_count();
        std::vector<uint8_t> framebuffer(static_cast<size_t>(cfg_.width * pages), 0x00);

        const auto lines = wrap_text(text);
        const int total_height = static_cast<int>(lines.size()) * (kGlyphHeight + 3);
        int y = std::max(0, (cfg_.height - total_height) / 2);

        for (const std::string &line : lines) {
            const int line_width = static_cast<int>(line.size()) * (kGlyphWidth + kGlyphSpacing) -
                                   (line.empty() ? 0 : kGlyphSpacing);
            int x = std::max(0, (cfg_.width - line_width) / 2);

            for (char c : line) {
                draw_char(framebuffer, x, y, normalize_char(c));
                x += kGlyphWidth + kGlyphSpacing;
            }
            y += kGlyphHeight + 3;
        }

        return framebuffer;
    }

    std::vector<std::string> wrap_text(const std::string &text) const {
        std::vector<std::string> lines;
        std::string current;

        auto flush = [&]() {
            if (!current.empty()) {
                lines.push_back(current);
                current.clear();
            }
        };

        size_t i = 0;
        while (i < text.size()) {
            while (i < text.size() && text[i] == ' ') {
                ++i;
            }

            size_t j = i;
            while (j < text.size() && text[j] != ' ') {
                ++j;
            }

            const std::string word = text.substr(i, j - i);
            if (word.empty()) {
                break;
            }

            const size_t next_size = current.empty() ? word.size() : current.size() + 1 + word.size();
            if (next_size > kTextWrapColumns && !current.empty()) {
                flush();
            }

            if (!current.empty()) {
                current.push_back(' ');
            }
            current += word;
            i = j;
        }

        flush();
        if (lines.empty()) {
            lines.push_back("");
        }
        return lines;
    }

    static char normalize_char(char c) {
        if (c >= 'a' && c <= 'z') {
            return static_cast<char>(c - 'a' + 'A');
        }
        return c;
    }

    void draw_char(std::vector<uint8_t> &framebuffer, int x, int y, char c) const {
        static const std::unordered_map<char, std::array<uint8_t, kGlyphWidth>> kFont = {
            {' ', {0x00, 0x00, 0x00, 0x00, 0x00}},
            {'!', {0x00, 0x00, 0x5F, 0x00, 0x00}},
            {'-', {0x08, 0x08, 0x08, 0x08, 0x08}},
            {'0', {0x3E, 0x51, 0x49, 0x45, 0x3E}},
            {'1', {0x00, 0x42, 0x7F, 0x40, 0x00}},
            {'2', {0x42, 0x61, 0x51, 0x49, 0x46}},
            {'3', {0x21, 0x41, 0x45, 0x4B, 0x31}},
            {'4', {0x18, 0x14, 0x12, 0x7F, 0x10}},
            {'5', {0x27, 0x45, 0x45, 0x45, 0x39}},
            {'6', {0x3C, 0x4A, 0x49, 0x49, 0x30}},
            {'7', {0x01, 0x71, 0x09, 0x05, 0x03}},
            {'8', {0x36, 0x49, 0x49, 0x49, 0x36}},
            {'9', {0x06, 0x49, 0x49, 0x29, 0x1E}},
            {'A', {0x7E, 0x11, 0x11, 0x11, 0x7E}},
            {'B', {0x7F, 0x49, 0x49, 0x49, 0x36}},
            {'C', {0x3E, 0x41, 0x41, 0x41, 0x22}},
            {'D', {0x7F, 0x41, 0x41, 0x22, 0x1C}},
            {'E', {0x7F, 0x49, 0x49, 0x49, 0x41}},
            {'F', {0x7F, 0x09, 0x09, 0x09, 0x01}},
            {'G', {0x3E, 0x41, 0x49, 0x49, 0x7A}},
            {'H', {0x7F, 0x08, 0x08, 0x08, 0x7F}},
            {'I', {0x00, 0x41, 0x7F, 0x41, 0x00}},
            {'J', {0x20, 0x40, 0x41, 0x3F, 0x01}},
            {'K', {0x7F, 0x08, 0x14, 0x22, 0x41}},
            {'L', {0x7F, 0x40, 0x40, 0x40, 0x40}},
            {'M', {0x7F, 0x02, 0x0C, 0x02, 0x7F}},
            {'N', {0x7F, 0x04, 0x08, 0x10, 0x7F}},
            {'O', {0x3E, 0x41, 0x41, 0x41, 0x3E}},
            {'P', {0x7F, 0x09, 0x09, 0x09, 0x06}},
            {'Q', {0x3E, 0x41, 0x51, 0x21, 0x5E}},
            {'R', {0x7F, 0x09, 0x19, 0x29, 0x46}},
            {'S', {0x46, 0x49, 0x49, 0x49, 0x31}},
            {'T', {0x01, 0x01, 0x7F, 0x01, 0x01}},
            {'U', {0x3F, 0x40, 0x40, 0x40, 0x3F}},
            {'V', {0x1F, 0x20, 0x40, 0x20, 0x1F}},
            {'W', {0x7F, 0x20, 0x18, 0x20, 0x7F}},
            {'X', {0x63, 0x14, 0x08, 0x14, 0x63}},
            {'Y', {0x07, 0x08, 0x70, 0x08, 0x07}},
            {'Z', {0x61, 0x51, 0x49, 0x45, 0x43}},
        };

        const auto it = kFont.find(c);
        const auto &glyph = it == kFont.end() ? kFont.at(' ') : it->second;

        for (int col = 0; col < kGlyphWidth; ++col) {
            for (int row = 0; row < kGlyphHeight; ++row) {
                if (((glyph[col] >> row) & 0x1) == 0) {
                    continue;
                }
                set_pixel(framebuffer, x + col, y + row);
            }
        }
    }

    void set_pixel(std::vector<uint8_t> &framebuffer, int x, int y) const {
        if (x < 0 || x >= cfg_.width || y < 0 || y >= cfg_.height) {
            return;
        }
        const int page = y / 8;
        const int bit = y % 8;
        framebuffer[static_cast<size_t>(page * cfg_.width + x)] |= static_cast<uint8_t>(1u << bit);
    }

    void write_all(const std::vector<uint8_t> &payload) {
#ifdef __linux__
        size_t offset = 0;
        while (offset < payload.size()) {
            const ssize_t written =
                ::write(fd_, payload.data() + offset, payload.size() - offset);
            if (written < 0) {
                throw std::runtime_error("OLED I2C write failed: " + std::string(std::strerror(errno)));
            }
            offset += static_cast<size_t>(written);
        }
#endif
    }

    OledConfig cfg_;
#ifdef __linux__
    int fd_{-1};
#endif
};
