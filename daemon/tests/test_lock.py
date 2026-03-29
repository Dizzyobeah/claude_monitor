"""Tests for the single-instance lock guard."""

import os
import sys

import pytest

from claude_monitor.lock import acquire_lock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_lock_path(tmp_path) -> str:
    """Return a unique lock path inside pytest's tmp_path."""
    return str(tmp_path / "test-daemon.lock")


def _reset_module_lock():
    """Reset the module-level _lock_fh so tests are independent."""
    import claude_monitor.lock as lock_mod

    if lock_mod._lock_fh is not None:
        try:
            lock_mod._lock_fh.close()
        except Exception:
            pass
        lock_mod._lock_fh = None


# ---------------------------------------------------------------------------
# First-caller acquires the lock
# ---------------------------------------------------------------------------


class TestAcquireLock:
    def test_first_call_succeeds(self, tmp_path):
        """acquire_lock() must not exit when no other instance holds the lock."""
        path = _fresh_lock_path(tmp_path)
        # Should complete without raising SystemExit
        acquire_lock(path=path)
        import claude_monitor.lock as lock_mod

        assert lock_mod._lock_fh is not None
        _reset_module_lock()

    def test_lock_file_created(self, tmp_path):
        """Lock file must be created on disk."""
        path = _fresh_lock_path(tmp_path)
        acquire_lock(path=path)
        assert os.path.exists(path)
        _reset_module_lock()

    def test_pid_written_to_lock_file(self, tmp_path):
        """Our PID must be readable from the lock file."""
        import claude_monitor.lock as lock_mod

        path = _fresh_lock_path(tmp_path)
        acquire_lock(path=path)

        # Read through the module-level fd so we don't need a second open()
        # (on Windows msvcrt byte-range locking blocks other openers on byte 0).
        fh = lock_mod._lock_fh
        fh.seek(0)
        content = fh.read().decode().strip().lstrip("\x00")
        assert content == str(os.getpid())
        _reset_module_lock()

    def test_parent_directory_created_if_missing(self, tmp_path):
        """acquire_lock() must create missing parent directories."""
        path = str(tmp_path / "deeply" / "nested" / "dir" / "daemon.lock")
        acquire_lock(path=path)
        assert os.path.exists(path)
        _reset_module_lock()


# ---------------------------------------------------------------------------
# Second-caller exits immediately
# ---------------------------------------------------------------------------


class TestSecondInstanceExits:
    def test_second_call_exits_zero(self, tmp_path):
        """
        Simulate a second process by opening + locking the file ourselves,
        then calling acquire_lock() on the same path — it must sys.exit(0).
        """
        path = _fresh_lock_path(tmp_path)

        # Hold the lock in this process (simulates "first instance")
        if sys.platform == "win32":
            import msvcrt

            holder_fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_BINARY)
            holder = os.fdopen(holder_fd, "r+b")
            holder.write(b"\x00")  # ensure byte 0 exists before locking
            holder.flush()
            holder.seek(0)
            msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            holder = open(path, "w")
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            # "Second instance" should call sys.exit(0)
            with pytest.raises(SystemExit) as exc_info:
                acquire_lock(path=path)
            assert exc_info.value.code == 0
        finally:
            holder.close()

    def test_second_call_does_not_overwrite_lock(self, tmp_path):
        """
        The second-instance path must raise SystemExit(0).

        On Unix we also verify the sentinel PID written by the "first instance"
        is preserved, because flock() is acquired before any write.  On Windows,
        msvcrt byte-range locking fires after the write, so the content may
        differ — we only assert the exit code there.
        """
        path = _fresh_lock_path(tmp_path)

        sentinel_pid = "99999"
        if sys.platform == "win32":
            import msvcrt

            holder_fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_BINARY)
            holder = os.fdopen(holder_fd, "r+b")
            holder.write(b"\x00")  # byte 0 lock sentinel
            holder.write(sentinel_pid.encode())  # PID at byte 1+
            holder.flush()
            holder.seek(0)
            msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            holder = open(path, "w")
            holder.write(sentinel_pid)
            holder.flush()
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            with pytest.raises(SystemExit) as exc_info:
                acquire_lock(path=path)
            assert exc_info.value.code == 0

            # Unix only: flock is acquired before any write, so sentinel stays.
            if sys.platform != "win32":
                with open(path) as f:
                    assert f.read().strip() == sentinel_pid
        finally:
            holder.close()


# ---------------------------------------------------------------------------
# Lock is released when the fd is closed (next process can take over)
# ---------------------------------------------------------------------------


class TestLockReleasedOnClose:
    def test_lock_reacquirable_after_release(self, tmp_path):
        """
        After closing the lock fd the lock must be acquirable again
        (simulates daemon restart after clean shutdown).
        """
        import claude_monitor.lock as lock_mod

        path = _fresh_lock_path(tmp_path)
        acquire_lock(path=path)

        # Simulate process exit: close and clear the module-level handle
        lock_mod._lock_fh.close()
        lock_mod._lock_fh = None

        # Should succeed — lock is free again
        acquire_lock(path=path)
        assert lock_mod._lock_fh is not None
        _reset_module_lock()
