#include "display_manager.h"

static constexpr uint32_t FRAME_INTERVAL_MS = 33; // ~30 FPS

void DisplayManager::begin(LGFX* lcd) {
    _lcd = lcd;
    _lcd->init();
    _lcd->setRotation(0);  // Portrait
    _lcd->setBrightness(200);
    _lcd->fillScreen(Colors::BG_DARK);

    _canvas.createSprite(SCREEN_W, SCREEN_H);
    _canvas.setSwapBytes(true);

    _lastFrameTime = millis();
}

Animation* DisplayManager::animForState(SessionState state) {
    switch (state) {
        case SessionState::IDLE:         return &_idleAnim;
        case SessionState::THINKING:     return &_thinkingAnim;
        case SessionState::TOOL_USE:     return &_toolUseAnim;
        case SessionState::PERMISSION:   return &_permissionAnim;
        case SessionState::INPUT_NEEDED: return &_inputAnim;
        case SessionState::ERROR:        return &_errorAnim;
        default:                         return &_idleAnim;
    }
}

void DisplayManager::update(uint32_t now, SessionStore* sessions, bool bleConnected) {
    if (now - _lastFrameTime < FRAME_INTERVAL_MS) return;
    uint32_t elapsed = now - _lastFrameTime;
    _lastFrameTime = now;

    _canvas.fillSprite(Colors::BG_DARK);

    // Not connected to daemon
    if (!bleConnected) {
        drawWaitingForBle();
        _canvas.pushSprite(0, 0);
        return;
    }

    Session* displayed = sessions->getDisplayed();

    if (!displayed) {
        drawNoSessions();
        _canvas.pushSprite(0, 0);
        return;
    }

    // Switch animation if state changed
    SessionState newState = displayed->state;
    if (newState != _currentState) {
        _currentState = newState;
        Animation* anim = animForState(_currentState);
        if (anim) anim->begin();
    }

    drawHeader(displayed, sessions->count(), sessions->displayIndex(), bleConnected);

    Animation* anim = animForState(_currentState);
    if (anim) {
        anim->update(elapsed);
        anim->draw(&_canvas, 0, HEADER_H, SCREEN_W, ANIM_H);
    }

    drawFooter(displayed);

    _canvas.pushSprite(0, 0);
}

void DisplayManager::drawHeader(Session* session, uint8_t count, uint8_t displayIdx, bool bleConnected) {
    _canvas.fillRect(0, 0, SCREEN_W, HEADER_H, Colors::BG_PANEL);

    // Session label
    _canvas.setTextColor(Colors::TEXT_PRIMARY);
    _canvas.setTextSize(2);
    _canvas.setTextDatum(lgfx::middle_left);
    _canvas.drawString(session->label, 8, HEADER_H / 2);

    // Session count dots (right side, leave room for BLE icon)
    if (count > 1) {
        int16_t dotStartX = SCREEN_W - 24 - (count * 10);
        int16_t dotY = HEADER_H / 2;
        for (uint8_t slotIdx = 0; slotIdx < count; slotIdx++) {
            if (slotIdx == displayIdx) {
                _canvas.fillCircle(dotStartX + slotIdx * 10, dotY, 4, Colors::CLAUDE_ORANGE);
            } else {
                _canvas.fillCircle(dotStartX + slotIdx * 10, dotY, 3, Colors::TEXT_DIM);
            }
        }
    }

    // BLE indicator (top right)
    int16_t bx = SCREEN_W - 12;
    int16_t by = HEADER_H / 2;
    uint16_t bleColor = bleConnected ? Colors::CYAN_INFO : Colors::TEXT_DIM;
    // Simple Bluetooth rune shape
    _canvas.drawLine(bx, by - 8, bx, by + 8, bleColor);       // Vertical
    _canvas.drawLine(bx, by - 8, bx + 5, by - 3, bleColor);   // Top right
    _canvas.drawLine(bx + 5, by - 3, bx - 4, by + 4, bleColor); // Cross down
    _canvas.drawLine(bx, by + 8, bx + 5, by + 3, bleColor);   // Bottom right
    _canvas.drawLine(bx + 5, by + 3, bx - 4, by - 4, bleColor); // Cross up

    _canvas.drawFastHLine(0, HEADER_H - 1, SCREEN_W, Colors::CLAUDE_ORANGE);
}

void DisplayManager::drawFooter(Session* session) {
    int16_t footerY = HEADER_H + ANIM_H;

    _canvas.fillRect(0, footerY, SCREEN_W, FOOTER_H, Colors::BG_PANEL);
    _canvas.drawFastHLine(0, footerY, SCREEN_W, Colors::CLAUDE_ORANGE);

    const char* stateName = stateToString(session->state);
    uint16_t stateColor = Colors::TEXT_PRIMARY;
    switch (session->state) {
        case SessionState::THINKING:     stateColor = Colors::CLAUDE_ORANGE; break;
        case SessionState::TOOL_USE:     stateColor = Colors::PURPLE_TOOL; break;
        case SessionState::PERMISSION:   stateColor = Colors::RED_ALERT; break;
        case SessionState::INPUT_NEEDED: stateColor = Colors::CYAN_INFO; break;
        case SessionState::ERROR:        stateColor = Colors::RED_ALERT; break;
        default:                         stateColor = Colors::BLUE_IDLE; break;
    }

    _canvas.setTextColor(stateColor);
    _canvas.setTextSize(2);
    _canvas.setTextDatum(lgfx::middle_center);
    _canvas.drawString(stateName, SCREEN_W / 2, footerY + 22);

    if (stateNeedsAttention(session->state)) {
        _canvas.setTextColor(Colors::YELLOW_WARN);
        _canvas.setTextSize(1);
        _canvas.setTextDatum(lgfx::middle_center);
        _canvas.drawString(">>> TAP SCREEN TO FOCUS <<<", SCREEN_W / 2, footerY + 50);

        uint32_t now = millis();
        bool arrowPhase = ((now / 300) % 2) == 0;
        uint16_t arrowColor = arrowPhase ? Colors::YELLOW_WARN : Colors::BG_PANEL;
        _canvas.fillTriangle(5, footerY + 47, 15, footerY + 42, 15, footerY + 52, arrowColor);
        _canvas.fillTriangle(SCREEN_W - 5, footerY + 47, SCREEN_W - 15, footerY + 42, SCREEN_W - 15, footerY + 52, arrowColor);
    } else {
        _canvas.setTextColor(Colors::TEXT_DIM);
        _canvas.setTextSize(1);
        _canvas.setTextDatum(lgfx::middle_center);
        char sidLabel[16];
        snprintf(sidLabel, sizeof(sidLabel), "session: %s", session->sid);
        _canvas.drawString(sidLabel, SCREEN_W / 2, footerY + 50);
    }
}

void DisplayManager::drawWaitingForBle() {
    _canvas.setTextColor(Colors::CLAUDE_ORANGE);
    _canvas.setTextSize(2);
    _canvas.setTextDatum(lgfx::middle_center);
    _canvas.drawString("Claude Monitor", SCREEN_W / 2, SCREEN_H / 2 - 60);

    // Animated Bluetooth icon (pulsing)
    uint8_t angle = (uint8_t)((millis() * 256) / 2000);
    int8_t pulse = isin(angle);
    uint8_t bright = 100 + (pulse + 127) * 100 / 254;
    uint16_t bleColor = _canvas.color565(0, bright * 2 / 3, bright);

    int16_t bx = SCREEN_W / 2;
    int16_t by = SCREEN_H / 2;
    // Larger BLE rune
    int16_t s = 3;  // scale
    _canvas.drawLine(bx, by - 8*s, bx, by + 8*s, bleColor);
    _canvas.drawLine(bx, by - 8*s, bx + 5*s, by - 3*s, bleColor);
    _canvas.drawLine(bx + 5*s, by - 3*s, bx - 4*s, by + 4*s, bleColor);
    _canvas.drawLine(bx, by + 8*s, bx + 5*s, by + 3*s, bleColor);
    _canvas.drawLine(bx + 5*s, by + 3*s, bx - 4*s, by - 4*s, bleColor);

    // Broadcast arcs
    for (int r = 20; r <= 35; r += 8) {
        uint8_t arcBright = bright * (40 - r) / 40;
        uint16_t arcColor = _canvas.color565(0, arcBright * 2 / 3, arcBright);
        _canvas.drawCircle(bx, by, r, arcColor);
    }

    _canvas.setTextColor(Colors::TEXT_DIM);
    _canvas.setTextSize(1);
    _canvas.setTextDatum(lgfx::middle_center);
    _canvas.drawString("Bluetooth advertising...", SCREEN_W / 2, SCREEN_H / 2 + 50);
    _canvas.drawString("Run claude-monitor on", SCREEN_W / 2, SCREEN_H / 2 + 70);
    _canvas.drawString("your computer to connect", SCREEN_W / 2, SCREEN_H / 2 + 85);
}

void DisplayManager::drawNoSessions() {
    _canvas.fillSprite(Colors::BG_DARK);

    _canvas.setTextColor(Colors::TEXT_DIM);
    _canvas.setTextSize(2);
    _canvas.setTextDatum(lgfx::middle_center);
    _canvas.drawString("Claude Monitor", SCREEN_W / 2, SCREEN_H / 2 - 30);

    _canvas.setTextSize(1);
    _canvas.drawString("No active sessions", SCREEN_W / 2, SCREEN_H / 2 + 10);
    _canvas.drawString("Waiting for Claude Code...", SCREEN_W / 2, SCREEN_H / 2 + 30);

    // BLE connected indicator
    _canvas.setTextColor(_canvas.color565(0, 60, 80));
    _canvas.drawString("BLE connected", SCREEN_W / 2, SCREEN_H / 2 + 55);

    // Subtle breathing dot
    uint8_t angle = (uint8_t)((millis() * 256) / 3000);
    int8_t breath = isin(angle);
    uint8_t bright = 50 + (breath + 127) * 50 / 254;
    _canvas.fillCircle(SCREEN_W / 2, SCREEN_H / 2 + 80, 5, _canvas.color565(bright, bright / 2, 0));
}
