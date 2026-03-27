#pragma once

#include "serial_protocol.h"

static constexpr uint8_t MAX_SESSIONS = 8;
static constexpr uint32_t CAROUSEL_INTERVAL_MS = 5000;
static constexpr uint32_t STALE_TIMEOUT_MS = 600000; // 10 minutes

struct Session {
    char sid[6]    = {0};
    char label[21] = {0};
    SessionState state = SessionState::IDLE;
    uint32_t lastUpdate = 0;
    bool active = false;
};

class SessionStore {
public:
    void upsert(const char* sid, SessionState state, const char* label);
    void remove(const char* sid);
    void pruneStale(uint32_t now);

    Session* getDisplayed();          // Currently shown session
    Session* getPriority();           // Highest priority session needing attention
    const char* getDisplayedSid();

    void cycleNext();
    void update(uint32_t now);        // Auto-carousel logic

    uint8_t count() const { return _count; }
    uint8_t displayIndex() const { return _displayIdx; }
    bool stateChanged() const { return _stateChanged; }
    void clearStateChanged() { _stateChanged = false; }

private:
    Session _sessions[MAX_SESSIONS];
    uint8_t _count = 0;
    uint8_t _displayIdx = 0;
    uint32_t _lastCarousel = 0;
    bool _stateChanged = true;

    int findBySid(const char* sid);
    int findEmpty();
    void recount();
};
