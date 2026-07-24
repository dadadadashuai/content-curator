# content-curator/app/models.py
"""Pydantic models for API request/response."""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CreatorCreate(BaseModel):
    platform: str               # 'bilibili' | 'wechat'
    uid: str
    name: str = ""
    update_strategy: str = "select"   # 'select' | 'auto' | 'paused'
    priority: str = "normal"          # 'realtime' | 'normal' | 'low'
    content_types: list[str] = []
    custom_tags: list[str] = []


class CreatorUpdate(BaseModel):
    name: Optional[str] = None
    update_strategy: Optional[str] = None
    priority: Optional[str] = None
    content_types: Optional[list[str]] = None
    custom_tags: Optional[list[str]] = None
    enabled: Optional[int] = None


class ContentImport(BaseModel):
    creator_id: int
    platform: str = "bilibili"
    items: list[dict] = []


class BatchProcess(BaseModel):
    content_ids: list[int] = []


class SettingsUpdate(BaseModel):
    key: str
    value: str


class ClaimResolve(BaseModel):
    claim_id: int
    action: str = "confirm"     # 'confirm' | 'correct' | 'remove'
    correction: str = ""
