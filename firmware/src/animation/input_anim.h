#pragma once

#include "animation.h"

// INPUT state: Blinking cursor prompt
// Indicates Claude is waiting for user input
class InputAnimation : public Animation {
public:
    void begin() override { _phase = 0; }

    void update(uint32_t elapsed_ms) override {
        _phase += elapsed_ms;
    }

    void draw(LGFX_Sprite* canvas, int16_t x, int16_t y, int16_t w, int16_t h) override {
        int16_t cx = x + w / 2;
        int16_t cy = y + h / 2;

        // Terminal prompt visualization
        int16_t promptX = cx - 60;
        int16_t promptY = cy - 20;

        // Terminal background box
        canvas->fillRoundRect(cx - 80, cy - 40, 160, 80, 6, canvas->color565(20, 20, 30));
        canvas->drawRoundRect(cx - 80, cy - 40, 160, 80, 6, Colors::CYAN_INFO);

        // Prompt symbol ">"
        canvas->setTextColor(Colors::GREEN_OK);
        canvas->setTextSize(2);
        canvas->setTextDatum(lgfx::middle_left);
        canvas->drawString(">", promptX, promptY + 5);

        // Blinking cursor (500ms on, 500ms off)
        bool cursorVisible = ((_phase / 500) % 2) == 0;
        if (cursorVisible) {
            int16_t cursorX = promptX + 24;
            canvas->fillRect(cursorX, promptY - 5, 12, 20, Colors::CLAUDE_ORANGE);
        }

        // Floating dots below (waiting indicator)
        for (int i = 0; i < 3; i++) {
            uint8_t dotAngle = (uint8_t)((_phase * 256) / 1500) + i * 50;
            int8_t bounce = isin(dotAngle);
            int16_t dy = (bounce * 6) / 127;

            int16_t dx = cx - 16 + i * 16;
            int16_t dotY = cy + 30 + dy;

            canvas->fillCircle(dx, dotY, 3, Colors::CLAUDE_ORANGE);
        }

        // "INPUT NEEDED" text
        canvas->setTextColor(Colors::CYAN_INFO);
        canvas->setTextSize(1);
        canvas->setTextDatum(lgfx::top_center);
        canvas->drawString("INPUT NEEDED", cx, cy + 45);
    }

private:
    uint32_t _phase = 0;
};
