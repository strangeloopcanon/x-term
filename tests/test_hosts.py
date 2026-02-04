from __future__ import annotations

from pathlib import Path

from xgate.hosts import MANAGED_END, MANAGED_START, apply_hosts, normalize_domain


def test_normalize_domain_strips_scheme():
    assert normalize_domain("https://x.com/path") == "x.com"
    assert normalize_domain("HTTP://twitter.com") == "twitter.com"


def test_apply_hosts_adds_block(tmp_path: Path):
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n", encoding="utf-8")

    changed = apply_hosts(hosts, domains=["x.com"], should_block=True)
    content = hosts.read_text(encoding="utf-8")

    assert changed is True
    assert MANAGED_START in content
    assert MANAGED_END in content
    assert "0.0.0.0 x.com" in content


def test_apply_hosts_removes_block(tmp_path: Path):
    hosts = tmp_path / "hosts"
    hosts.write_text(
        "127.0.0.1 localhost\n"
        f"{MANAGED_START}\n"
        "0.0.0.0 x.com\n"
        f"{MANAGED_END}\n",
        encoding="utf-8",
    )

    changed = apply_hosts(hosts, domains=["x.com"], should_block=False)
    content = hosts.read_text(encoding="utf-8")

    assert changed is True
    assert MANAGED_START not in content
    assert "0.0.0.0 x.com" not in content
