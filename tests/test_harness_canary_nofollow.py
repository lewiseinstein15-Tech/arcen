"""Exercise the actual generated verifier on Linux; no Docker or provider."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys

import pytest
from test_harness_canary import run, setup
from test_harness_comparison import provider
from test_probe_execution import Boundary

from arcen.harness import probe_container
from arcen.harness.canary import CASES, _commands

pytestmark = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"),
    reason="Linux-style no-follow and nonblocking open required",
)


def script_for(case, output):
    args = shlex.split(_commands(case).verify)
    assert args[:3] == ["/usr/local/bin/python3", "-I", "-c"]
    return args[3].replace("/workspace/" + case.output_file, str(output))


def run_script(script, setup=""):
    return subprocess.run(
        [sys.executable, "-I", "-c", setup + "\n" + script],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    ).returncode


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_real_verifier_rejects_symlinks_fifo_and_wrong_files(tmp_path, case):
    path = tmp_path / case.output_file
    target = tmp_path / "correct-target"
    target.write_bytes(case.expected)
    script = script_for(case, path)
    assert run_script(script) == 1
    path.write_bytes(case.expected)
    assert run_script(script) == 0
    path.write_bytes(case.expected + b"extra")
    assert run_script(script) == 1
    path.write_bytes(b"x" * len(case.expected))
    assert run_script(script) == 1
    path.unlink()
    path.symlink_to(target)
    assert run_script(script) == 1
    path.unlink()
    os.mkfifo(path)
    assert run_script(script) == 1  # O_NONBLOCK: no hang opening a FIFO
    path.unlink()
    path.mkdir()
    assert run_script(script) == 1


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
@pytest.mark.parametrize("when", ["before_open", "after_open"])
def test_path_replaced_by_symlink_during_open_cannot_redirect_verifier(tmp_path, case, when):
    path = tmp_path / case.output_file
    target = tmp_path / "correct-target"
    path.write_bytes(b"x" * len(case.expected))
    target.write_bytes(case.expected)
    if when == "before_open":
        setup = f"""import os
real_open = os.open
def racing_open(path, flags, *args, **kwargs):
    os.unlink(path)
    os.symlink({str(target)!r}, path)
    return real_open(path, flags, *args, **kwargs)
os.open = racing_open
"""
    else:
        setup = f"""import os
real_open = os.open
def racing_open(path, flags, *args, **kwargs):
    fd = real_open(path, flags, *args, **kwargs)
    os.unlink(path)
    os.symlink({str(target)!r}, path)
    return fd
os.open = racing_open
"""
    assert run_script(script_for(case, path), setup) == 1
    assert path.is_symlink()


def test_legacy_lstat_then_open_positive_control_is_redirected(tmp_path):
    """Demonstrate the old race using a deterministic local path swap."""
    case = CASES[0]
    path, target = tmp_path / case.output_file, tmp_path / "correct-target"
    path.write_bytes(b"bad")
    target.write_bytes(case.expected)
    setup = f"""import builtins,os
real_open = builtins.open
def racing_open(path, *args, **kwargs):
    os.unlink(path)
    os.symlink({str(target)!r}, path)
    return real_open(path, *args, **kwargs)
builtins.open = racing_open
"""
    legacy = f"""import os,stat,sys
p={str(path)!r}; expected={case.expected!r}
s=os.lstat(p)
if not stat.S_ISREG(s.st_mode) or s.st_size != len(expected): sys.exit(1)
with open(p,'rb') as f: actual=f.read(len(expected)+1)
sys.exit(0 if actual == expected else 1)
"""
    assert run_script(legacy, setup) == 0
    assert path.is_symlink()


@pytest.mark.parametrize("flag", ["O_NOFOLLOW", "O_NONBLOCK"])
def test_missing_required_flag_fails_closed(tmp_path, flag):
    case = CASES[0]
    path = tmp_path / case.output_file
    path.write_bytes(case.expected)
    assert run_script(script_for(case, path), f"import os\ndel os.{flag}\n") == 2  # inconclusive


@pytest.mark.parametrize("which", [1, 2])
def test_unsupported_verifier_flags_are_inconclusive_in_orchestrator(tmp_path, monkeypatch, which):
    args = setup(tmp_path)
    checks = 0

    class Unsupported(Boundary):
        def dispatch(self, name, arguments):
            nonlocal checks
            if arguments["cmd"].startswith("/usr/local/bin/python3 -I -c"):
                checks += 1
                if checks == which:
                    return {"ok": False, "result": {"exit": 2}, "error": "unsupported"}
            return super().dispatch(name, arguments)

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Unsupported)
    calls = provider(monkeypatch)
    report = run(args)
    assert report.outcome == "inconclusive" and checks == which and len(calls) == which * 2
    expected = ("inconclusive", "not-run") if which == 1 else ("passed", "inconclusive")
    assert [(f.reference, f.candidate) for f in report.findings] == [expected]
