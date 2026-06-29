"""Skills CRUD API — /api/v1/skills."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

logger = structlog.get_logger()

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillCreate(BaseModel):
    """Request body for creating a skill."""

    model_config = ConfigDict(strict=True)

    name: str
    description: str
    content: str
    tags: list[str] = []
    triggers: list[str] = []


class SkillResponse(BaseModel):
    """Response body for a skill."""

    model_config = ConfigDict(strict=True)

    id: str
    name: str
    description: str
    content: str
    tags: list[str]
    triggers: list[str]
    enabled: bool
    builtin: bool


@router.get("/")
async def list_skills(workspace_id: str | None = None) -> list[SkillResponse]:
    """List all enabled skills, optionally filtered by workspace."""
    logger.info("api.skills.list", workspace_id=workspace_id)
    # TODO: implement
    # store = get_postgres(request)
    # skills = await store.list_skills(workspace_id=workspace_id)
    # return [SkillResponse(...) for s in skills]
    return []


@router.post("/", status_code=201)
async def create_skill(body: SkillCreate) -> SkillResponse:
    """Create a new custom skill."""
    logger.info("api.skills.create", name=body.name)
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/{skill_id}")
async def get_skill(skill_id: str) -> SkillResponse:
    """Get a skill by ID."""
    logger.info("api.skills.get", skill_id=skill_id)
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.put("/{skill_id}")
async def update_skill(skill_id: str, body: SkillCreate) -> SkillResponse:
    """Update an existing skill."""
    logger.info("api.skills.update", skill_id=skill_id)
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: str) -> None:
    """Delete a skill (soft-disable for builtins)."""
    logger.info("api.skills.delete", skill_id=skill_id)
    # TODO: implement
    raise HTTPException(status_code=501, detail="Not yet implemented")
