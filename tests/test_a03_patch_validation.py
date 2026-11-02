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
