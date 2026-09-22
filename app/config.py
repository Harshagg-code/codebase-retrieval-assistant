"""Paths, model names, and filter thresholds shared across the pipeline."""

from pathlib import Path

REPOS_DIR = Path("data/repos")
QDRANT_PATH = Path("data/qdrant")
SQLITE_PATH = Path("data/index.sqlite")

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
RERANKER_MODEL = "BAAI/bge-reranker-base"
GENERATION_MODEL = "gpt-4o-mini"  # swappable behind answer.generate_answer -- least interesting part of the system

# File extension -> tree-sitter-language-pack grammar name.
LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}

# Directories skipped anywhere in a file's path, regardless of depth.
SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "vendor",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
    ".eggs",
}
SKIP_DIR_SUFFIXES = (".egg-info",)

# Extensions that are binary, image, or otherwise never worth indexing as text.
SKIP_EXTENSIONS = {
    # images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    # compiled / binary / archives
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin", ".whl",
    ".zip", ".tar", ".gz", ".tgz", ".7z", ".pdf", ".db", ".sqlite",
    ".class", ".jar",
    # fonts
    ".woff", ".woff2", ".ttf", ".eot",
    # git internals that show up as plain files (packed objects/indexes)
    ".pack", ".idx",
    # compiled translations
    ".mo",
}

# Lockfiles: large, machine-generated, no useful symbols.
SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "composer.lock",
    "Gemfile.lock",
}

MAX_FILE_SIZE = 400 * 1024  # bytes
MIN_FILE_SIZE = 30  # bytes
