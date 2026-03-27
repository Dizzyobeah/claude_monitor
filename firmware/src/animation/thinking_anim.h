#pragma once

#include "animation.h"

// THINKING state: Three dots orbiting a center point
// Smooth circular motion with trailing fade effect
class ThinkingAnimation : public Animation {
public:
    void begin() override { _phase = 0; }

    void update(uint32_t elapsed_ms) override {
        _phase += elapsed_ms;
    }

    void draw(LGFX_Sprite* canvas, int16_t x, int16_t y, int16_t w, int16_t h) override {
        int16_t cx = x + w / 2;
        int16_t cy = y + h / 2;
        int16_t orbitR = 40;

        // Base angle rotates over ~2 second period
        uint8_t baseAngle = (uint8_t)((_phase * 256) / 2000);

        // Draw orbit track (subtle)
        canvas->drawCircle(cx, cy, orbitR, Colors::BG_PANEL);

        // Three dots, 120 degrees apart (85 units in 256-space)
        for (int i = 0; i < 3; i++) {
            uint8_t dotAngle = baseAngle + i * 85;

            // Trail: 4 fading ghost positions
            for (int t = 4; t >= 1; t--) {
                uint8_t trailAngle = dotAngle - t * 6;
                int16_t tx = cx + (icos(trailAngle) * orbitR) / 127;
                int16_t ty = cy + (isin(trailAngle) * orbitR) / 127;
                uint8_t alpha = (5 - t) * 40;
                uint16_t trailColor;
                if (i == 0) trailColor = canvas->color565(alpha, alpha / 2, 0);
                else if (i == 1) trailColor = canvas->color565(alpha, alpha * 3 / 4, 0);
                else trailColor = canvas->color565(alpha, alpha, alpha / 3);
                canvas->fillCircle(tx, ty, 4, trailColor);
            }

            // Main dot
            int16_t dx = cx + (icos(dotAngle) * orbitR) / 127;
            int16_t dy = cy + (isin(dotAngle) * orbitR) / 127;

            uint16_t dotColor;
            if (i == 0) dotColor = Colors::CLAUDE_ORANGE;
            else if (i == 1) dotColor = Colors::YELLOW_WARN;
            else dotColor = canvas->color565(255, 200, 100);

            canvas->fillCircle(dx, dy, 7, dotColor);
            canvas->fillCircle(dx - 2, dy - 2, 3, Colors::TEXT_PRIMARY);  // Highlight
        }

        // Center dot
        canvas->fillCircle(cx, cy, 5, Colors::CLAUDE_ORANGE);
    }

private:
    uint32_t _phase = 0;
};
