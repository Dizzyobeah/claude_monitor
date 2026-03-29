#include "touch_handler.h"

void TouchHandler::begin(LGFX* lcd) {
    _lcd = lcd;
    _state = State::IDLE;
    _touchDownTime = 0;
    _lastReleaseTime = 0;
}

TouchEvent TouchHandler::update() {
    uint32_t now = millis();

    lgfx::touch_point_t tp;
    int touchCount = _lcd->getTouch(&tp, 1);
    bool isTouched = touchCount > 0;

    switch (_state) {
        case State::IDLE:
            if (isTouched && (now - _lastReleaseTime > DEBOUNCE_MS)) {
                _touchDownTime = now;
                _state = State::PRESSED;
            }
            break;

        case State::PRESSED:
            if (!isTouched) {
                // Released before long-press threshold — this is a tap
                _state = State::IDLE;
                _lastReleaseTime = now;
                return TouchEvent::TAP;
            }
            if (now - _touchDownTime >= LONG_PRESS_MS) {
                _state = State::LONG_PRESS_FIRED;
                return TouchEvent::LONG_PRESS;
            }
            break;

        case State::LONG_PRESS_FIRED:
            if (!isTouched) {
                // Finger lifted after long-press was already fired
                _state = State::IDLE;
                _lastReleaseTime = now;
            }
            break;
    }

    return TouchEvent::NONE;
}
