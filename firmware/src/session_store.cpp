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
            // If the display was pointing at this (now-dead) slot, move on —
            // same pattern as remove().
            if (_displayIdx == (uint8_t)i) {
                cycleNext();
            }
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
    // Return the most recently updated session that needs attention,
    // not just the first one in slot order.
    int bestIdx = -1;
    uint32_t bestTime = 0;
    for (int i = 0; i < MAX_SESSIONS; i++) {
        if (_sessions[i].active && stateNeedsAttention(_sessions[i].state)) {
            if (bestIdx < 0 || _sessions[i].lastUpdate > bestTime) {
                bestIdx = i;
                bestTime = _sessions[i].lastUpdate;
            }
        }
    }
    return bestIdx >= 0 ? &_sessions[bestIdx] : nullptr;
}

const char* SessionStore::getDisplayedSid() {
    Session* s = getDisplayed();
    return s ? s->sid : "";
}

uint8_t SessionStore::displayRank() const {
    // Count how many active sessions come before _displayIdx in slot order.
    // This gives the 0-based rank used for dot indicators, independent of
    // how sparse the backing array is.
    uint8_t rank = 0;
    for (int i = 0; i < MAX_SESSIONS; i++) {
        if (i == (int)_displayIdx) break;
        if (_sessions[i].active) rank++;
    }
    return rank;
}

void SessionStore::cycleNext() {
    if (_count <= 1) return;
    int start = _displayIdx;
    uint8_t steps = 0;
    do {
        _displayIdx = (_displayIdx + 1) % MAX_SESSIONS;
        if (++steps > MAX_SESSIONS) {
            recount();  // _count was stale — recover gracefully
            return;
        }
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
    if (now - _lastPrune > 30000) {
        _lastPrune = now;
        pruneStale(now);
    }
}
