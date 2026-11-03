"""Fail-closed host-side handling of untrusted workspace tar streams.

This first step does not yet connect the extractor to a turn or publish patches.
"""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path, PurePosixPath

from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError

MAX_ENTRIES = 10000
MAX_FILE_SIZE = 4 * 1024 * 1024
MAX_PATH_BYTES = 240


def extract_candidate(data: bytes, destination: Path) -> None:
    """Extract a bounded uncompressed tar to a newly created private directory."""
    if len(data) > MAX_PATCH_BYTES:
        raise ArtifactError("workspace archive exceeds size limit")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for count, entry in enumerate(archive, 1):
                if count > MAX_ENTRIES:
                    raise ArtifactError("workspace archive exceeds entry limit")
                raw = entry.name
                path = PurePosixPath(raw)
                parts = raw.split("/")
                if (
                    not raw
                    or raw.startswith("/")
                    or any(part in ("", ".", "..") for part in parts)
                    or len(raw.encode("utf-8", "surrogateescape")) > MAX_PATH_BYTES
                    or any(len(part.encode("utf-8", "surrogateescape")) > 128 for part in parts)
                    or path.is_absolute()
                ):
                    raise ArtifactError("unsafe workspace archive path")
                if raw in seen:
                    raise ArtifactError("duplicate workspace archive path")
                seen.add(raw)
                if entry.mode & 0o6000:
                    raise ArtifactError("workspace archive has setuid or setgid bits")
                if not (entry.isdir() or entry.isfile()) or entry.sparse is not None:
                    raise ArtifactError("workspace archive contains unsupported entry type")
                if entry.size < 0 or entry.size > MAX_FILE_SIZE:
                    raise ArtifactError("workspace archive file exceeds size limit")
                total += entry.size
                if total > MAX_PATCH_BYTES:
                    raise ArtifactError("workspace archive contents exceed size limit")
                # Validate even Git entries before ignoring their content.
                if any(part.lower() == ".git" for part in parts):
                    continue
                target = destination.joinpath(*parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if entry.isdir():
                    target.mkdir(mode=0o700, exist_ok=True)
                    if not target.is_dir():
                        raise ArtifactError("workspace archive path conflict")
                else:
                    source = archive.extractfile(entry)
                    if source is None:
                        raise ArtifactError("workspace archive file has no contents")
                    fd = os.open(
                        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                    )
                    with source, os.fdopen(fd, "wb") as output:
                        remaining = entry.size
                        while remaining:
                            block = source.read(min(remaining, 65536))
                            if not block:
                                raise ArtifactError("truncated workspace archive file")
                            output.write(block)
                            remaining -= len(block)
                        os.fchmod(output.fileno(), 0o755 if entry.mode & 0o111 else 0o644)
    except (tarfile.TarError, OSError, UnicodeError) as exc:
        raise ArtifactError(f"workspace archive extraction failed: {exc}") from exc


def build_host_patch(baseline_tar: bytes, candidate_tar: bytes) -> bytes:
    """Build and validate a patch in a disposable host Git repository.

    Only archive data is processed on the host; no workspace code is executed.
    This helper is not connected to a container turn or artifact publication.
    """
    import shutil
    import subprocess
    import tempfile

    from arcen.sandbox.patch_validation import validate_patch

    def attrs(root: Path) -> dict[str, tuple[bytes, int]]:
        return {
            p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mode & 0o777)
            for p in root.rglob("*")
            if p.is_file() and p.name.lower() == ".gitattributes"
        }

    with tempfile.TemporaryDirectory(prefix="arcen-host-export-") as temporary:
        root = Path(temporary)
        baseline, candidate = root / "baseline", root / "candidate"
        extract_candidate(baseline_tar, baseline)
        extract_candidate(candidate_tar, candidate)
        base_attrs, candidate_attrs = attrs(baseline), attrs(candidate)
        if base_attrs != candidate_attrs:
            raise ArtifactError("changes to .gitattributes are forbidden")
        # Exclude unchanged attributes entirely so Git cannot use them to
        # transform files or run filters. Changes to them have been refused.
        for name in base_attrs:
            (baseline / name).unlink()
            (candidate / name).unlink()
        repo = root / "repo"
        shutil.copytree(baseline, repo)
        env = {
            "PATH": os.defpath,
            "HOME": str(root),
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "ARCEN",
            "GIT_AUTHOR_EMAIL": "arcen@example.invalid",
            "GIT_COMMITTER_NAME": "ARCEN",
            "GIT_COMMITTER_EMAIL": "arcen@example.invalid",
        }
        command = [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repo),
        ]

        def git(*arguments: str) -> bytes:
            try:
                result = subprocess.run(
                    command + list(arguments),
                    env=env,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise ArtifactError("host Git diff could not run") from exc
            if result.returncode:
                raise ArtifactError(
                    "host Git diff failed: " + result.stderr.decode("utf-8", "replace")[:500]
                )
            return result.stdout

        git("init", "-q")
        git("add", "-A", "-f")
        git("commit", "-q", "--allow-empty", "-m", "baseline")
        for child in repo.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        shutil.copytree(candidate, repo, dirs_exist_ok=True)
        git("add", "-A", "-f")
        patch = git(
            "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv", "--no-renames"
        )
        validate_patch(patch)
        return patch


def export_candidate(session: str, candidate_tar: bytes, emit, *, home: Path | None = None) -> dict:
    """Create and publish a host-generated diff using a verified private baseline.

    The caller must obtain candidate_tar through the bounded container collector.
    This function processes archive data only and never executes candidate code.
    It is not yet connected to real container turns.
    """
    from arcen.sandbox.artifact_store import publish_artifact
    from arcen.sandbox.baseline_store import load_baseline

    baseline, base_commit = load_baseline(session, home=home)
    patch = build_host_patch(baseline, candidate_tar)
    return publish_artifact(session, patch, base_commit, emit, home=home, require_baseline=True)
