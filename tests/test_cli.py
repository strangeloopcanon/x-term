from __future__ import annotations

from pathlib import Path

from xgate import COMPAT_VERSION
from xgate.cli import _read_deployed_compat, _status_payload
from xgate.config import DEFAULT_CONFIG


def test_read_deployed_compat_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("xgate.cli.DEPLOYED_APP_DIR", tmp_path)
    compat, error = _read_deployed_compat()
    assert compat is None
    assert "not found" in (error or "")


def test_read_deployed_compat_parses_value(monkeypatch, tmp_path: Path):
    app_dir = tmp_path / "xgate"
    app_dir.mkdir(parents=True)
    (app_dir / "__init__.py").write_text(
        '"""xgate"""\nCOMPAT_VERSION = 7\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("xgate.cli.DEPLOYED_APP_DIR", app_dir)

    compat, error = _read_deployed_compat()
    assert compat == 7
    assert error is None


def test_status_payload_warns_on_compat_mismatch(monkeypatch):
    monkeypatch.setattr(
        "xgate.cli.ProcessGate.poll",
        lambda self: (False, False, {"evidence": []}),
    )
    monkeypatch.setattr("xgate.cli.hosts_has_block", lambda _path: False)
    monkeypatch.setattr("xgate.cli._read_daemon_state", lambda **_kwargs: None)
    monkeypatch.setattr("xgate.cli._read_deployed_compat", lambda: (COMPAT_VERSION + 1, None))

    payload = _status_payload(DEFAULT_CONFIG, debug=False, config_file=Path("/tmp/config.json"))
    warnings = payload.get("status_warnings", [])
    assert any("CLI/daemon mismatch" in warning for warning in warnings)
    assert any("daemon state unavailable" in warning for warning in warnings)


def test_status_payload_includes_time_block_fields(monkeypatch):
    monkeypatch.setattr(
        "xgate.cli.ProcessGate.poll",
        lambda self: (False, False, {"evidence": []}),
    )
    monkeypatch.setattr("xgate.cli.hosts_has_block", lambda _path: False)
    monkeypatch.setattr("xgate.cli._read_daemon_state", lambda **_kwargs: None)
    monkeypatch.setattr("xgate.cli._read_deployed_compat", lambda: (COMPAT_VERSION, None))

    payload = _status_payload(DEFAULT_CONFIG, debug=False, config_file=Path("/tmp/config.json"))
    assert "time_blocks" in payload
    assert "block_until_unix" in payload
    assert "block_reasons" in payload
    assert "timer_block_active" in payload
    assert "time_block_active" in payload
