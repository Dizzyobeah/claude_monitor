#pragma once

#include "board/board_config.h"

class TouchHandler {
public:
    void begin(LGFX* lcd);
    bool update();  // Returns true if a tap was detected
    int16_t lastX() const { return _lastX; }
    int16_t lastY() const { return _lastY; }

private:
    LGFX* _lcd = nullptr;
    bool _wasTouched = false;
    uint32_t _lastTouchTime = 0;
    int16_t _lastX = 0;
    int16_t _lastY = 0;

    static constexpr uint32_t DEBOUNCE_MS = 200;
};
