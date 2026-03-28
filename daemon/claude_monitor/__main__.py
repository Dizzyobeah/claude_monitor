"""Entry point: python -m claude_monitor"""

import asyncio
import logging
import signal
import sys

from .config import Config
from .daemon import ClaudeMonitorDaemon
from .lock import acquire_lock

log = logging.getLogger(__name__)


def _make_exception_handler():
    """Return an asyncio exception handler that suppresses known shutdown noise.

    Two harmless error classes are demoted from ERROR to DEBUG:

    * OSError WinError 64 ("The specified network name is no longer available"):
      Windows IOCP invalidates the socket handle when the process is killed hard
      (e.g. closing the console window) or when a network adapter resets.

    * TypeError "'NoneType' object is not callable" from aiohttp web_protocol:
      In-flight RequestHandler tasks lose their factory reference when the
      AppRunner is torn down mid-accept during an abrupt shutdown.
    """

    def handler(loop, context):
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
    # Acquire a single-instance lock before doing anything else.
    # If another daemon process is already running this exits(0) immediately.
    acquire_lock()

    config = Config.from_args()

    logging.basicConfig(
        level=logging.DEBUG if config.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    daemon = ClaudeMonitorDaemon(config)

    loop = asyncio.new_event_loop()
    loop.set_exception_handler(_make_exception_handler())

    # Graceful shutdown on SIGINT/SIGTERM
    # add_signal_handler is Unix-only; on Windows fall back to KeyboardInterrupt
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: loop.stop())

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
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        logging.info("Claude Monitor stopped.")


if __name__ == "__main__":
    main()
