"""Deciding which files in a repository are worth indexing.

Most of a checked-out repository is not source anyone would search for. A
Node project is mostly `node_modules`; a Python one carries `.venv` and
`__pycache__`; both carry lockfiles, minified bundles and build output. Those
are generated, enormous, and would drown genuine code in the index — a search
for "authenticate" should not return forty copies of a vendored library.

So the walk is deliberately conservative. It skips known-generated trees,
anything binary, and anything implausibly large for source, and reports what
it skipped so a missing file has an explanation.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from app.services.uploads.file_types import detect

#: Directories never worth indexing. Matched on the exact directory name at
#: any depth, which is how these tools actually lay things out.
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "bower_components",
        "vendor",
        "third_party",
        ".venv",
        "venv",
        "env",
        "virtualenv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "out",
        "target",
        "bin",
        "obj",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".turbo",
        ".parcel-cache",
        "coverage",
        "htmlcov",
        ".nyc_output",
        ".idea",
        ".vscode",
        ".gradle",
        ".terraform",
        "site-packages",
        "Pods",
        "DerivedData",
    }
)

#: Files that are generated, locked or minified. Their content is real text,
#: which is exactly why they need excluding: a 4 MB lockfile chunks into
#: hundreds of meaningless vectors.
IGNORED_FILENAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
        "composer.lock",
        "Cargo.lock",
        "go.sum",
        "Gemfile.lock",
        "packages.lock.json",
        ".ds_store",
        "thumbs.db",
    }
)

IGNORED_SUFFIXES = frozenset(
    {
        ".min.js",
        ".min.css",
        ".map",
        ".bundle.js",
        ".pyc",
        ".pyo",
        ".class",
        ".o",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".lock",
        ".log",
        ".pid",
        ".sqlite3",
        ".db",
    }
)

#: A source file larger than this is generated, vendored or data. Real code
#: written by a person effectively never reaches it.
MAX_FILE_BYTES = 1024 * 1024

#: Total files imported from one repository. A monorepo can hold hundreds of
#: thousands, and importing all of them would take hours and bury everything
#: else the user owns.
MAX_FILES = 2000


@dataclass(slots=True)
class WalkResult:
    files: list[Path] = field(default_factory=list)
    skipped: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    truncated: bool = False

    def skip(self, reason: str) -> None:
        self.skipped += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


def is_probably_binary(path: Path, *, probe_bytes: int = 8192) -> bool:
    """A NUL byte in the first few KB means binary.

    The same heuristic git itself uses. Cheap, and wrong only for files that
    would embed as noise anyway.
    """
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(probe_bytes)
    except OSError:
        return True


def walk_repository(root: Path) -> WalkResult:
    """Collect the files worth indexing, and count what was left out."""
    result = WalkResult()

    for path in _iter_files(root):
        if len(result.files) >= MAX_FILES:
            result.truncated = True
            result.skip("repository too large")
            continue

        name = path.name.lower()

        if name in IGNORED_FILENAMES:
            result.skip("generated or lock file")
            continue
        if any(name.endswith(suffix) for suffix in IGNORED_SUFFIXES):
            result.skip("generated or binary")
            continue

        # No parser means nothing could read it even if imported.
        if detect(path.name) is None:
            result.skip("unsupported file type")
            continue

        try:
            size = path.stat().st_size
        except OSError:
            result.skip("unreadable")
            continue

        if size == 0:
            result.skip("empty")
            continue
        if size > MAX_FILE_BYTES:
            result.skip("too large")
            continue
        if is_probably_binary(path):
            result.skip("binary")
            continue

        result.files.append(path)

    return result


def _iter_files(root: Path) -> Iterator[Path]:
    """Depth-first walk that prunes ignored directories rather than
    descending into them — the difference between reading a `node_modules`
    tree and skipping it in one comparison."""
    stack = [root]

    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue

        for entry in entries:
            if entry.is_symlink():
                # A symlink can point outside the checkout, or into a cycle.
                continue
            if entry.is_dir():
                if entry.name not in IGNORED_DIRECTORIES:
                    stack.append(entry)
            elif entry.is_file():
                yield entry
