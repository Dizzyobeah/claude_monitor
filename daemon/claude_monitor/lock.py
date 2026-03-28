"""
Single-instance lock for the Claude Monitor daemon.

Acquires an exclusive OS-level lock on a well-known file so that any
second `uv run claude-monitor` process that races in during auto-start
exits immediately — before touching the port, BLE stack, or anything else.

Usage (called at the very top of main()):

    from .lock import acquire_lock
    acquire_lock()          # exits(0) if another instance already holds it

The lock is released automatically when the process exits (OS closes the fd).
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

# Lock file lives in the XDG state dir on Linux/macOS;
# %USERPROFILE%\.local\state\claude-monitor\ on Windows (same path logic).
_LOCK_DIR = os.path.join(os.path.expanduser("~"), ".local", "state", "claude-monitor")
_LOCK_PATH = os.path.join(_LOCK_DIR, "daemon.lock")


def _lock_path() -> str:
    """Return the lock file path (also used by tests to override)."""
    return _LOCK_PATH


# Module-level file handle — must stay open for the lifetime of the process.
_lock_fh = None


def acquire_lock(path: str | None = None) -> None:
    """
    Acquire an exclusive lock on *path* (default: ``_LOCK_PATH``).

    If the lock is already held by another process, log a message and
    call ``sys.exit(0)`` — the daemon is already running, nothing to do.

    Raises ``OSError`` only for unexpected I/O errors (disk full, etc.).
    """
    global _lock_fh

    target = path or _lock_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)

    if sys.platform == "win32":
        _acquire_lock_windows(target)
    else:
        _acquire_lock_unix(target)


def _acquire_lock_unix(target: str) -> None:
    """Unix: flock(LOCK_EX|LOCK_NB) on the lock file."""
    global _lock_fh

    import fcntl

    # O_CREAT|O_RDWR: create if absent, never truncate.
    fd = os.open(target, os.O_CREAT | os.O_RDWR)
    fh = os.fdopen(fd, "r+b")  # noqa: WPS515

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        _exit_already_running(target)

    # Write our PID after acquiring (flock doesn't restrict I/O).
    fh.seek(0)
    fh.write(str(os.getpid()).encode())
    fh.truncate()
    fh.flush()

    _lock_fh = fh
    log.debug("Lock acquired: %s (pid %d)", target, os.getpid())


def _acquire_lock_windows(target: str) -> None:
    """
    Windows: msvcrt.locking(LK_NBLCK) on byte 0 of the lock file.

    msvcrt byte-range locking prevents even the lock holder from
    reading/writing the locked bytes.  So we:
      1. Open the file (create if absent; do NOT truncate — avoid stomping
         on a live daemon's PID).
      2. Ensure the file is at least 1 byte long (pad with '\\0' if new/empty).
      3. Attempt LK_NBLCK on byte 0 — exits(0) if already locked.
      4. Only after we own the lock: seek past byte 0, write the PID.
    """
    global _lock_fh

    import msvcrt

    # O_CREAT|O_RDWR: create if absent, never truncate.
    fd = os.open(target, os.O_CREAT | os.O_RDWR | os.O_BINARY)
    fh = os.fdopen(fd, "r+b")  # noqa: WPS515

    try:
        # Ensure at least 1 byte exists so locking(…, 1) has something to lock.
        current_size = os.fstat(fh.fileno()).st_size
        if current_size == 0:
            fh.write(b"\x00")
            fh.flush()

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    except OSError:
        try:
            fh.close()
        except OSError:
            pass
        _exit_already_running(target)
        return  # unreachable; satisfies type checkers

    # We own the lock.  Write our PID starting at byte 1 so we never
    # touch the locked byte 0.  Readers should strip the leading null.
    pid_bytes = str(os.getpid()).encode()
    fh.seek(1)
    fh.write(pid_bytes)
    fh.flush()

    _lock_fh = fh
    log.debug("Lock acquired (windows): %s (pid %d)", target, os.getpid())


def _exit_already_running(target: str) -> None:
    log.info(
        "Claude Monitor daemon is already running (lock held: %s). Exiting.", target
    )
    sys.exit(0)
