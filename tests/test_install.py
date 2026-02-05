from __future__ import annotations

import subprocess

import pytest

from xgate.install import _launchctl


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

