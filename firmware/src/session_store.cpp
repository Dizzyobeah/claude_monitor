#include "session_store.h"
#include <string.h>

int SessionStore::findBySid(const char* sid) {
    for (int i = 0; i < MAX_SESSIONS; i++) {
        if (_sessions[i].active && strcmp(_sessions[i].sid, sid) == 0) return i;
    }
    return -1;
}

int SessionStore::findEmpty() {
    for (int i = 0; i < MAX_SESSIONS; i++) {
        if (!_sessions[i].active) return i;
    }
    return -1;
}

void SessionStore::recount() {
    _count = 0;
    for (int i = 0; i < MAX_SESSIONS; i++) {
        if (_sessions[i].active) _count++;
    }
}

void SessionStore::upsert(const char* sid, SessionState state, const char* label) {
    int idx = findBySid(sid);
    if (idx < 0) {
        idx = findEmpty();
        if (idx < 0) return; // Full, ignore
        _sessions[idx].active = true;
        strncpy(_sessions[idx].sid, sid, 5);
        _sessions[idx].sid[5] = '\0';
        recount();
    }

    if (_sessions[idx].state != state) {
        _stateChanged = true;
    }

    _sessions[idx].state = state;
    _sessions[idx].lastUpdate = millis();
    if (label && label[0]) {
        strncpy(_sessions[idx].label, label, 20);
        _sessions[idx].label[20] = '\0';
    }

    // Auto-switch to sessions needing attention
    if (stateNeedsAttention(state)) {
        _displayIdx = idx;
    }
}

void SessionStore::remove(const char* sid) {
    int idx = findBySid(sid);
    if (idx < 0) return;
    _sessions[idx] = Session{};
    recount();
    _stateChanged = true;
    if (_displayIdx == idx) {
        cycleNext();
    }
}

void SessionStore::pruneStale(uint32_t now) {
    for (int i = 0; i < MAX_SESSIONS; i++) {
        if (_sessions[i].active && (now - _sessions[i].lastUpdate) > STALE_TIMEOUT_MS) {
            _sessions[i] = Session{};
            _stateChanged = true;
        }
    }
    recount();
}

Session* SessionStore::getDisplayed() {
    if (_count == 0) return nullptr;
    if (_displayIdx < MAX_SESSIONS && _sessions[_displayIdx].active) {
        return &_sessions[_displayIdx];
    }
    // Find first active
    for (int i = 0; i < MAX_SESSIONS; i++) {
        if (_sessions[i].active) {
            _displayIdx = i;
            return &_sessions[i];
        }
    }
    return nullptr;
}

Session* SessionStore::getPriority() {
    for (int i = 0; i < MAX_SESSIONS; i++) {
        if (_sessions[i].active && stateNeedsAttention(_sessions[i].state)) {
            return &_sessions[i];
        }
    }
    return nullptr;
}

const char* SessionStore::getDisplayedSid() {
    Session* s = getDisplayed();
    return s ? s->sid : "";
}

void SessionStore::cycleNext() {
    if (_count <= 1) return;
    int start = _displayIdx;
    do {
        _displayIdx = (_displayIdx + 1) % MAX_SESSIONS;
    } while (!_sessions[_displayIdx].active && _displayIdx != start);
    _stateChanged = true;
}

void SessionStore::update(uint32_t now) {
    // Auto-carousel: cycle sessions every CAROUSEL_INTERVAL_MS
    // But don't carousel away from sessions needing attention
    if (_count > 1 && (now - _lastCarousel) > CAROUSEL_INTERVAL_MS) {
        _lastCarousel = now;
        Session* current = getDisplayed();
        if (current && !stateNeedsAttention(current->state)) {
            // Check if any session needs attention first
            Session* priority = getPriority();
            if (priority) {
                int idx = findBySid(priority->sid);
                if (idx >= 0 && idx != _displayIdx) {
                    _displayIdx = idx;
                    _stateChanged = true;
                }
            } else {
                cycleNext();
            }
        }
    }

    // Prune stale sessions every 30 seconds
    static uint32_t lastPrune = 0;
    if (now - lastPrune > 30000) {
        lastPrune = now;
        pruneStale(now);
    }
}
