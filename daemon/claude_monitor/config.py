"""Configuration for Claude Monitor daemon."""

import argparse
import dataclasses


@dataclasses.dataclass
class Config:
    http_port: int = 7483       # Hook events from Claude Code
    stale_timeout: int = 600    # seconds

    @classmethod
    def from_args(cls) -> "Config":
        parser = argparse.ArgumentParser(description="Claude Monitor daemon")
        parser.add_argument(
            "--http-port",
            type=int, default=7483,
            help="HTTP port for hook events (default: 7483)",
        )
        args = parser.parse_args()

        return cls(http_port=args.http_port)
