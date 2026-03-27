#include "touch_handler.h"

void TouchHandler::begin(LGFX* lcd) {
    _lcd = lcd;
    _wasTouched = false;
    _lastTouchTime = 0;
}

bool TouchHandler::update() {
    uint32_t now = millis();

    lgfx::touch_point_t tp;
    int touchCount = _lcd->getTouch(&tp, 1);
    bool isTouched = touchCount > 0;

    if (isTouched && !_wasTouched) {
        // Touch down - register tap if debounce period has elapsed
        if (now - _lastTouchTime > DEBOUNCE_MS) {
            _lastX = tp.x;
            _lastY = tp.y;
            _lastTouchTime = now;
            _wasTouched = true;
            return true;  // Tap detected
        }
    }

    if (!isTouched) {
        _wasTouched = false;
    }

    return false;
}
