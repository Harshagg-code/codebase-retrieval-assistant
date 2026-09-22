"""Repository ingestion: clone handling and the pre-parse file filter."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.config import (
    MAX_FILE_SIZE,
    MIN_FILE_SIZE,
    REPOS_DIR,
    SKIP_DIR_SUFFIXES,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    SKIP_FILENAMES,
)

# Order matters: each file is skipped for the first matching reason.
SKIP_REASONS = ("directory", "filename", "extension", "too_large", "too_small")


def _repo_name_from_url(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def clone_repo(url: str, dest_root: Path = REPOS_DIR) -> Path:
    """Shallow-clone url into dest_root/<repo-name>, or reuse it if already cloned."""
    name = _repo_name_from_url(url)
    dest = dest_root / name

    if dest.exists():
        print(f"{name}: already cloned at {dest}")
        return dest

    dest_root.mkdir(parents=True, exist_ok=True)
    print(f"{name}: cloning {url} -> {dest}")
    subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], check=True)
    return dest


@dataclass
class FilterResult:
    kept: list[Path]
    skipped: dict[str, list[Path]] = field(
        default_factory=lambda: {reason: [] for reason in SKIP_REASONS}
    )


def _is_skipped_dir_part(part: str) -> bool:
    return part in SKIP_DIRS or any(part.endswith(suf) for suf in SKIP_DIR_SUFFIXES)


def filter_files(repo_path: Path) -> FilterResult:
    """Walk repo_path and split files into kept vs. skipped-with-reason."""
    result = FilterResult(kept=[])

    for path in sorted(repo_path.rglob("*")):
        if path.is_dir():
            continue

        rel = path.relative_to(repo_path)

        if any(_is_skipped_dir_part(part) for part in rel.parts[:-1]):
            result.skipped["directory"].append(rel)
            continue

        if path.name in SKIP_FILENAMES:
            result.skipped["filename"].append(rel)
            continue

        if path.suffix.lower() in SKIP_EXTENSIONS:
            result.skipped["extension"].append(rel)
            continue

        size = path.stat().st_size

        if size > MAX_FILE_SIZE:
            result.skipped["too_large"].append(rel)
            continue

        if size < MIN_FILE_SIZE:
            result.skipped["too_small"].append(rel)
            continue

        result.kept.append(rel)

    return result


def print_filter_summary(result: FilterResult) -> None:
    total_skipped = sum(len(paths) for paths in result.skipped.values())
    total = len(result.kept) + total_skipped

    print(f"scanned {total} files: {len(result.kept)} kept, {total_skipped} skipped")
    for reason in SKIP_REASONS:
        count = len(result.skipped[reason])
        if count:
            print(f"  {count} by {reason}")


if __name__ == "__main__":
    repo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/repos/requests")
    result = filter_files(repo_path)
    print_filter_summary(result)
