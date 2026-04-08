"""Configuration for Claude Monitor daemon."""

import argparse
import dataclasses


@dataclasses.dataclass
class Config:
    http_port: int = 7483  # Hook events from Claude Code
    stale_timeout: int = 600  # seconds
    verbose: bool = False
    json_log: bool = False
    max_devices: int = 1
    ota_firmware: str = ""
    # Set to a subcommand name if the user ran one (e.g. "status")
    subcommand: str = ""
    # For the "device" subcommand: "show" or "forget"
    device_subcommand: str = ""

    @classmethod
    def from_args(cls) -> "Config":
        parser = argparse.ArgumentParser(description="Claude Monitor daemon")
        sub = parser.add_subparsers(dest="subcommand")

        # `status` subcommand
        sub.add_parser("status", help="Show daemon status and active sessions")

        # `ota` subcommand
        ota_parser = sub.add_parser("ota", help="Push firmware update to ESP32 via BLE")
        ota_parser.add_argument("firmware", help="Path to firmware.bin file")

        # `device` subcommand
        device_parser = sub.add_parser("device", help="Manage the paired BLE display")
        device_sub = device_parser.add_subparsers(dest="device_subcommand")
        device_sub.add_parser("show", help="Show the paired device address")
        device_sub.add_parser("forget", help="Clear pairing — next start will scan openly")

        # Daemon flags (used when no subcommand is given)
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
        parser.add_argument(
            "--json-log",
            action="store_true",
            help="Output logs as JSON lines (machine-parseable)",
        )
        parser.add_argument(
            "--devices",
            type=int,
            default=1,
            metavar="N",
            help="Max number of BLE displays to connect (default: 1)",
        )
        args = parser.parse_args()

        return cls(
            http_port=args.http_port,
            stale_timeout=args.stale_timeout,
            verbose=args.verbose,
            json_log=args.json_log,
            max_devices=args.devices,
            ota_firmware=getattr(args, "firmware", ""),
            subcommand=args.subcommand or "",
            device_subcommand=getattr(args, "device_subcommand", "") or "",
        )
