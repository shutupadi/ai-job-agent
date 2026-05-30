"""Settings endpoints — current settings + minor live tweaks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import get_current_user
from app.config import settings
from app.db import models
from app.schemas.schemas import SettingsOut, SettingsPatch

router = APIRouter()


@router.get("", response_model=SettingsOut)
def get_settings(user: models.User = Depends(get_current_user)):
    return SettingsOut(
        apply_mode=settings.apply_mode,
        min_rank_to_apply=settings.min_rank_to_apply,
        max_applications_per_run=settings.max_applications_per_run,
        rate_limit_seconds=settings.rate_limit_seconds,
        keywords=settings.keywords,
        locations=settings.locations,
        greenhouse_boards=settings.greenhouse_boards,
        lever_companies=settings.lever_companies,
        enable_greenhouse=settings.enable_greenhouse,
        enable_lever=settings.enable_lever,
        enable_ycombinator=settings.enable_ycombinator,
        enable_workday=settings.enable_workday,
        enable_oracle=settings.enable_oracle,
        enable_linkedin=settings.enable_linkedin,
        enable_naukri=settings.enable_naukri,
        include_remote=settings.include_remote,
        include_international=settings.include_international,
        geo_filter_enabled=settings.geo_filter_enabled,
        experience_filter_enabled=settings.experience_filter_enabled,
        max_experience_years=settings.max_experience_years,
        llm_provider=settings.llm_provider,
        llm_model=settings.active_llm_model,
    )


@router.patch("", response_model=SettingsOut)
def patch_settings(
    payload: SettingsPatch,
    user: models.User = Depends(get_current_user),
):
    """In-process global overrides (admin only). NOTE: reset on restart.
    To persist, edit the .env file."""
    if not user.is_admin:
        raise HTTPException(403, "Admin only — these settings are global.")
    if payload.apply_mode is not None:
        settings.apply_mode = payload.apply_mode
    if payload.min_rank_to_apply is not None:
        settings.min_rank_to_apply = payload.min_rank_to_apply
    if payload.max_applications_per_run is not None:
        settings.max_applications_per_run = payload.max_applications_per_run
    if payload.rate_limit_seconds is not None:
        settings.rate_limit_seconds = payload.rate_limit_seconds
    return get_settings(user)
