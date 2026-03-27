#pragma once

#include "animation.h"

// ERROR state: Red X with horizontal shake effect
class ErrorAnimation : public Animation {
public:
    void begin() override { _phase = 0; }

    void update(uint32_t elapsed_ms) override {
        _phase += elapsed_ms;
    }

    void draw(LGFX_Sprite* canvas, int16_t x, int16_t y, int16_t w, int16_t h) override {
        int16_t cx = x + w / 2;
        int16_t cy = y + h / 2;

        // Shake effect (decaying sine, resets every 2 seconds)
        uint32_t shakePhase = _phase % 2000;
        int16_t shakeOff = 0;
        if (shakePhase < 500) {
            uint8_t sa = (uint8_t)((shakePhase * 256) / 100);  // Fast shake
            int8_t sv = isin(sa);
            int16_t decay = 500 - shakePhase;  // Decays from 500 to 0
            shakeOff = (sv * decay * 6) / (127 * 500);
        }

        int16_t drawCx = cx + shakeOff;

        // Red glow background circle
        uint8_t glowAngle = (uint8_t)((_phase * 256) / 2000);
        int8_t glowPulse = isin(glowAngle);
        int16_t glowR = 45 + (glowPulse * 5) / 127;
        uint8_t glowBright = 40 + (glowPulse + 127) * 30 / 254;
        canvas->fillCircle(drawCx, cy, glowR, canvas->color565(glowBright, 0, 0));

        // X shape (two thick lines)
        int16_t arm = 22;
        int16_t thick = 5;

        // Draw thick X using multiple offset lines
        for (int t = -thick; t <= thick; t++) {
            canvas->drawLine(drawCx - arm + t, cy - arm, drawCx + arm + t, cy + arm, Colors::RED_ALERT);
            canvas->drawLine(drawCx + arm + t, cy - arm, drawCx - arm + t, cy + arm, Colors::RED_ALERT);
        }

        // White border on X for contrast
        canvas->drawLine(drawCx - arm, cy - arm, drawCx + arm, cy + arm, Colors::TEXT_PRIMARY);
        canvas->drawLine(drawCx + arm, cy - arm, drawCx - arm, cy + arm, Colors::TEXT_PRIMARY);

        // "ERROR" text below
        canvas->setTextColor(Colors::RED_ALERT);
        canvas->setTextSize(1);
        canvas->setTextDatum(lgfx::top_center);

        bool textBlink = ((_phase / 800) % 2) == 0;
        if (textBlink) {
            canvas->drawString("ERROR", cx, cy + 50);
        }
    }

private:
    uint32_t _phase = 0;
};
