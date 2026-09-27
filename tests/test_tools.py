"""T-006 / T-007 — bash + file tools (test-plan T-05, T-06).

T-05: bash `echo hi` → {ok, result: {stdout: 'hi\\n', exit: 0}}.
T-06: file write → read → edit round-trip, content byte-identical.
"""

import pytest

from arcen.tools.bash import BashTool
from arcen.tools.file import (
    FileAppend,
    FileEdit,
    FileGlob,
    FileList,
    FileMkdir,
    FileMove,
    FileRead,
    FileWrite,
)


def test_bash() -> None:
    # ticket Command + Verification, verbatim
    out = BashTool().execute({"cmd": "echo hi"})
    assert out == {"ok": True, "result": {"stdout": "hi\n", "stderr": "", "exit": 0}, "error": None}


def test_bash_nonzero_exit_is_a_value() -> None:
    out = BashTool().execute({"cmd": "echo boom >&2; exit 3"})
    assert out["ok"] is False
    assert out["result"]["exit"] == 3
    assert "boom" in out["result"]["stderr"]
    assert out["error"]


def test_bash_timeout_never_raises() -> None:
    out = BashTool().execute({"cmd": "sleep 5", "timeout_s": 0.2})
    assert out["ok"] is False
    assert "timed out" in out["error"]


def test_bash_cwd(tmp_path) -> None:
    out = BashTool().execute({"cmd": "pwd", "cwd": str(tmp_path)})
    assert out["ok"] is True
    assert out["result"]["stdout"].strip() == str(tmp_path)


def test_file() -> None:
    # write → read → edit round-trip, byte-for-byte
    tool_w, tool_r, tool_e = FileWrite(), FileRead(), FileEdit()
    path = "/tmp/arcen_t007_roundtrip.txt"
    content = "line one\nline two\nline three\n"
    out_w = tool_w.execute({"path": path, "content": content})
    assert out_w["ok"] is True and out_w["result"]["bytes"] == len(content.encode())

    out_r = tool_r.execute({"path": path})
    assert out_r["ok"] is True
    assert out_r["result"]["content"] == content  # byte-for-byte

    out_e = tool_e.execute({"path": path, "find": "line two", "replace": "LINE 2"})
    assert out_e["ok"] is True and out_e["result"]["replacements"] == 1
    assert tool_r.execute({"path": path})["result"]["content"] == "line one\nLINE 2\nline three\n"


def test_file_edit_missing_needle_is_a_value(tmp_path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("abc")
    out = FileEdit().execute({"path": str(p), "find": "zzz", "replace": "q"})
    assert out["ok"] is False and "not found" in out["error"]


def test_file_read_slice(tmp_path) -> None:
    p = tmp_path / "y.txt"
    p.write_text("\n".join(f"l{i}" for i in range(100)))
    out = FileRead().execute({"path": str(p), "offset_line": 10, "limit_lines": 5})
    assert out["result"]["content"] == "l10\nl11\nl12\nl13\nl14\n"
    assert out["result"]["truncated"] is True


def test_file_read_preserves_trailing_newline(tmp_path) -> None:
    p = tmp_path / "z.txt"
    p.write_text("alpha\nbeta\n")
    out = FileRead().execute({"path": str(p)})
    assert out["result"]["content"] == "alpha\nbeta\n"  # byte-for-byte


def test_file_append_list_glob_mkdir_move(tmp_path) -> None:
    d = tmp_path / "dirA"
    out = FileMkdir().execute({"path": str(d)})
    assert out["ok"] is True

    f = d / "a.txt"
    FileWrite().execute({"path": str(f), "content": "one\n"})
    FileAppend().execute({"path": str(f), "content": "two\n"})
    assert FileRead().execute({"path": str(f)})["result"]["content"] == "one\ntwo\n"

    listed = FileList().execute({"path": str(d)})
    assert listed["result"]["entries"][0]["name"] == "a.txt"

    g = FileGlob().execute({"pattern": str(d / "*.txt")})
    assert g["result"]["count"] == 1

    m = FileMove().execute({"src": str(f), "dst": str(d / "b.txt")})
    assert m["ok"] is True
    assert (d / "b.txt").read_text() == "one\ntwo\n"
