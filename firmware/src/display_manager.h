#pragma once

#include "board/board_config.h"
#include "session_store.h"
#include "animation/animation.h"
#include "animation/clawd_anim.h"

// Layout constants
static constexpr int16_t HEADER_H  = 0;
static constexpr int16_t ANIM_H    = 240;
static constexpr int16_t FOOTER_H  = 80;  // SCREEN_H - ANIM_H

// Rows within the animation sprite that contain the character + all decorations.
// Pushing only this band instead of the full 240-row sprite cuts SPI time by ~30%,
// shrinking the window during which the panel scan and SPI write overlap (tearing).
// Derived from: character center cy=120, body top by=cy-4*S=76, tallest decoration
// (IDLE glow ellipse) ~10px below legs bottom (cy+4*S+3*S+10=197), dots above head
// (cy-4*S-22=54). Add 4px safety margin each side → [50, 210].
static constexpr int16_t ANIM_DIRTY_Y0 = 50;   // first dirty row in sprite coords
static constexpr int16_t ANIM_DIRTY_Y1 = 215;  // last dirty row  (exclusive)

class DisplayManager {
public:
    void begin(LGFX* lcd);
    void update(uint32_t now, SessionStore* sessions, bool bleConnected);

private:
    LGFX* _lcd = nullptr;
    LGFX_Sprite* _canvas = nullptr;  // Animation-zone back buffer (240×ANIM_H) — flicker-free push

    ClawdAnimation _clawdAnim;  // Handles all 6 session states

    SessionState _currentState    = SessionState::DISCONNECTED;
    SessionState _lastFooterState = SessionState::DISCONNECTED;

    // Tracks the last full-screen idle/disconnected draw so we only repaint on
    // transitions — same pattern as footer, avoids per-frame fillScreen flicker.
    enum class IdleScreen { NONE, WAITING_BLE, NO_SESSIONS };
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
    void drawNoSessions();
};
