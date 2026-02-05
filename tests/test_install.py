from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from xgate.install import LaunchctlError, _launchctl, install_daemon


def _completed(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["launchctl"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_launchctl_tolerates_no_such_process(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _completed(3, stderr="Boot-out failed: 3: No such process\n"),
    )
    result = _launchctl(["bootout", "system/com.xterm.xgate"], tolerate_no_such_process=True)
    assert result.returncode == 3


def test_launchctl_raises_for_other_failures(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: _completed(5, stderr="Bootstrap failed: 5: Input/output error\n"),
    )
    with pytest.raises(RuntimeError, match="bootstrap"):
        _launchctl(["bootstrap", "system", "/tmp/xgate.plist"])


def test_install_daemon_tolerates_kickstart_failure_if_service_loaded(monkeypatch, tmp_path: Path):
    launchctl_calls: list[list[str]] = []

    def fake_launchctl(args, *, tolerate_no_such_process=False):  # noqa: ARG001
        launchctl_calls.append(list(args))
        if args[:2] == ["kickstart", "-k"]:
            raise LaunchctlError(args, 37, "unknown error")
        return _completed(0)

    monkeypatch.setattr("xgate.install._require_root", lambda: None)
    monkeypatch.setattr("xgate.install._user_from_sudo", lambda: SimpleNamespace(pw_uid=1, pw_gid=1))
    monkeypatch.setattr("xgate.install._ensure_log_dir", lambda: None)
    monkeypatch.setattr("xgate.install._install_code", lambda: tmp_path)
    monkeypatch.setattr("xgate.install._ensure_user_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xgate.install._chown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xgate.install._write_plist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xgate.install._launchctl", fake_launchctl)
    monkeypatch.setattr("xgate.install.daemon_status", lambda: {"code": 0, "stdout": "", "stderr": ""})

    install_daemon(tmp_path / "config.json")

    assert any(call[:2] == ["kickstart", "-k"] for call in launchctl_calls)


def test_install_daemon_raises_when_kickstart_fails_and_service_missing(monkeypatch, tmp_path: Path):
    def fake_launchctl(args, *, tolerate_no_such_process=False):  # noqa: ARG001
        if args[:2] == ["kickstart", "-k"]:
            raise LaunchctlError(args, 37, "unknown error")
        return _completed(0)

    monkeypatch.setattr("xgate.install._require_root", lambda: None)
    monkeypatch.setattr("xgate.install._user_from_sudo", lambda: SimpleNamespace(pw_uid=1, pw_gid=1))
    monkeypatch.setattr("xgate.install._ensure_log_dir", lambda: None)
    monkeypatch.setattr("xgate.install._install_code", lambda: tmp_path)
    monkeypatch.setattr("xgate.install._ensure_user_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xgate.install._chown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xgate.install._write_plist", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("xgate.install._launchctl", fake_launchctl)
    monkeypatch.setattr("xgate.install.daemon_status", lambda: {"code": 113, "stdout": "", "stderr": ""})

    with pytest.raises(LaunchctlError, match="kickstart"):
        install_daemon(tmp_path / "config.json")
