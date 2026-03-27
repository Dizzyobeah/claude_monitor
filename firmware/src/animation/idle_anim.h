#pragma once

#include "animation.h"

// IDLE state: Slow pulsing circle with breathing effect
// Calm, muted blue that gently breathes in and out
class IdleAnimation : public Animation {
public:
    void begin() override { _phase = 0; }

    void update(uint32_t elapsed_ms) override {
        _phase += elapsed_ms;
    }

    void draw(LGFX_Sprite* canvas, int16_t x, int16_t y, int16_t w, int16_t h) override {
        int16_t cx = x + w / 2;
        int16_t cy = y + h / 2;

        // Breathing: slow sine wave over ~3 second period
        uint8_t angle = (uint8_t)((_phase * 256) / 3000);
        int8_t breath = isin(angle);  // -127 to 127

        // Base radius 30, oscillates +/- 10
        int16_t radius = 30 + (breath * 10) / 127;

        // Outer glow rings (fading outward)
        for (int r = radius + 20; r > radius; r -= 4) {
            uint8_t alpha = (uint8_t)((r - radius) * 3);
            // Blend blue with background
            uint16_t color = canvas->color565(
                alpha / 8,
                alpha / 4 + 20,
                alpha / 2 + 40
            );
            canvas->drawCircle(cx, cy, r, color);
        }

        // Main circle with brightness based on breath
        uint8_t bright = 100 + (breath + 127) * 100 / 254;  // 100-200
        uint16_t mainColor = canvas->color565(bright / 6, bright / 3, bright);
        canvas->fillCircle(cx, cy, radius, mainColor);

        // Inner highlight
        int16_t hlRadius = radius * 2 / 3;
        uint16_t hlColor = canvas->color565(bright / 4, bright / 2, 255);
        canvas->fillCircle(cx - radius / 4, cy - radius / 4, hlRadius, hlColor);

        // Small dot in center
        canvas->fillCircle(cx, cy, 4, Colors::TEXT_PRIMARY);
    }

private:
    uint32_t _phase = 0;
};
