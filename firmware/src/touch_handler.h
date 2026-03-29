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

private:
    LGFX* _lcd = nullptr;
    enum class State : uint8_t { IDLE, PRESSED, LONG_PRESS_FIRED };
    State _state = State::IDLE;
    uint32_t _touchDownTime = 0;
    uint32_t _lastReleaseTime = 0;

    static constexpr uint32_t DEBOUNCE_MS = 200;
    static constexpr uint32_t LONG_PRESS_MS = 600;
};
