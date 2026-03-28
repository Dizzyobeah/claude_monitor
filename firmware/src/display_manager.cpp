#include "display_manager.h"

static constexpr uint32_t FRAME_INTERVAL_MS = 33; // ~30 FPS

void DisplayManager::begin(LGFX* lcd) {
    _lcd = lcd;
    _lcd->init();
    _lcd->setRotation(2);  // Portrait, 180° rotated
    _lcd->setBrightness(200);
    _lcd->fillScreen(Colors::BG_DARK);

    // Allocate animation-zone sprite for flicker-free animation rendering.
    // Only allocate the dirty band (rows ANIM_DIRTY_Y0..Y1) instead of the full
    // 240-row animation zone — cuts the buffer from 115KB to ~79KB, which fits
    // in the largest contiguous heap block after LovyanGFX/WiFi allocations.
    static constexpr int16_t SPRITE_H = ANIM_DIRTY_Y1 - ANIM_DIRTY_Y0;
    Serial.printf("[Display] Free heap: %u bytes, max contiguous: %u bytes\n",
                  (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap());
    Serial.printf("[Display] Requesting sprite %dx%d = %u bytes\n",
                  SCREEN_W, SPRITE_H, (unsigned)(SCREEN_W * SPRITE_H * 2));
    _canvas = new LGFX_Sprite(_lcd);
    _canvas->setColorDepth(16);
    void* buf = _canvas->createSprite(SCREEN_W, SPRITE_H);
    Serial.printf("[Display] Free heap after alloc: %u bytes\n", (unsigned)ESP.getFreeHeap());

    if (!buf) {
        Serial.println("[Display] ERROR: sprite allocation failed — not enough contiguous heap!");
        delete _canvas;
        _canvas = nullptr;
    } else {
        Serial.printf("[Display] Sprite OK (%dx%d 16-bit, %u bytes)\n",
                      SCREEN_W, SPRITE_H, (unsigned)(SCREEN_W * SPRITE_H * 2));
        _canvas->fillScreen(Colors::BG_DARK);
    }

    _lastFrameTime = millis();
}

Animation* DisplayManager::animForState() {
    return &_clawdAnim;
}

void DisplayManager::update(uint32_t now, SessionStore* sessions, bool bleConnected) {
    if (now - _lastFrameTime < FRAME_INTERVAL_MS) return;
    uint32_t elapsed = now - _lastFrameTime;
    _lastFrameTime = now;

    // --- NOT CONNECTED: draw full-screen waiting screen only on transition ---
    if (!bleConnected) {
        _idlePhase += elapsed;
        if (_lastIdleScreen != IdleScreen::WAITING_BLE) {
            _lcd->fillScreen(Colors::BG_DARK);
            _lastIdleScreen = IdleScreen::WAITING_BLE;
            _lastFooterState = SessionState::DISCONNECTED;  // force footer redraw on reconnect
        }
        drawWaitingForBle();
        return;
    }

    Session* displayed = sessions->getDisplayed();

    // --- NO SESSIONS: draw full-screen idle screen only on transition ---
    if (!displayed) {
        _idlePhase += elapsed;
        if (_lastIdleScreen != IdleScreen::NO_SESSIONS) {
            _lcd->fillScreen(Colors::BG_DARK);
            _lastIdleScreen = IdleScreen::NO_SESSIONS;
            _lastFooterState = SessionState::DISCONNECTED;  // force footer redraw when session appears
        }
        drawNoSessions();
        return;
    }

    // --- ACTIVE SESSION: animated zone + footer ---

    // On the first active-session frame after an idle screen, clear the full
    // animation zone so rows outside ANIM_DIRTY_Y0..Y1 don't retain idle pixels
    // (those rows are never included in the partial pushSprite band).
    if (_lastIdleScreen != IdleScreen::NONE) {
        _lcd->fillRect(0, HEADER_H, SCREEN_W, ANIM_H, Colors::BG_DARK);
    }

    // Clear idle screen tracker so we re-fill on next disconnect/empty
    _lastIdleScreen = IdleScreen::NONE;
    _idlePhase = 0;

    // Switch animation if state changed
    SessionState newState = displayed->state;
    if (newState != _currentState) {
        _currentState = newState;
        _clawdAnim.setState(_currentState);
        _clawdAnim.begin();
        _animDirty = true;  // state change always requires a redraw
    }

    // 1. Animation zone: draw into sprite, push in one SPI burst — zero flicker.
    //    Skip the push when the animation reports no visual change to save ~15ms SPI.
    Animation* anim = animForState();
    if (anim) {
        anim->update(elapsed);
        _animDirty = _clawdAnim.isDirty();

        if (_animDirty) {
            if (_canvas) {
                // Sprite covers only the dirty band (ANIM_DIRTY_Y0..Y1).
                // Draw with y-offset so the animation renders at the correct
                // position within this smaller sprite.
                static constexpr int16_t BAND_H = ANIM_DIRTY_Y1 - ANIM_DIRTY_Y0;
                _canvas->fillScreen(Colors::BG_DARK);
                anim->draw(_canvas, 0, -ANIM_DIRTY_Y0, SCREEN_W, ANIM_H);
                // Push the entire sprite to the corresponding LCD region
                const uint16_t* buf = reinterpret_cast<const uint16_t*>(_canvas->getBuffer());
                _lcd->startWrite();
                _lcd->pushImage(0, HEADER_H + ANIM_DIRTY_Y0, SCREEN_W, BAND_H, buf);
                _lcd->endWrite();
            } else {
                // Fallback: no sprite (OOM) — draw directly to LCD (may flicker slightly)
                _lcd->fillRect(0, HEADER_H, SCREEN_W, ANIM_H, Colors::BG_DARK);
                anim->draw(_lcd, 0, HEADER_H, SCREEN_W, ANIM_H);
            }
        }
    }

    // 2. Footer: only redrawn on state transitions — content is static per-state.
    //    Animated elements (blinking arrows) live inside the sprite above.
    if (displayed->state != _lastFooterState) {
        drawFooter(displayed, sessions->count(), sessions->displayRank());
        _lastFooterState = displayed->state;
    }
}

// ---------------------------------------------------------------------------
// Footer — drawn directly to _lcd (80px tall, mostly static per state)
// ---------------------------------------------------------------------------
void DisplayManager::drawFooter(Session* session, uint8_t sessionCount, uint8_t displayRank) {
    int16_t footerY = HEADER_H + ANIM_H;

    _lcd->fillRect(0, footerY, SCREEN_W, FOOTER_H, Colors::BG_PANEL);
    _lcd->drawFastHLine(0, footerY, SCREEN_W, Colors::CLAUDE_ORANGE);

    const char* stateName = stateToString(session->state);
    uint16_t stateColor = Colors::TEXT_PRIMARY;
    switch (session->state) {
        case SessionState::THINKING:     stateColor = Colors::CLAUDE_ORANGE; break;
        case SessionState::TOOL_USE:     stateColor = Colors::PURPLE_TOOL;   break;
        case SessionState::PERMISSION:   stateColor = Colors::RED_ALERT;     break;
        case SessionState::INPUT_NEEDED: stateColor = Colors::CYAN_INFO;     break;
        case SessionState::ERROR:        stateColor = Colors::RED_ALERT;     break;
        default:                         stateColor = Colors::BLUE_IDLE;     break;
    }

    _lcd->setTextColor(stateColor);
    _lcd->setTextSize(2);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString(stateName, SCREEN_W / 2, footerY + 22);

    if (stateNeedsAttention(session->state)) {
        _lcd->setTextColor(Colors::YELLOW_WARN);
        _lcd->setTextSize(1);
        _lcd->setTextDatum(lgfx::middle_center);
        _lcd->drawString("TAP SCREEN TO FOCUS", SCREEN_W / 2, footerY + 50);
    } else {
        _lcd->setTextColor(Colors::TEXT_DIM);
        _lcd->setTextSize(1);
        _lcd->setTextDatum(lgfx::middle_center);
        char sidLabel[16];
        snprintf(sidLabel, sizeof(sidLabel), "session: %s", session->sid);
        _lcd->drawString(sidLabel, SCREEN_W / 2, footerY + 50);
    }

    // --- Multi-session dot indicator ---
    // Drawn only when there are multiple sessions. Filled dot = current session,
    // empty dot = other session. Max 8 sessions (MAX_SESSIONS), dots are 6px
    // diameter with 10px spacing, centered horizontally at the bottom of footer.
    if (sessionCount > 1) {
        static constexpr int16_t DOT_R    = 3;   // dot radius
        static constexpr int16_t DOT_GAP  = 10;  // centre-to-centre spacing
        int16_t totalW  = (sessionCount - 1) * DOT_GAP;
        int16_t startX  = (SCREEN_W - totalW) / 2;
        int16_t dotY    = footerY + FOOTER_H - DOT_R - 4;
        for (uint8_t i = 0; i < sessionCount; i++) {
            int16_t dx = startX + i * DOT_GAP;
            if (i == displayRank) {
                _lcd->fillCircle(dx, dotY, DOT_R, stateColor);
            } else {
                _lcd->drawCircle(dx, dotY, DOT_R, Colors::TEXT_DIM);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Waiting for BLE — full-screen static content drawn once on transition,
// then only the animated elements are redrawn each frame.
// ---------------------------------------------------------------------------
void DisplayManager::drawWaitingForBle() {
    // Static text is drawn only once (on transition, when _lastIdleScreen changed).
    // Here we only redraw the animated elements using _idlePhase.
    uint8_t angle = (uint8_t)((_idlePhase * 256) / 2000);
    int8_t pulse = isin(angle);
    uint8_t bright = 100 + (pulse + 127) * 100 / 254;
    uint16_t bleColor = _lcd->color565(0, bright * 2 / 3, bright);

    int16_t bx = SCREEN_W / 2;
    int16_t by = SCREEN_H / 2;
    int16_t s = 3;

    // Overdraw static text once more — only needed on the very first call after
    // transition (subsequent calls just update the animated icon in-place, but
    // since we don't have a sprite here we redraw the icon region each frame).
    _lcd->setTextColor(Colors::CLAUDE_ORANGE);
    _lcd->setTextSize(2);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString("Claude Monitor", SCREEN_W / 2, SCREEN_H / 2 - 60);

    // Erase previous icon area before redrawing (avoids ghost pixels from last frame)
    _lcd->fillRect(bx - 45, by - 45, 90, 90, Colors::BG_DARK);

    _lcd->drawLine(bx, by - 8*s, bx, by + 8*s, bleColor);
    _lcd->drawLine(bx, by - 8*s, bx + 5*s, by - 3*s, bleColor);
    _lcd->drawLine(bx + 5*s, by - 3*s, bx - 4*s, by + 4*s, bleColor);
    _lcd->drawLine(bx, by + 8*s, bx + 5*s, by + 3*s, bleColor);
    _lcd->drawLine(bx + 5*s, by + 3*s, bx - 4*s, by - 4*s, bleColor);

    // Broadcast arcs
    for (int r = 20; r <= 35; r += 8) {
        uint8_t arcBright = bright * (40 - r) / 40;
        uint16_t arcColor = _lcd->color565(0, arcBright * 2 / 3, arcBright);
        _lcd->drawCircle(bx, by, r, arcColor);
    }

    _lcd->setTextColor(Colors::TEXT_DIM);
    _lcd->setTextSize(1);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString("Bluetooth advertising...", SCREEN_W / 2, SCREEN_H / 2 + 50);
    _lcd->drawString("Run claude-monitor on",    SCREEN_W / 2, SCREEN_H / 2 + 70);
    _lcd->drawString("your computer to connect", SCREEN_W / 2, SCREEN_H / 2 + 85);
}

// ---------------------------------------------------------------------------
// No sessions — full-screen. Static text drawn once on transition;
// only the breathing dot is redrawn each frame using _idlePhase.
// ---------------------------------------------------------------------------
void DisplayManager::drawNoSessions() {
    // Static labels — cheap to redraw (no flicker risk, just text on dark bg)
    _lcd->setTextColor(Colors::TEXT_DIM);
    _lcd->setTextSize(2);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString("Claude Monitor", SCREEN_W / 2, SCREEN_H / 2 - 30);

    _lcd->setTextSize(1);
    _lcd->drawString("No active sessions",        SCREEN_W / 2, SCREEN_H / 2 + 10);
    _lcd->drawString("Waiting for Claude Code...", SCREEN_W / 2, SCREEN_H / 2 + 30);

    _lcd->setTextColor(_lcd->color565(0, 60, 80));
    _lcd->drawString("BLE connected", SCREEN_W / 2, SCREEN_H / 2 + 55);

    // Animated breathing dot — erase old position then redraw with new brightness
    uint8_t angle = (uint8_t)((_idlePhase * 256) / 3000);
    int8_t breath = isin(angle);
    uint8_t bright = 50 + (breath + 127) * 50 / 254;
    int16_t dotX = SCREEN_W / 2;
    int16_t dotY = SCREEN_H / 2 + 80;
    _lcd->fillCircle(dotX, dotY, 6, Colors::BG_DARK);  // erase with 1px margin
    _lcd->fillCircle(dotX, dotY, 5, _lcd->color565(bright, bright / 2, 0));
}
