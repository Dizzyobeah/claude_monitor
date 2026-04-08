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
    // If allocation fails, retry with progressively smaller band heights.
    static constexpr int16_t FULL_SPRITE_H = ANIM_DIRTY_Y1 - ANIM_DIRTY_Y0;
    Serial.printf("[Display] Free heap: %u bytes, max contiguous: %u bytes\n",
                  (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap());

    void* buf = nullptr;
    int16_t spriteH = FULL_SPRITE_H;

    // Try full band first, then halve until allocation succeeds or band is too small
    while (spriteH >= 40 && !buf) {
        Serial.printf("[Display] Trying sprite %dx%d = %u bytes\n",
                      SCREEN_W, spriteH, (unsigned)(SCREEN_W * spriteH * 2));
        _canvas = new LGFX_Sprite(_lcd);
        _canvas->setColorDepth(16);
        buf = _canvas->createSprite(SCREEN_W, spriteH);
        if (!buf) {
            Serial.printf("[Display] Sprite %dx%d failed — trying smaller\n", SCREEN_W, spriteH);
            delete _canvas;
            _canvas = nullptr;
            spriteH = spriteH * 3 / 4;  // Reduce by 25% each attempt
        }
    }

    Serial.printf("[Display] Free heap after alloc: %u bytes\n", (unsigned)ESP.getFreeHeap());

    if (!buf) {
        Serial.println("[Display] ERROR: all sprite allocations failed — rendering direct to LCD");
        _canvas = nullptr;
    } else {
        Serial.printf("[Display] Sprite OK (%dx%d 16-bit, %u bytes)\n",
                      SCREEN_W, spriteH, (unsigned)(SCREEN_W * spriteH * 2));
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
            _lastDisplayRank = 0xFF;
        }
        drawWaitingForBle();
        return;
    }

    Session* displayed = sessions->getDisplayed();

    // --- NO SESSIONS: show IDLE character with "NO SESSIONS" footer ---
    if (!displayed) {
        if (_lastIdleScreen != IdleScreen::NO_SESSIONS) {
            _lcd->fillScreen(Colors::BG_DARK);
            _lastIdleScreen = IdleScreen::NO_SESSIONS;
            _lastFooterState = SessionState::DISCONNECTED;
            _lastDisplayRank = 0xFF;
            // Set up IDLE animation for the character sprite
            _currentState = SessionState::IDLE;
            _clawdAnim.setState(SessionState::IDLE);
            _clawdAnim.begin();
            _animDirty = true;
            // Draw the "NO SESSIONS" footer once
            drawNoSessionsFooter();
        }
        // Animate the IDLE character — same rendering path as active sessions
        _clawdAnim.update(elapsed);
        _animDirty = _clawdAnim.isDirty();
        if (_animDirty) {
            if (_canvas) {
                static constexpr int16_t BAND_H = ANIM_DIRTY_Y1 - ANIM_DIRTY_Y0;
                _canvas->fillScreen(Colors::BG_DARK);
                _clawdAnim.draw(_canvas, 0, -ANIM_DIRTY_Y0, SCREEN_W, ANIM_H);
                const uint16_t* buf = reinterpret_cast<const uint16_t*>(_canvas->getBuffer());
                _lcd->startWrite();
                _lcd->pushImage(0, HEADER_H + ANIM_DIRTY_Y0, SCREEN_W, BAND_H, buf);
                _lcd->endWrite();
            } else {
                _lcd->fillRect(0, HEADER_H, SCREEN_W, ANIM_H, Colors::BG_DARK);
                _clawdAnim.draw(_lcd, 0, HEADER_H, SCREEN_W, ANIM_H);
            }
        }
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

    // 2. Footer: redrawn on state transitions or session switches.
    //    Animated elements (blinking arrows) live inside the sprite above.
    uint8_t rank = sessions->displayRank();
    if (displayed->state != _lastFooterState || rank != _lastDisplayRank) {
        drawFooter(displayed, sessions->count(), rank);
        _lastFooterState = displayed->state;
        _lastDisplayRank = rank;
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

    // --- Multi-session navigation: arrows + dot indicator ---
    // Drawn only when there are multiple sessions. Navigation arrows on left/right
    // edges for finger tapping; dots in the centre show which session is active.
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

        // Navigation arrows — big filled triangles at left/right edges,
        // vertically centred between state text and dots for easy finger taps.
        static constexpr int16_t ARROW_H  = 14;  // half-height (28px total)
        static constexpr int16_t ARROW_W  = 16;  // width (tip to base)
        int16_t arrowY = footerY + 46;           // between text (y+22) and dots (y+73)
        uint16_t arrowColor = Colors::TEXT_DIM;

        // Left arrow  (◀) — tip points left
        int16_t lx = 14;  // tip X
        _lcd->fillTriangle(
            lx,             arrowY,              // tip
            lx + ARROW_W,   arrowY - ARROW_H,    // top-right
            lx + ARROW_W,   arrowY + ARROW_H,    // bottom-right
            arrowColor
        );

        // Right arrow (▶) — tip points right
        int16_t rx = SCREEN_W - 14;  // tip X
        _lcd->fillTriangle(
            rx,             arrowY,              // tip
            rx - ARROW_W,   arrowY - ARROW_H,    // top-left
            rx - ARROW_W,   arrowY + ARROW_H,    // bottom-left
            arrowColor
        );
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
// Passkey overlay — shown during BLE pairing so user can enter PIN
// ---------------------------------------------------------------------------
void DisplayManager::drawPasskeyOverlay(uint32_t passkey) {
    _lcd->fillScreen(Colors::BG_DARK);

    _lcd->setTextColor(Colors::CLAUDE_ORANGE);
    _lcd->setTextSize(2);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString("BLE Pairing", SCREEN_W / 2, SCREEN_H / 2 - 60);

    _lcd->setTextColor(Colors::TEXT_PRIMARY);
    _lcd->setTextSize(1);
    _lcd->drawString("Enter this passkey on", SCREEN_W / 2, SCREEN_H / 2 - 30);
    _lcd->drawString("your computer:", SCREEN_W / 2, SCREEN_H / 2 - 15);

    // Large passkey display
    char buf[8];
    snprintf(buf, sizeof(buf), "%06u", passkey);
    _lcd->setTextColor(Colors::CYAN_INFO);
    _lcd->setTextSize(4);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString(buf, SCREEN_W / 2, SCREEN_H / 2 + 30);

    _lcd->setTextColor(Colors::TEXT_DIM);
    _lcd->setTextSize(1);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString("Passkey expires after pairing", SCREEN_W / 2, SCREEN_H / 2 + 70);

    // Mark screen state so normal display forces a full redraw after pairing
    _lastIdleScreen = IdleScreen::PASSKEY;
    _lastFooterState = SessionState::DISCONNECTED;
}

// ---------------------------------------------------------------------------
// Centre message — full-screen text for critical events (e.g. pairing reset)
// ---------------------------------------------------------------------------
void DisplayManager::drawCentreMessage(const char* msg) {
    _lcd->fillScreen(TFT_BLACK);
    _lcd->setTextColor(TFT_WHITE);
    _lcd->setTextSize(2);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString(msg, SCREEN_W / 2, SCREEN_H / 2);

    // Force a full redraw next update cycle
    _lastIdleScreen = IdleScreen::NONE;
    _lastFooterState = SessionState::DISCONNECTED;
}

// ---------------------------------------------------------------------------
// No sessions footer — static footer drawn once when entering the
// no-sessions state.  The animation zone uses the normal IDLE character.
// ---------------------------------------------------------------------------
void DisplayManager::drawNoSessionsFooter() {
    int16_t footerY = HEADER_H + ANIM_H;

    _lcd->fillRect(0, footerY, SCREEN_W, FOOTER_H, Colors::BG_PANEL);
    _lcd->drawFastHLine(0, footerY, SCREEN_W, Colors::CLAUDE_ORANGE);

    _lcd->setTextColor(Colors::BLUE_IDLE);
    _lcd->setTextSize(2);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString("NO SESSIONS", SCREEN_W / 2, footerY + 22);

    _lcd->setTextColor(Colors::TEXT_DIM);
    _lcd->setTextSize(1);
    _lcd->setTextDatum(lgfx::middle_center);
    _lcd->drawString("Waiting for Claude Code...", SCREEN_W / 2, footerY + 50);
}
