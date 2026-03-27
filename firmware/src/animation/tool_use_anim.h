#pragma once

#include "animation.h"

// TOOL_USE state: Rotating gear icon
// Purple-themed gear that spins steadily
class ToolUseAnimation : public Animation {
public:
    void begin() override { _phase = 0; }

    void update(uint32_t elapsed_ms) override {
        _phase += elapsed_ms;
    }

    void draw(LGFX_Sprite* canvas, int16_t x, int16_t y, int16_t w, int16_t h) override {
        int16_t cx = x + w / 2;
        int16_t cy = y + h / 2;

        // Rotation angle, ~3 second period
        uint8_t angle = (uint8_t)((_phase * 256) / 3000);

        int16_t outerR = 38;
        int16_t innerR = 24;
        int16_t toothH = 10;
        int teethCount = 8;

        // Draw gear teeth
        for (int i = 0; i < teethCount; i++) {
            uint8_t toothAngle = angle + (i * 256) / teethCount;

            // Outer point of tooth
            int16_t ox = cx + (icos(toothAngle) * (outerR + toothH)) / 127;
            int16_t oy = cy + (isin(toothAngle) * (outerR + toothH)) / 127;

            // Base points of tooth (slightly offset from tooth center)
            uint8_t a1 = toothAngle - 8;
            uint8_t a2 = toothAngle + 8;
            int16_t b1x = cx + (icos(a1) * outerR) / 127;
            int16_t b1y = cy + (isin(a1) * outerR) / 127;
            int16_t b2x = cx + (icos(a2) * outerR) / 127;
            int16_t b2y = cy + (isin(a2) * outerR) / 127;

            canvas->fillTriangle(ox, oy, b1x, b1y, b2x, b2y, Colors::PURPLE_TOOL);
        }

        // Gear body (filled circle)
        canvas->fillCircle(cx, cy, outerR, Colors::PURPLE_TOOL);

        // Inner ring
        canvas->fillCircle(cx, cy, innerR, Colors::BG_PANEL);

        // Center hub
        canvas->fillCircle(cx, cy, 10, Colors::PURPLE_TOOL);
        canvas->fillCircle(cx, cy, 5, Colors::BG_DARK);

        // Spinning indicator: a bright dot on the gear edge
        int16_t indX = cx + (icos(angle) * (innerR + 5)) / 127;
        int16_t indY = cy + (isin(angle) * (innerR + 5)) / 127;
        canvas->fillCircle(indX, indY, 3, Colors::CYAN_INFO);

        // Progress dots around the outside
        uint8_t progressAngle = (uint8_t)((_phase * 256) / 500);
        for (int i = 0; i < 12; i++) {
            uint8_t pa = (i * 256) / 12;
            int16_t px = cx + (icos(pa) * (outerR + toothH + 12)) / 127;
            int16_t py = cy + (isin(pa) * (outerR + toothH + 12)) / 127;
            bool lit = ((pa - progressAngle) & 0xFF) < 128;
            canvas->fillCircle(px, py, 2, lit ? Colors::PURPLE_TOOL : Colors::BG_PANEL);
        }
    }

private:
    uint32_t _phase = 0;
};
