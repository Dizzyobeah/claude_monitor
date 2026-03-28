"""Configuration for Claude Monitor daemon."""

import argparse
import dataclasses


@dataclasses.dataclass
class Config:
    http_port: int = 7483  # Hook events from Claude Code
    stale_timeout: int = 600  # seconds
    verbose: bool = False

    @classmethod
    def from_args(cls) -> "Config":
        parser = argparse.ArgumentParser(description="Claude Monitor daemon")
        parser.add_argument(
            "--http-port",
            type=int,
            default=7483,
            help="HTTP port for hook events (default: 7483)",
        )
        parser.add_argument(
            "--stale-timeout",
            type=int,
            default=600,
            metavar="SECONDS",
            help="Remove sessions with no updates after this many seconds (default: 600)",
        )
        parser.add_argument(
            "--verbose",
            "-v",
            action="store_true",
            help="Enable DEBUG-level logging",
        )
        args = parser.parse_args()

        return cls(
            http_port=args.http_port,
            stale_timeout=args.stale_timeout,
            verbose=args.verbose,
        )
