"""Tests for SessionTracker: state machine, priority ordering, pruning, removal."""

import time

from claude_monitor.session_tracker import (
    SessionTracker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tracker() -> SessionTracker:
    return SessionTracker(stale_timeout=60)


def session_states(tracker: SessionTracker) -> dict[str, str]:
    return {sid: info.state for sid, info in tracker.sessions.items()}


# ---------------------------------------------------------------------------
# Basic state transitions
# ---------------------------------------------------------------------------


class TestUpdateSession:
    def test_session_created_on_first_event(self):
        t = make_tracker()
        t.update_session("abc123", "SessionStart", {})
        assert "abc123" in t.sessions
        assert t.sessions["abc123"].state == "INPUT"

    def test_state_transitions(self):
        t = make_tracker()
        events = [
            ("UserPromptSubmit", "THINKING"),
            ("PreToolUse", "TOOL_USE"),
            ("PostToolUse", "THINKING"),
            ("SubagentStart", "THINKING"),
            ("SubagentStop", "THINKING"),
            ("Stop", "INPUT"),
            ("PermissionRequest", "PERMISSION"),
            ("StopFailure", "ERROR"),
            ("PostToolUseFailure", "ERROR"),
        ]
        for event, expected_state in events:
            t.update_session("s1", event, {})
            assert t.sessions["s1"].state == expected_state, (
                f"Failed for event {event!r}"
            )

    def test_notification_permission(self):
        t = make_tracker()
        t.update_session(
            "s1", "Notification", {"notification_type": "permission_prompt"}
        )
        assert t.sessions["s1"].state == "PERMISSION"

    def test_notification_idle(self):
        t = make_tracker()
        t.update_session("s1", "Notification", {"notification_type": "idle_prompt"})
        assert t.sessions["s1"].state == "INPUT"

    def test_unknown_event_ignored(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "BogusEvent", {})
        assert t.sessions["s1"].state == "INPUT"

    def test_unknown_notification_type_ignored(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "Notification", {"notification_type": "bogus_type"})
        assert t.sessions["s1"].state == "INPUT"

    def test_label_extracted_from_cwd(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {"cwd": "/home/user/myproject"})
        assert t.sessions["s1"].label == "myproject"

    def test_label_truncated_to_20_chars(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {"cwd": "/home/user/" + "a" * 30})
        assert len(t.sessions["s1"].label) == 20

    def test_label_defaults_to_unknown_when_no_cwd(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        assert t.sessions["s1"].label == "unknown"

    def test_label_for_root_cwd(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {"cwd": "/"})
        # os.path.basename("/") returns "" — now falls back to "unknown"
        assert t.sessions["s1"].label == "unknown"

    def test_label_exactly_20_chars_not_truncated(self):
        t = make_tracker()
        name = "a" * 20
        t.update_session("s1", "SessionStart", {"cwd": f"/home/user/{name}"})
        assert t.sessions["s1"].label == name
        assert len(t.sessions["s1"].label) == 20

    def test_tty_and_ppid_stored_on_first_event(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {}, tty="/dev/pts/1", ppid="1234")
        assert t.sessions["s1"].tty == "/dev/pts/1"
        assert t.sessions["s1"].ppid == "1234"

    def test_tty_and_ppid_not_overwritten_once_set(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {}, tty="/dev/pts/1", ppid="1234")
        t.update_session("s1", "UserPromptSubmit", {}, tty="/dev/pts/9", ppid="9999")
        # Original values preserved
        assert t.sessions["s1"].tty == "/dev/pts/1"
        assert t.sessions["s1"].ppid == "1234"

    def test_tty_and_ppid_set_on_later_event_if_initially_empty(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "UserPromptSubmit", {}, tty="/dev/pts/5", ppid="555")
        assert t.sessions["s1"].tty == "/dev/pts/5"
        assert t.sessions["s1"].ppid == "555"


# ---------------------------------------------------------------------------
# Session removal
# ---------------------------------------------------------------------------


class TestSessionEnd:
    def test_session_end_keeps_session_in_input_during_grace_period(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "SessionEnd", {})
        # Session still visible during grace period
        assert "s1" in t.sessions
        assert t.sessions["s1"].state == "INPUT"

    def test_session_end_does_not_record_removed_id_immediately(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "SessionEnd", {})
        assert t.pop_removed_ids() == []

    def test_session_end_removes_after_grace_period_expires(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "SessionEnd", {})
        # Fast-forward the scheduled removal time
        t._pending_removal["s1"] = time.time() - 1
        t.prune_stale()
        assert "s1" not in t.sessions
        assert "s1" in t.pop_removed_ids()

    def test_session_end_cancelled_by_new_event(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "SessionEnd", {})
        assert "s1" in t._pending_removal
        # Session comes back (e.g. /undo or session switch)
        t.update_session("s1", "SessionStart", {})
        assert "s1" not in t._pending_removal
        # Should still be present after prune
        t.prune_stale()
        assert "s1" in t.sessions

    def test_pop_removed_ids_clears_the_list(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "SessionEnd", {})
        t._pending_removal["s1"] = time.time() - 1
        t.prune_stale()
        t.pop_removed_ids()  # consume
        assert t.pop_removed_ids() == []

    def test_session_end_on_nonexistent_session_is_noop(self):
        t = make_tracker()
        # Should not raise
        t.update_session("ghost", "SessionEnd", {})
        assert t.pop_removed_ids() == []

    def test_multiple_removals_all_recorded_after_grace(self):
        t = make_tracker()
        for sid in ("a", "b", "c"):
            t.update_session(sid, "SessionStart", {})
        for sid in ("a", "b", "c"):
            t.update_session(sid, "SessionEnd", {})
        # Expire all grace periods
        for sid in ("a", "b", "c"):
            t._pending_removal[sid] = time.time() - 1
        t.prune_stale()
        removed = t.pop_removed_ids()
        assert sorted(removed) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# `changed` flag
# ---------------------------------------------------------------------------


class TestChangedFlag:
    def test_new_session_sets_changed(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        assert t.changed is True

    def test_changed_is_consumed_on_read(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        _ = t.changed  # consume
        assert t.changed is False

    def test_same_state_does_not_set_changed(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        _ = t.changed  # consume
        t.update_session("s1", "SessionStart", {})
        assert t.changed is False

    def test_state_change_sets_changed(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        _ = t.changed  # consume
        t.update_session("s1", "UserPromptSubmit", {})
        assert t.changed is True

    def test_session_end_sets_changed_when_state_transitions_to_input(self):
        t = make_tracker()
        t.update_session("s1", "UserPromptSubmit", {})  # THINKING
        _ = t.changed  # consume
        t.update_session("s1", "SessionEnd", {})
        # State changed THINKING -> INPUT
        assert t.changed is True

    def test_session_end_does_not_set_changed_when_already_input(self):
        t = make_tracker()
        t.update_session("s1", "Stop", {})  # INPUT
        _ = t.changed  # consume
        t.update_session("s1", "SessionEnd", {})
        # Already INPUT, no state change
        assert t.changed is False


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


class TestGetOrderedSessions:
    def test_attention_states_sort_first(self):
        t = make_tracker()
        t.update_session("s1", "UserPromptSubmit", {})  # THINKING
        t.update_session("s2", "PermissionRequest", {})  # PERMISSION
        t.update_session("s3", "Stop", {})  # INPUT
        t.update_session("s4", "StopFailure", {})  # ERROR

        ordered = t.get_ordered_sessions()
        # All attention states before THINKING
        attention = {"PERMISSION", "INPUT", "ERROR"}
        first_non_attention = next(
            i for i, s in enumerate(ordered) if s.state not in attention
        )
        for s in ordered[:first_non_attention]:
            assert s.state in attention

    def test_within_same_tier_most_recent_first(self):
        t = make_tracker()
        t.update_session("old", "SessionStart", {})
        t.update_session("new", "SessionStart", {})
        # Force ordering without relying on wall clock resolution
        t.sessions["old"].last_update = 1000.0
        t.sessions["new"].last_update = 2000.0

        ordered = t.get_ordered_sessions()
        assert ordered[0].session_id == "new"
        assert ordered[1].session_id == "old"

    def test_empty_tracker_returns_empty_list(self):
        t = make_tracker()
        assert t.get_ordered_sessions() == []


# ---------------------------------------------------------------------------
# Stale pruning
# ---------------------------------------------------------------------------


class TestPruneStale:
    def test_stale_session_removed(self):
        t = SessionTracker(stale_timeout=1)
        t.update_session("s1", "SessionStart", {})
        # Force last_update to the past
        t.sessions["s1"].last_update = time.time() - 10
        t.prune_stale()
        assert "s1" not in t.sessions

    def test_stale_prune_records_removed_id(self):
        t = SessionTracker(stale_timeout=1)
        t.update_session("s1", "SessionStart", {})
        t.sessions["s1"].last_update = time.time() - 10
        t.prune_stale()
        assert "s1" in t.pop_removed_ids()

    def test_fresh_session_not_pruned(self):
        t = SessionTracker(stale_timeout=600)
        t.update_session("s1", "SessionStart", {})
        t.prune_stale()
        assert "s1" in t.sessions

    def test_stale_sets_changed_flag(self):
        t = SessionTracker(stale_timeout=1)
        t.update_session("s1", "SessionStart", {})
        _ = t.changed  # consume
        t.sessions["s1"].last_update = time.time() - 10
        t.prune_stale()
        assert t.changed is True


# ---------------------------------------------------------------------------
# is_idle / ever_had_session
# ---------------------------------------------------------------------------


class TestIsIdle:
    def test_false_on_cold_start(self):
        """Daemon must not exit before any session has ever been seen."""
        t = make_tracker()
        assert t.is_idle is False

    def test_false_while_session_active(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        assert t.is_idle is False

    def test_false_while_pending_removal(self):
        """Session is in grace period after SessionEnd — not yet truly gone."""
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "SessionEnd", {})
        # sessions dict is empty but _pending_removal still has s1
        assert "s1" not in t.sessions or t._pending_removal
        assert t.is_idle is False

    def test_true_after_last_session_fully_removed(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t.update_session("s1", "SessionEnd", {})
        # Force-expire the grace period
        t._remove_session("s1")
        assert t.is_idle is True

    def test_true_after_stale_prune_removes_last_session(self):
        t = SessionTracker(stale_timeout=1)
        t.update_session("s1", "SessionStart", {})
        t.sessions["s1"].last_update = time.time() - 10
        t.prune_stale()
        assert t.is_idle is True

    def test_ever_had_session_set_on_first_session(self):
        t = make_tracker()
        assert t.ever_had_session is False
        t.update_session("s1", "SessionStart", {})
        assert t.ever_had_session is True

    def test_ever_had_session_not_reset_after_removal(self):
        t = make_tracker()
        t.update_session("s1", "SessionStart", {})
        t._remove_session("s1")
        assert t.ever_had_session is True
