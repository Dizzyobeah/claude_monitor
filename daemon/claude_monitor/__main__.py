"""Entry point: python -m claude_monitor"""

import asyncio
import json as json_mod
import logging
import os
import signal
import sys
import time
from typing import Any

from .config import Config
from .daemon import ClaudeMonitorDaemon
from .lock import STATE_DIR, acquire_lock


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for machine-parseable output."""

    def format(self, record: logging.LogRecord) -> str:
        return json_mod.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        })

log = logging.getLogger(__name__)


def _make_exception_handler() -> Any:
    """Return an asyncio exception handler that suppresses known shutdown noise.

    Two harmless error classes are demoted from ERROR to DEBUG:

    * OSError WinError 64 ("The specified network name is no longer available"):
      Windows IOCP invalidates the socket handle when the process is killed hard
      (e.g. closing the console window) or when a network adapter resets.

    * TypeError "'NoneType' object is not callable" from aiohttp web_protocol:
      In-flight RequestHandler tasks lose their factory reference when the
      AppRunner is torn down mid-accept during an abrupt shutdown.
    """

    def handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        msg = context.get("message", "")
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 64:
            log.debug("Suppressed WinError 64 (socket closed abruptly): %s", exc)
            return
        if isinstance(exc, TypeError) and "'NoneType' object is not callable" in str(
            exc
        ):
            log.debug("Suppressed aiohttp shutdown noise: %s", exc)
            return
        if "Accept failed on a socket" in msg and isinstance(exc, OSError):
            log.debug("Suppressed socket accept failure: %s", exc)
            return
        loop.default_exception_handler(context)

    return handler


def main() -> None:
    config = Config.from_args()

    # Handle subcommands that don't need the daemon
    if config.subcommand == "status":
        from .cli import status

        status(f"http://localhost:{config.http_port}")
        return

    if config.subcommand == "ota":
        from .cli import ota

        ota(config.ota_firmware, f"http://localhost:{config.http_port}")
        return

    if config.subcommand == "device":
        from .cli import device_forget, device_show

        if config.device_subcommand == "show":
            device_show()
        elif config.device_subcommand == "forget":
            device_forget()
        else:
            print("Usage: claude-monitor device [show|forget]", file=sys.stderr)
            sys.exit(1)
        return

    # Acquire a single-instance lock before doing anything else.
    # If another daemon process is already running this exits(0) immediately.
    acquire_lock()

    # Log to ~/.local/state/claude-monitor/ with restricted permissions
    # instead of world-readable /tmp to avoid leaking session activity.
    os.makedirs(STATE_DIR, exist_ok=True)
    log_path = os.path.join(STATE_DIR, "daemon.log")
    if config.json_log:
        fmt: logging.Formatter = _JsonFormatter()
    else:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
        )

    log_handler = logging.FileHandler(log_path)
    log_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    # Restrict log file to owner-only read/write
    try:
        os.chmod(log_path, 0o600)
    except OSError:
        pass

    logging.basicConfig(
        level=logging.DEBUG if config.verbose else logging.INFO,
        handlers=[log_handler, stream_handler],
    )
    daemon = ClaudeMonitorDaemon(config)

    loop = asyncio.new_event_loop()
    loop.set_exception_handler(_make_exception_handler())

    # Graceful shutdown on SIGINT/SIGTERM
    # add_signal_handler is Unix-only; on Windows fall back to KeyboardInterrupt
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: loop.stop())

        # SIGHUP: graceful reload — reset session tracker and force BLE resync
        # without dropping the BLE connection or restarting the HTTP server.
        def _handle_sighup() -> None:
            log.info("SIGHUP received — reloading session state")
            daemon.tracker.sessions.clear()
            daemon.tracker.ever_had_session = False
            daemon._force_resync = True

        loop.add_signal_handler(signal.SIGHUP, _handle_sighup)

    try:
        loop.run_until_complete(daemon.run())
    except (KeyboardInterrupt, RuntimeError):
        # KeyboardInterrupt: Ctrl-C on Windows (no add_signal_handler).
        # RuntimeError: can occur if a Unix signal handler calls loop.stop()
        # while run_until_complete() is running (kept for safety, but the
        # normal auto-exit path now cancels tasks cooperatively instead).
        pass
    finally:
        # Cancel all pending tasks so coroutines can clean up (e.g. runner.cleanup).
        # BLE cleanup (bleak/CoreBluetooth) can hang indefinitely during a
        # disconnect cycle, so we impose a hard timeout — if tasks don't finish
        # within 5 seconds, we abandon them and close the loop anyway.
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                for task in pending:
                    task.cancel()
                try:
                    loop.run_until_complete(
                        asyncio.wait_for(
                            asyncio.gather(*pending, return_exceptions=True),
                            timeout=5.0,
                        )
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    log.warning("Cleanup timed out after 5s — forcing shutdown")
        except RuntimeError:
            # Loop already closed or no running loop — nothing to clean up
            pass
        loop.close()
        logging.info("Claude Monitor stopped.")


if __name__ == "__main__":
    main()
