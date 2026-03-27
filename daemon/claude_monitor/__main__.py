"""Entry point: python -m claude_monitor"""

import asyncio
import logging
import signal
import sys

from .config import Config
from .daemon import ClaudeMonitorDaemon


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = Config.from_args()
    daemon = ClaudeMonitorDaemon(config)

    loop = asyncio.new_event_loop()

    # Graceful shutdown on SIGINT/SIGTERM
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: loop.stop())

    try:
        loop.run_until_complete(daemon.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
        logging.info("Claude Monitor stopped.")


if __name__ == "__main__":
    main()
