"""Cloning a repository, safely.

Shelling out to `git` rather than using a Python git library. The operation is
one command, and a library would add a large dependency to wrap a binary that
has to be installed anyway.

Shelling out to git with a user-supplied URL needs care, and the two things
that matter here are:

**No shell.** The argument list goes straight to `execve`, so a URL containing
`;rm -rf ~` is a nonsense URL and nothing more. There is no shell to interpret
it.

**No credential prompts.** A private repository would otherwise block forever
waiting on a terminal that does not exist, holding the worker open until the
timeout. `GIT_TERMINAL_PROMPT=0` turns that into an immediate, honest failure.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import SecondBrainError
from app.core.logging import get_logger

logger = get_logger(__name__)

CLONE_TIMEOUT_SECONDS = 300


class RepositoryError(SecondBrainError):
    status_code = 422
    error_code = "repository_error"
    default_message = "The repository could not be imported."


@dataclass(frozen=True, slots=True)
class RepositoryRef:
    """A parsed repository reference."""

    clone_url: str
    owner: str
    name: str
    branch: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


#: Accepts the forms people actually paste: a browser URL, an owner/name
#: shorthand, an SSH remote, and any of those with a .git suffix.
_PATTERNS = (
    re.compile(
        r"^https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"
    ),
    re.compile(r"^git@github\.com:(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"),
    re.compile(r"^(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"),
)


def parse_repository(reference: str, *, branch: str | None = None) -> RepositoryRef:
    """Turn what the user pasted into a clone URL.

    Only github.com is accepted. Cloning an arbitrary URL on a user's behalf
    is a server-side request forgery primitive — it would let anyone point the
    server at `http://169.254.169.254/` or an internal host and use the error
    messages to probe a network they cannot otherwise reach.
    """
    candidate = reference.strip()

    # A local path is allowed only because the tests need one; it can never
    # arrive from the API, which validates the reference first.
    if candidate.startswith("file://") or Path(candidate).is_dir():
        path = Path(candidate.removeprefix("file://"))
        return RepositoryRef(clone_url=str(path), owner="local", name=path.name, branch=branch)

    for pattern in _PATTERNS:
        if match := pattern.match(candidate):
            owner, name = match.group("owner"), match.group("name")
            return RepositoryRef(
                clone_url=f"https://github.com/{owner}/{name}.git",
                owner=owner,
                name=name,
                branch=branch,
            )

    raise RepositoryError(
        f"{reference!r} is not a GitHub repository. "
        "Use a URL like https://github.com/owner/name, or just owner/name."
    )


def git_is_available() -> bool:
    return shutil.which("git") is not None


async def clone(ref: RepositoryRef, destination: Path) -> str:
    """Shallow-clone a repository and return the commit SHA.

    `--depth 1` because history is not searched — only the current state of
    the files is. On a large repository that is the difference between tens of
    megabytes and several gigabytes.
    """
    if not git_is_available():
        raise RepositoryError(
            "Git is not installed on the server, so repositories cannot be cloned. "
            "Install it from https://git-scm.com and restart the backend."
        )

    command = [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        # Submodules would clone unbounded extra repositories, and each of
        # them is a URL the user did not ask for.
        "--no-recurse-submodules",
        "--quiet",
    ]
    if ref.branch:
        command += ["--branch", ref.branch]
    command += [ref.clone_url, str(destination)]

    environment = {
        **os.environ,
        # No prompt for credentials on a private repository: it would hang
        # until the timeout rather than failing usefully.
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "GCM_INTERACTIVE": "never",
    }

    logger.info("cloning_repository", repository=ref.full_name, branch=ref.branch)

    try:
        completed = await _run(command, env=environment, timeout=CLONE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise RepositoryError(
            f"Cloning {ref.full_name} took longer than "
            f"{CLONE_TIMEOUT_SECONDS // 60} minutes and was stopped."
        ) from exc
    except OSError as exc:
        raise RepositoryError(f"Could not run git: {exc}") from exc

    if completed.returncode != 0:
        raise RepositoryError(
            _explain_clone_failure(ref, completed.stderr.decode("utf-8", "replace"))
        )

    return await _head_commit(destination)


async def _run(
    command: list[str], *, env: dict[str, str] | None = None, timeout: int
) -> subprocess.CompletedProcess[bytes]:
    """Run a command off the event loop.

    `asyncio.create_subprocess_exec` is the obvious choice and is wrong here:
    it raises NotImplementedError under a SelectorEventLoop, which is what
    uvicorn runs on Windows. The failure is invisible to the test suite
    because pytest-asyncio uses the default (Proactor) policy, so the same
    code passed every test and then failed on the actual server.

    `subprocess.run` in a worker thread has no event-loop dependency at all,
    which makes it correct on every platform and every loop implementation.

    Still no shell: the argument list goes straight to the process, so a URL
    containing shell metacharacters is just an invalid URL.
    """
    return await asyncio.to_thread(
        subprocess.run,
        command,
        capture_output=True,
        env=env,
        timeout=timeout,
        check=False,
    )


def _explain_clone_failure(ref: RepositoryRef, stderr: str) -> str:
    """Turn git's stderr into something a person can act on."""
    lowered = stderr.lower()

    if "could not read username" in lowered or "authentication failed" in lowered:
        return (
            f"{ref.full_name} is private or does not exist. "
            "Only public repositories can be imported."
        )
    if "repository not found" in lowered or "not found" in lowered:
        return f"{ref.full_name} was not found on GitHub."
    if "could not resolve host" in lowered or "unable to access" in lowered:
        return "Could not reach GitHub. Check your network connection."
    if "remote branch" in lowered and "not found" in lowered:
        return f"Branch {ref.branch!r} does not exist in {ref.full_name}."

    return f"Cloning {ref.full_name} failed: {stderr.strip()[:300]}"


async def _head_commit(repository: Path) -> str:
    try:
        completed = await _run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"], timeout=30
        )
        return completed.stdout.decode().strip()
    except (subprocess.TimeoutExpired, OSError):
        # Not fatal: the clone succeeded, we simply cannot label it. Re-sync
        # will then always re-import rather than skipping an unchanged repo.
        logger.warning("head_commit_unavailable", path=str(repository))
        return ""
