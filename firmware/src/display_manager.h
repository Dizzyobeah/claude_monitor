#pragma once

#include "board/board_config.h"
#include "session_store.h"
#include "animation/animation.h"
#include "animation/clawd_anim.h"
#include "util.h"

// Layout constants
static constexpr int16_t HEADER_H  = 0;
static constexpr int16_t ANIM_H    = 180;
static constexpr int16_t FOOTER_H  = 60;  // SCREEN_H - ANIM_H

class DisplayManager {
public:
    void begin(LGFX* lcd);
    void update(uint32_t now, SessionStore* sessions, bool bleConnected);
    void drawPasskeyOverlay(uint32_t passkey);
    void drawCentreMessage(const char* msg);  // Full-screen message (e.g. "PAIRING RESET")

private:
    LGFX* _lcd = nullptr;
    LGFX_Sprite* _canvas = nullptr;  // Animation-zone back buffer (240×ANIM_H) — flicker-free push

    ClawdAnimation _clawdAnim;  // Handles all 6 session states

    SessionState _currentState    = SessionState::DISCONNECTED;
    SessionState _lastFooterState = SessionState::DISCONNECTED;
    uint8_t _lastDisplayRank = 0xFF;  // Force first footer draw

    // Tracks the last full-screen idle/disconnected draw so we only repaint on
    // transitions — same pattern as footer, avoids per-frame fillScreen flicker.
    enum class IdleScreen { NONE, WAITING_BLE, NO_SESSIONS, PASSKEY };
    IdleScreen _lastIdleScreen = IdleScreen::NONE;

    // Phase accumulator for idle/disconnected screen animations.
    // Updated with elapsed time so animations are frame-rate independent and
    // don't rely on millis() directly.
    uint32_t _idlePhase = 0;

    // Tracks whether the animation zone actually changed last frame.
    // When false, pushSprite is skipped to save ~15ms of SPI bandwidth.
    bool _animDirty = true;

    uint32_t _lastFrameTime = 0;

    Animation* animForState();
    void drawFooter(Session* session, uint8_t sessionCount, uint8_t displayRank);
    void drawWaitingForBle();
    void drawNoSessionsFooter();
};
