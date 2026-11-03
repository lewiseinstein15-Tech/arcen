"""Unit tests for the A-03 patch validator; these do not test export/apply."""

import subprocess

import pytest

from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError, validate_patch


def patch(path: str, mode: str = "100644") -> bytes:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"new file mode {mode}\nindex 0000000..1234567\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+hello\n"
    ).encode()


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        ".git/config",
        "a/.git/x",
        ".env",
        ".env.local",
        "dir/.environment",
        "dir/.npmrc",
        ".pypirc",
        "secret.key",
        "secret.p12",
        ".gitattributes",
        "dir/.gitmodules",
        "keys/server.pem",
        "home/id_rsa",
    ],
)
def test_rejects_unsafe_or_secret_paths(path):
    with pytest.raises(ArtifactError):
        validate_patch(patch(path))


@pytest.mark.parametrize("mode", ["120000", "160000", "100755"])
def test_rejects_symlink_submodule_and_executable(mode):
    with pytest.raises(ArtifactError):
        validate_patch(patch("file", mode))


def test_rejects_oversize():
    with pytest.raises(ArtifactError, match="exceeds"):
        validate_patch(b"a" * (MAX_PATCH_BYTES + 1))


def test_rejects_mismatched_patch_header():
    data = patch("file").replace(b"+++ b/file", b"+++ b/other")
    with pytest.raises(ArtifactError, match="mismatched"):
        validate_patch(data)


def test_accepts_new_file():
    assert validate_patch(patch("dir/new.txt")) == ["dir/new.txt"]


def test_accepts_real_git_binary_diff(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True
    )
    (tmp_path / "binary.dat").write_bytes(b"\x00old\xff")
    subprocess.run(["git", "-C", str(tmp_path), "add", "binary.dat"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "baseline"], check=True)
    (tmp_path / "binary.dat").write_bytes(b"\x00new\xff")
    data = subprocess.check_output(
        ["git", "-C", str(tmp_path), "diff", "--binary", "--no-ext-diff", "--no-textconv"]
    )
    assert validate_patch(data) == ["binary.dat"]
    (tmp_path / "binary.dat").write_bytes(b"\x00old\xff")
    subprocess.run(["git", "-C", str(tmp_path), "apply", "--check", "-"], input=data, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "apply", "-"], input=data, check=True)
    assert (tmp_path / "binary.dat").read_bytes() == b"\x00new\xff"


def test_existing_executable_content_change_allowed():
    data = (
        b"diff --git a/tool b/tool\nindex 1234567..abcdef0 100755\n"
        b"--- a/tool\n+++ b/tool\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert validate_patch(data) == ["tool"]


@pytest.mark.parametrize("old,new", [("100644", "100755"), ("100755", "100644")])
def test_executable_mode_change_rejected(old, new):
    data = f"diff --git a/tool b/tool\nold mode {old}\nnew mode {new}\n".encode()
    with pytest.raises(ArtifactError):
        validate_patch(data)


def test_new_executable_hidden_in_index_rejected():
    data = patch("tool").replace(b"index 0000000..1234567", b"index 0000000..1234567 100755")
    with pytest.raises(ArtifactError):
        validate_patch(data)


def test_hunk_header_like_content_is_valid_and_applies(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.invalid"], check=True
    )
    path = tmp_path / "markers"
    path.write_bytes(b"-- prior\nunchanged\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "markers"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    path.write_bytes(b"++ next\nunchanged\n")
    data = subprocess.check_output(["git", "-C", str(tmp_path), "diff", "--binary"])
    assert b"--- prior\n+++ next\n" in data
    assert validate_patch(data) == ["markers"]
    path.write_bytes(b"-- prior\nunchanged\n")
    subprocess.run(["git", "-C", str(tmp_path), "apply", "--check", "-"], input=data, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "apply", "-"], input=data, check=True)
    assert path.read_bytes() == b"++ next\nunchanged\n"


def test_rejects_header_smuggled_after_incomplete_hunk():
    data = (
        b"diff --git a/safe b/safe\nindex 1234567..abcdef0 100644\n"
        b"--- a/safe\n+++ b/safe\n@@ -1 +1 @@\n-old\n"
        b"diff --git a/other b/other\nnew file mode 100644\nindex 0000000..1234567\n"
        b"--- /dev/null\n+++ b/other\n@@ -0,0 +1 @@\n+other\n"
    )
    with pytest.raises(ArtifactError, match="truncated"):
        validate_patch(data)


def test_rejects_extra_metadata_after_completed_hunk():
    with pytest.raises(ArtifactError, match="unexpected metadata"):
        validate_patch(patch("file") + b"--- a/other\n+++ b/other\n")


def test_rejects_absurd_hunk_count():
    data = patch("file").replace(b"-0,0", b"-0," + b"9" * 5000)
    with pytest.raises(ArtifactError, match="size limit"):
        validate_patch(data)


def test_supports_two_hunks_and_no_newline_marker(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.invalid"], check=True
    )
    path = tmp_path / "multi"
    path.write_bytes(b"old\n" + b"unchanged\n" * 20 + b"old")
    subprocess.run(["git", "-C", str(tmp_path), "add", "multi"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    path.write_bytes(b"new\n" + b"unchanged\n" * 20 + b"new")
    data = subprocess.check_output(["git", "-C", str(tmp_path), "diff", "--binary"])
    assert data.count(b"@@ -") == 2 and b"No newline at end of file" in data
    assert validate_patch(data) == ["multi"]
