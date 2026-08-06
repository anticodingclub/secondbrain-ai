"""Importing GitHub repositories."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import (
    CurrentUser,
    RepositoryImportServiceDep,
    SessionDep,
)
from app.core.exceptions import ConflictError, NotFoundError
from app.models.repository import Repository, RepositoryStatus
from app.services.repositories import git_is_available, parse_repository

router = APIRouter(prefix="/repositories", tags=["repositories"])


class ImportRequest(BaseModel):
    #: A GitHub URL, an SSH remote, or the `owner/name` shorthand.
    repository: str = Field(min_length=1, max_length=512)
    branch: str | None = Field(default=None, max_length=255)


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    clone_url: str
    owner_name: str
    repo_name: str
    branch: str | None
    commit_sha: str | None
    status: RepositoryStatus
    error_message: str | None
    file_count: int
    skipped_count: int
    collection_id: uuid.UUID | None
    last_synced_at: datetime | None
    repo_metadata: dict[str, Any]
    created_at: datetime


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Import a GitHub repository",
)
async def import_repository(
    payload: ImportRequest,
    current_user: CurrentUser,
    session: SessionDep,
    importer: RepositoryImportServiceDep,
    background: BackgroundTasks,
) -> RepositoryResponse:
    """Clone and index a public repository.

    Returns 202 rather than 201: cloning and indexing a repository takes
    minutes, so the work is accepted and continues in the background. Poll
    the returned record for its status.
    """
    if not git_is_available():
        raise NotFoundError(
            "Git is not installed on the server, so repositories cannot be imported. "
            "Install it from https://git-scm.com and restart the backend."
        )

    ref = parse_repository(payload.repository, branch=payload.branch)

    existing = (
        await session.execute(
            select(Repository).where(
                Repository.owner_id == current_user.id,
                Repository.clone_url == ref.clone_url,
            )
        )
    ).scalar_one_or_none()

    if existing is not None and existing.status not in {
        RepositoryStatus.FAILED,
        RepositoryStatus.READY,
    }:
        raise ConflictError(f"{ref.full_name} is already being imported.")

    repository = existing or Repository(
        owner_id=current_user.id,
        clone_url=ref.clone_url,
        owner_name=ref.owner,
        repo_name=ref.name,
        branch=ref.branch,
    )
    repository.status = RepositoryStatus.PENDING
    repository.error_message = None
    repository.branch = ref.branch

    session.add(repository)
    await session.flush()
    response = RepositoryResponse.model_validate(repository)
    repository_id = repository.id

    # Committed before scheduling: background tasks run before FastAPI tears
    # down `yield` dependencies, so the importer's own session would otherwise
    # find no such repository. Same hazard as document upload.
    await session.commit()
    background.add_task(
        importer.import_repository,
        repository_id,
        owner_id=current_user.id,
        ref=ref,
    )

    return response


@router.get("", response_model=list[RepositoryResponse], summary="List repositories")
async def list_repositories(
    current_user: CurrentUser, session: SessionDep
) -> list[RepositoryResponse]:
    rows = (
        (
            await session.execute(
                select(Repository)
                .where(Repository.owner_id == current_user.id)
                .order_by(Repository.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [RepositoryResponse.model_validate(row) for row in rows]


async def _owned_repository(
    repository_id: uuid.UUID, current_user: CurrentUser, session: SessionDep
) -> Repository:
    repository = (
        await session.execute(
            select(Repository).where(
                Repository.id == repository_id,
                Repository.owner_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if repository is None:
        raise NotFoundError("Repository not found.")
    return repository


OwnedRepository = Annotated[Repository, Depends(_owned_repository)]


@router.get("/{repository_id}", response_model=RepositoryResponse, summary="One repository")
async def get_repository(repository: OwnedRepository) -> RepositoryResponse:
    return RepositoryResponse.model_validate(repository)


@router.post(
    "/{repository_id}/sync",
    response_model=RepositoryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-import a repository",
)
async def sync_repository(
    repository: OwnedRepository,
    current_user: CurrentUser,
    session: SessionDep,
    importer: RepositoryImportServiceDep,
    background: BackgroundTasks,
) -> RepositoryResponse:
    """Pull the latest commit and import anything new.

    Unchanged files deduplicate by content hash, so re-syncing a repository
    that has not moved costs a clone and nothing else.
    """
    ref = parse_repository(repository.clone_url, branch=repository.branch)
    repository.status = RepositoryStatus.PENDING
    repository.error_message = None

    response = RepositoryResponse.model_validate(repository)
    repository_id = repository.id

    await session.commit()
    background.add_task(
        importer.import_repository,
        repository_id,
        owner_id=current_user.id,
        ref=ref,
    )
    return response


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a repository",
)
async def delete_repository(repository: OwnedRepository, session: SessionDep) -> None:
    """Remove the repository record.

    Its documents are left in place deliberately: they are ordinary documents
    the user owns, and silently deleting hundreds of files because a
    repository entry was removed would be a surprise. They can be deleted
    from the library by filtering to the collection.
    """
    await session.delete(repository)
