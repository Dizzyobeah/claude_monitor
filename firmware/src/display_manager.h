#pragma once

#include "board/board_config.h"
#include "session_store.h"
#include "animation/animation.h"
#include "animation/idle_anim.h"
#include "animation/thinking_anim.h"
#include "animation/tool_use_anim.h"
#include "animation/permission_anim.h"
#include "animation/input_anim.h"
#include "animation/error_anim.h"

// Layout constants
static constexpr int16_t HEADER_H  = 40;
static constexpr int16_t ANIM_H    = 200;
static constexpr int16_t FOOTER_H  = 80;  // SCREEN_H - HEADER_H - ANIM_H

class DisplayManager {
public:
    void begin(LGFX* lcd);
    void update(uint32_t now, SessionStore* sessions, bool bleConnected);

private:
    LGFX* _lcd = nullptr;
    LGFX_Sprite _canvas;

    // Animation instances (one per state)
    IdleAnimation       _idleAnim;
    ThinkingAnimation   _thinkingAnim;
    ToolUseAnimation    _toolUseAnim;
    PermissionAnimation _permissionAnim;
    InputAnimation      _inputAnim;
    ErrorAnimation      _errorAnim;

    SessionState _currentState = SessionState::DISCONNECTED;
    uint32_t _lastFrameTime = 0;

    Animation* animForState(SessionState state);
    void drawHeader(Session* session, uint8_t count, uint8_t displayIdx, bool bleConnected);
    void drawFooter(Session* session);
    void drawWaitingForBle();
    void drawNoSessions();
};
