#pragma once

#include "animation.h"

// PERMISSION state: Urgent red pulsing border with bell icon
// This is the most attention-grabbing animation - user needs to approve something
class PermissionAnimation : public Animation {
public:
    void begin() override { _phase = 0; }

    void update(uint32_t elapsed_ms) override {
        _phase += elapsed_ms;
    }

    void draw(LGFX_Sprite* canvas, int16_t x, int16_t y, int16_t w, int16_t h) override {
        int16_t cx = x + w / 2;
        int16_t cy = y + h / 2;

        // Fast pulse ~1 second period
        uint8_t angle = (uint8_t)((_phase * 256) / 1000);
        int8_t pulse = isin(angle);
        uint8_t intensity = 128 + pulse;  // 1-255

        // Pulsing red border (thick)
        uint16_t borderColor = canvas->color565(intensity, 0, 0);
        for (int i = 0; i < 4; i++) {
            canvas->drawRect(x + i, y + i, w - 2 * i, h - 2 * i, borderColor);
        }

        // Bell icon - body (trapezoid approximation using triangles + rect)
        int16_t bellTop = cy - 30;
        int16_t bellBot = cy + 15;
        int16_t bellW = 40;

        // Bell dome (half circle on top)
        canvas->fillCircle(cx, bellTop + 5, 12, Colors::YELLOW_WARN);

        // Bell body (widens downward)
        canvas->fillTriangle(
            cx - 8, bellTop + 5,
            cx + 8, bellTop + 5,
            cx - bellW / 2, bellBot,
            Colors::YELLOW_WARN
        );
        canvas->fillTriangle(
            cx + 8, bellTop + 5,
            cx - bellW / 2, bellBot,
            cx + bellW / 2, bellBot,
            Colors::YELLOW_WARN
        );

        // Bell rim
        canvas->fillRoundRect(cx - bellW / 2 - 4, bellBot, bellW + 8, 6, 3, Colors::YELLOW_WARN);

        // Bell clapper
        canvas->fillCircle(cx, bellBot + 10, 5, Colors::YELLOW_WARN);

        // Shake effect on the bell
        int8_t shake = isin((uint8_t)((_phase * 256) / 200));
        int16_t shakeOff = (shake * 3) / 127;

        // Sound lines (animated)
        uint8_t linePhase = (uint8_t)((_phase * 256) / 400);
        for (int side = -1; side <= 1; side += 2) {
            for (int i = 0; i < 3; i++) {
                int8_t a = isin(linePhase + i * 40);
                uint8_t alpha = 100 + (a + 127) * 100 / 254;
                int16_t lx = cx + side * (bellW / 2 + 10 + i * 8) + shakeOff;
                int16_t ly1 = cy - 15 + i * 5;
                int16_t ly2 = cy + 5 - i * 5;
                uint16_t lineColor = canvas->color565(alpha, alpha / 2, 0);
                canvas->drawLine(lx, ly1, lx, ly2, lineColor);
            }
        }

        // "APPROVE" text below (blinking)
        bool textVisible = ((_phase / 500) % 2) == 0;
        if (textVisible) {
            canvas->setTextColor(Colors::RED_ALERT);
            canvas->setTextSize(1);
            canvas->setTextDatum(lgfx::top_center);
            canvas->drawString("TAP TO FOCUS", cx, cy + 35);
        }
    }

private:
    uint32_t _phase = 0;
};
