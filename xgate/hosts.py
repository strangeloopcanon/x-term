from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse

MANAGED_START = "# xgate:start"
MANAGED_END = "# xgate:end"

_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$")


def normalize_domain(value: str) -> str:
    raw = value.strip().lower()
    if not raw:
        raise ValueError("empty domain")

    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.hostname:
            raw = parsed.hostname

    raw = raw.split("/")[0].split(":")[0].strip(".")
    if not raw or not _DOMAIN_RE.fullmatch(raw) or ".." in raw:
        raise ValueError("invalid domain")
    if raw.startswith("-") or raw.endswith("-"):
        raise ValueError("invalid domain")
    return raw


def expand_domains(domains: Iterable[str], *, include_www: bool) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for domain in domains:
        normalized = normalize_domain(domain)
        if normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
        if include_www and not normalized.startswith("www."):
            www = f"www.{normalized}"
            if www not in seen:
                seen.add(www)
                ordered.append(www)
    return ordered


def render_block_section(domains: list[str]) -> list[str]:
    lines = [MANAGED_START]
    for domain in domains:
        lines.append(f"0.0.0.0 {domain}")
        lines.append(f"::1 {domain}")
    lines.append(MANAGED_END)
    return lines


def _strip_managed(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == MANAGED_START:
            in_block = True
            continue
        if stripped == MANAGED_END:
            in_block = False
            continue
        if not in_block:
            cleaned.append(line)
    return cleaned


def apply_hosts(
    path: Path,
    *,
    domains: list[str],
    should_block: bool,
) -> bool:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    cleaned = _strip_managed(lines)

    if should_block and domains:
        if cleaned and cleaned[-1].strip():
            cleaned.append("")
        cleaned.extend(render_block_section(domains))

    newline = "\n" if original.endswith("\n") or not original else ""
    new_text = "\n".join(cleaned) + newline

    if new_text == original:
        return False

    tmp_path = path.with_suffix(".xgate.tmp")
    tmp_path.write_text(new_text, encoding="utf-8")
    tmp_path.replace(path)
    return True


def hosts_has_block(path: Path) -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    return MANAGED_START in content and MANAGED_END in content
