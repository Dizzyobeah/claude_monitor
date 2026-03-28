#pragma once

#include "board/board_config.h"

class TouchHandler {
public:
    void begin(LGFX* lcd);
    bool update();  // Returns true if a tap was detected

private:
    LGFX* _lcd = nullptr;
    bool _wasTouched = false;
    uint32_t _lastTouchTime = 0;

    static constexpr uint32_t DEBOUNCE_MS = 200;
};
