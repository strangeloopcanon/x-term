#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import re
import stat
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

    raise RuntimeError(f"Unsupported OS for auto-install: {sysname}")


def _make_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        # Best-effort: Chrome will fail clearly if it can't exec the host.
        pass


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install the x-term native messaging host manifest for Google Chrome.",
    )
    parser.add_argument(
        "--extension-id",
        required=True,
        help="Chrome extension ID (from chrome://extensions).",
    )
    parser.add_argument(
        "--manifest-dir",
        default=None,
        help="Override native host manifest directory (advanced).",
    )
    args = parser.parse_args(argv)

    ext_id = args.extension_id.strip()
    if not ext_id:
        raise SystemExit("--extension-id is required")
    if not re.fullmatch(r"[a-p]{32}", ext_id):
        raise SystemExit(
            "--extension-id must be a 32-character Chrome extension id (letters a-p)"
        )

    host_path = (Path(__file__).parent / "process_gate.py").resolve()
    if not host_path.exists():
        raise SystemExit(f"Missing native host at {host_path}")
    _make_executable(host_path)

    manifest_dir = (
        Path(args.manifest_dir).expanduser().resolve()
        if args.manifest_dir
        else _chrome_manifest_dir()
    )
    manifest_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = manifest_dir / f"{HOST_NAME}.json"

    manifest = {
        "name": HOST_NAME,
        "description": "Blocks x.com while Codex or Claude Code runs in a terminal.",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"],
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote native host manifest:\n  {manifest_path}")
    print("Restart Chrome to pick it up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
