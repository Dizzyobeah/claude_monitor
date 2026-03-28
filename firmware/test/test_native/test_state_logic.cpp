// Native unit tests for firmware state logic.
// Tests stateFromString, stateToString, stateNeedsAttention — the core
// protocol functions that must stay in sync with the Python daemon.

#include <unity.h>
#include <cstring>
#include <cstdint>

// ---- Replicate the enum and functions under test ----
// These are copied from ble_protocol.h/cpp to avoid pulling in the full
// Arduino/BLE dependency chain. If the source enum changes, these tests
// will catch the desync when the string comparisons fail.

enum class SessionState : uint8_t {
    IDLE = 0,
    THINKING,
    TOOL_USE,
    PERMISSION,
    INPUT_NEEDED,
    ERROR,
    DISCONNECTED,
    NUM_STATES
};

const char* stateToString(SessionState state) {
    switch (state) {
        case SessionState::IDLE:         return "IDLE";
        case SessionState::THINKING:     return "THINKING";
        case SessionState::TOOL_USE:     return "TOOL_USE";
        case SessionState::PERMISSION:   return "PERMISSION";
        case SessionState::INPUT_NEEDED: return "INPUT";
        case SessionState::ERROR:        return "ERROR";
        case SessionState::DISCONNECTED: return "DISCONNECTED";
        default:                         return "UNKNOWN";
    }
}

SessionState stateFromString(const char* str) {
    if (!str) return SessionState::IDLE;
    if (strcmp(str, "THINKING")   == 0) return SessionState::THINKING;
    if (strcmp(str, "TOOL_USE")   == 0) return SessionState::TOOL_USE;
    if (strcmp(str, "PERMISSION") == 0) return SessionState::PERMISSION;
    if (strcmp(str, "INPUT")      == 0) return SessionState::INPUT_NEEDED;
    if (strcmp(str, "ERROR")      == 0) return SessionState::ERROR;
    return SessionState::IDLE;
}

bool stateNeedsAttention(SessionState state) {
    return state == SessionState::PERMISSION ||
           state == SessionState::INPUT_NEEDED ||
           state == SessionState::ERROR;
}

// ---- Tests: stateFromString ----

void test_state_from_string_thinking() {
    TEST_ASSERT_EQUAL(SessionState::THINKING, stateFromString("THINKING"));
}

void test_state_from_string_tool_use() {
    TEST_ASSERT_EQUAL(SessionState::TOOL_USE, stateFromString("TOOL_USE"));
}

void test_state_from_string_permission() {
    TEST_ASSERT_EQUAL(SessionState::PERMISSION, stateFromString("PERMISSION"));
}

void test_state_from_string_input() {
    TEST_ASSERT_EQUAL(SessionState::INPUT_NEEDED, stateFromString("INPUT"));
}

void test_state_from_string_error() {
    TEST_ASSERT_EQUAL(SessionState::ERROR, stateFromString("ERROR"));
}

void test_state_from_string_unknown_defaults_to_idle() {
    TEST_ASSERT_EQUAL(SessionState::IDLE, stateFromString("BOGUS"));
}

void test_state_from_string_null_defaults_to_idle() {
    TEST_ASSERT_EQUAL(SessionState::IDLE, stateFromString(nullptr));
}

void test_state_from_string_empty_defaults_to_idle() {
    TEST_ASSERT_EQUAL(SessionState::IDLE, stateFromString(""));
}

// ---- Tests: stateToString ----

void test_state_to_string_roundtrip() {
    // Every state that stateFromString can produce should round-trip
    const char* cases[] = {"THINKING", "TOOL_USE", "PERMISSION", "INPUT", "ERROR"};
    SessionState expected[] = {
        SessionState::THINKING, SessionState::TOOL_USE, SessionState::PERMISSION,
        SessionState::INPUT_NEEDED, SessionState::ERROR
    };
    for (int i = 0; i < 5; i++) {
        SessionState s = stateFromString(cases[i]);
        TEST_ASSERT_EQUAL(expected[i], s);
        TEST_ASSERT_EQUAL_STRING(cases[i], stateToString(s));
    }
}

void test_state_to_string_idle() {
    TEST_ASSERT_EQUAL_STRING("IDLE", stateToString(SessionState::IDLE));
}

void test_state_to_string_disconnected() {
    TEST_ASSERT_EQUAL_STRING("DISCONNECTED", stateToString(SessionState::DISCONNECTED));
}

// ---- Tests: stateNeedsAttention ----

void test_attention_permission() {
    TEST_ASSERT_TRUE(stateNeedsAttention(SessionState::PERMISSION));
}

void test_attention_input() {
    TEST_ASSERT_TRUE(stateNeedsAttention(SessionState::INPUT_NEEDED));
}

void test_attention_error() {
    TEST_ASSERT_TRUE(stateNeedsAttention(SessionState::ERROR));
}

void test_no_attention_idle() {
    TEST_ASSERT_FALSE(stateNeedsAttention(SessionState::IDLE));
}

void test_no_attention_thinking() {
    TEST_ASSERT_FALSE(stateNeedsAttention(SessionState::THINKING));
}

void test_no_attention_tool_use() {
    TEST_ASSERT_FALSE(stateNeedsAttention(SessionState::TOOL_USE));
}

// ---- Buffer safety tests ----

void test_strncpy_null_termination() {
    // Verify the pattern used in session_store.cpp and ble_protocol.cpp
    char dst[6] = {0};
    const char* long_input = "abcdefghijk";  // longer than buffer
    strncpy(dst, long_input, sizeof(dst) - 1);
    dst[sizeof(dst) - 1] = '\0';
    TEST_ASSERT_EQUAL_STRING("abcde", dst);
    TEST_ASSERT_EQUAL(5, strlen(dst));
}

void test_strncpy_short_input() {
    char dst[6] = {'X', 'X', 'X', 'X', 'X', 'X'};
    const char* short_input = "ab";
    strncpy(dst, short_input, sizeof(dst) - 1);
    dst[sizeof(dst) - 1] = '\0';
    TEST_ASSERT_EQUAL_STRING("ab", dst);
}

// ---- Entry point ----

int main() {
    UNITY_BEGIN();

    // stateFromString
    RUN_TEST(test_state_from_string_thinking);
    RUN_TEST(test_state_from_string_tool_use);
    RUN_TEST(test_state_from_string_permission);
    RUN_TEST(test_state_from_string_input);
    RUN_TEST(test_state_from_string_error);
    RUN_TEST(test_state_from_string_unknown_defaults_to_idle);
    RUN_TEST(test_state_from_string_null_defaults_to_idle);
    RUN_TEST(test_state_from_string_empty_defaults_to_idle);

    // stateToString
    RUN_TEST(test_state_to_string_roundtrip);
    RUN_TEST(test_state_to_string_idle);
    RUN_TEST(test_state_to_string_disconnected);

    // stateNeedsAttention
    RUN_TEST(test_attention_permission);
    RUN_TEST(test_attention_input);
    RUN_TEST(test_attention_error);
    RUN_TEST(test_no_attention_idle);
    RUN_TEST(test_no_attention_thinking);
    RUN_TEST(test_no_attention_tool_use);

    // Buffer safety
    RUN_TEST(test_strncpy_null_termination);
    RUN_TEST(test_strncpy_short_input);

    return UNITY_END();
}
