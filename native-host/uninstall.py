#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

HOST_NAME = "com.xterm.processgate"


def _chrome_manifest_dir() -> Path:
    sysname = platform.system()
    home = Path.home()

    if sysname == "Darwin":
        return home / "Library/Application Support/Google/Chrome/NativeMessagingHosts"
    if sysname == "Linux":
        return home / ".config/google-chrome/NativeMessagingHosts"

    raise RuntimeError(f"Unsupported OS for auto-uninstall: {sysname}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uninstall.py",
        description="Uninstall the x-term native messaging host manifest for Google Chrome.",
    )
    parser.add_argument(
        "--manifest-dir",
        default=None,
        help="Override native host manifest directory (advanced).",
    )
    args = parser.parse_args(argv)

    manifest_dir = (
        Path(args.manifest_dir).expanduser().resolve()
        if args.manifest_dir
        else _chrome_manifest_dir()
    )
    manifest_path = manifest_dir / f"{HOST_NAME}.json"

    if manifest_path.exists():
        manifest_path.unlink()
        print(f"Removed:\n  {manifest_path}")
    else:
        print(f"Not found:\n  {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
