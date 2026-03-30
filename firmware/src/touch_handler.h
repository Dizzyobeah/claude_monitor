#pragma once

#include "board/board_config.h"

enum class TouchEvent : uint8_t { NONE, TAP, LONG_PRESS };

class TouchHandler {
public:
    void begin(LGFX* lcd);
    TouchEvent update();  // Returns event type each frame

    // True while finger is held down past the long-press threshold.
    // Use for visual feedback (e.g. LED color change).
    bool isLongPressActive() const { return _state == State::LONG_PRESS_FIRED; }

    // Screen coordinates of the last touch-down event.
    // Valid after update() returns TAP or LONG_PRESS.
    int16_t lastX() const { return _lastX; }
    int16_t lastY() const { return _lastY; }

private:
    LGFX* _lcd = nullptr;
    enum class State : uint8_t { IDLE, PRESSED, LONG_PRESS_FIRED };
    State _state = State::IDLE;
    uint32_t _touchDownTime = 0;
    uint32_t _lastReleaseTime = 0;
    int16_t _lastX = 0;
    int16_t _lastY = 0;

    static constexpr uint32_t DEBOUNCE_MS = 200;
    static constexpr uint32_t LONG_PRESS_MS = 600;
};
