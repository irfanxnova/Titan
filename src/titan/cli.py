"""Command-line interface entry point for Titan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

# Enable direct execution via 'python src/titan/cli.py'
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from titan import __version__
from titan.config import TitanConfig


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="titan",
        description="Titan: Experimental distributed-systems research platform.",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show Titan version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    status_parser = subparsers.add_parser(
        "status",
        help="Display the current project milestone and runtime configuration.",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output status information as JSON.",
    )

    return parser


def handle_status(json_output: bool = False) -> int:
    """Print the current system status and active configuration."""
    config = TitanConfig.from_env()

    if json_output:
        import json

        data = {
            "name": "Titan",
            "version": __version__,
            "milestone": "Milestone 1: Repository Foundation",
            "environment": config.environment,
            "log_level": config.log_level,
            "status": "ready",
        }
        print(json.dumps(data, indent=2))
    else:
        print("Titan Research Platform")
        print(f"  Version:     {__version__}")
        print("  Milestone:   1 (Repository Foundation)")
        print(f"  Environment: {config.environment}")
        print(f"  Log Level:   {config.log_level}")
        print("  State:       Operational (Skeleton)")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main execution entry point."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0

    if args.command == "status":
        return handle_status(json_output=args.json)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
