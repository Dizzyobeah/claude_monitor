#pragma once

#include <cstdint>

// Theme configuration for display colors.
// Stored in ESP32 NVS and configurable via BLE command.
// Three built-in themes; the active theme ID is persisted across reboots.

struct Theme {
    uint16_t bg_dark;
    uint16_t bg_panel;
    uint16_t text_primary;
    uint16_t text_dim;
    uint16_t accent;        // Claude orange equivalent
    uint16_t blue_idle;
    uint16_t red_alert;
    uint16_t yellow_warn;
    uint16_t purple_tool;
    uint16_t cyan_info;
};

enum class ThemeId : uint8_t {
    THEME_DEFAULT = 0,
    THEME_DARK = 1,
    THEME_HIGH_CONTRAST = 2,
    NUM_THEMES
};

static constexpr Theme THEMES[] = {
    // DEFAULT — current Claude Monitor colors
    {
        .bg_dark      = 0x1082,
        .bg_panel     = 0x2104,
        .text_primary = 0xFFFF,
        .text_dim     = 0x8410,
        .accent       = 0xFBE0,  // Claude orange
        .blue_idle    = 0x2D7F,
        .red_alert    = 0xF800,
        .yellow_warn  = 0xFFE0,
        .purple_tool  = 0x780F,
        .cyan_info    = 0x07FF,
    },
    // DARK — muted, lower brightness
    {
        .bg_dark      = 0x0000,  // Pure black
        .bg_panel     = 0x1082,
        .text_primary = 0xC618,  // Light gray
        .text_dim     = 0x4208,  // Darker gray
        .accent       = 0xC380,  // Dim orange
        .blue_idle    = 0x1A5F,
        .red_alert    = 0xA000,
        .yellow_warn  = 0xC580,
        .purple_tool  = 0x4807,
        .cyan_info    = 0x04BF,
    },
    // HIGH_CONTRAST — maximum readability
    {
        .bg_dark      = 0x0000,
        .bg_panel     = 0x0000,
        .text_primary = 0xFFFF,
        .text_dim     = 0xFFFF,
        .accent       = 0xFFE0,  // Bright yellow
        .blue_idle    = 0x07FF,  // Cyan
        .red_alert    = 0xF800,
        .yellow_warn  = 0xFFE0,
        .purple_tool  = 0xF81F,  // Magenta
        .cyan_info    = 0x07FF,
    },
};

static constexpr uint8_t NUM_THEMES = static_cast<uint8_t>(ThemeId::NUM_THEMES);

inline const Theme& getTheme(ThemeId id) {
    uint8_t idx = static_cast<uint8_t>(id);
    return THEMES[idx < NUM_THEMES ? idx : 0];
}
