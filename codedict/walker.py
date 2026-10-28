"""Enumerate project files (git-aware) and hash them."""
import fnmatch
import hashlib
import os
import subprocess
from pathlib import Path

from .config import DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_GLOBS, MAX_FILE_BYTES


def _read_ignore(root: Path) -> list[str]:
    f = root / ".codedictignore"
    if not f.exists():
        return []
    return [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def _git_files(root: Path) -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True, check=True, timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        dirnames[:] = [
            d for d in dirnames
            if d not in DEFAULT_IGNORE_DIRS and f"{rel_dir}/{d}".lstrip("./") not in DEFAULT_IGNORE_DIRS
        ]
        for fn in filenames:
            files.append(f"{rel_dir}/{fn}".lstrip("./") if rel_dir != "." else fn)
    return files


def list_files(root: Path, wanted_exts: set[str]) -> list[str]:
    patterns = DEFAULT_IGNORE_GLOBS + _read_ignore(root)
    candidates = _git_files(root)
    if candidates is None:
        candidates = _walk_files(root)
    result = []
    for rel in candidates:
        rel = rel.replace("\\", "/")
        parts = rel.split("/")
        if any(p in DEFAULT_IGNORE_DIRS for p in parts[:-1]):
            continue
        name = parts[-1]
        if any(fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat) for pat in patterns):
            continue
        ext = _ext(name)
        if ext not in wanted_exts:
            continue
        full = root / rel
        try:
            if not full.is_file() or full.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        result.append(rel)
    return sorted(result)


def _ext(name: str) -> str:
    low = name.lower()
    if low == "dockerfile":
        return ".dockerfile"
    return os.path.splitext(low)[1]


def file_ext(rel: str) -> str:
    return _ext(rel.rsplit("/", 1)[-1])


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
