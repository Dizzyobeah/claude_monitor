#pragma once

#include <LovyanGFX.hpp>

// Integer sin/cos lookup table (256 entries, values -127 to 127)
// sin_lut[angle] where angle is 0-255 mapping to 0-360 degrees
extern const int8_t SIN_LUT[256];

// Helper: lookup sin for angle 0-255, returns -127 to 127
static inline int8_t isin(uint8_t angle) { return SIN_LUT[angle]; }
static inline int8_t icos(uint8_t angle) { return SIN_LUT[(uint8_t)(angle + 64)]; }

// Color palette indices (set up by DisplayManager)
namespace Colors {
    static constexpr uint16_t BG_DARK      = 0x1082;  // Very dark gray
    static constexpr uint16_t BG_PANEL     = 0x2104;  // Dark gray panel
    static constexpr uint16_t TEXT_PRIMARY  = 0xFFFF;  // White
    static constexpr uint16_t TEXT_DIM      = 0x8410;  // Gray
    static constexpr uint16_t CLAUDE_ORANGE = 0xFBE0;  // Claude brand-ish orange
    static constexpr uint16_t BLUE_IDLE     = 0x2D7F;  // Calm blue
    static constexpr uint16_t GREEN_OK      = 0x07E0;  // Green
    static constexpr uint16_t RED_ALERT     = 0xF800;  // Red
    static constexpr uint16_t RED_SOFT      = 0xC000;  // Darker red
    static constexpr uint16_t YELLOW_WARN   = 0xFFE0;  // Yellow
    static constexpr uint16_t PURPLE_TOOL   = 0x780F;  // Purple
    static constexpr uint16_t CYAN_INFO     = 0x07FF;  // Cyan
}

class Animation {
public:
    virtual ~Animation() = default;
    virtual void begin() {}
    virtual void update(uint32_t elapsed_ms) = 0;
    virtual void draw(LGFX_Sprite* canvas, int16_t x, int16_t y, int16_t w, int16_t h) = 0;
};
