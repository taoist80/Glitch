"""Pydantic response models for Auri-specific API endpoints.

Kept separate from types.py so Auri's data model can evolve independently.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AuriChannelInfo(BaseModel):
    """A single active Auri roleplay session (SESSION_AGENT DynamoDB entry)."""

    session_id: str
    agent_id: str
    mode_id: str
    updated_at: Optional[int] = None

    @property
    def display_name(self) -> str:
        """Human-readable label derived from session_id."""
        # session_id looks like "telegram:group:123456789..." or "telegram:dm:..."
        parts = self.session_id.split(":")
        if len(parts) >= 3:
            channel_type = parts[1]
            raw_id = parts[2].rstrip("0") or parts[2]
            return f"{channel_type.capitalize()} {raw_id}"
        return self.session_id


class AuriChannelsResponse(BaseModel):
    """Response from GET /api/auri/channels."""

    channels: List[AuriChannelInfo]
    count: int


class AuriPersonaResponse(BaseModel):
    """Response from GET /api/auri/persona/core or /rules.

    Returns the raw Markdown content of the S3 persona file.
    """

    content: str


class AuriPersonaUpdate(BaseModel):
    """Request body for PUT /api/auri/persona/core or /rules."""

    content: str


class AuriPersonaSaveResponse(BaseModel):
    """Response from PUT /api/auri/persona/* endpoints."""

    saved: bool


class AuriMemoryStatsResponse(BaseModel):
    """Response from GET /api/auri/memory-stats.

    Row counts are retrieved from the protect-query Lambda (which has VPC
    access to the RDS Postgres instance where auri_memory lives).
    """

    available: bool
    memory_rows: int = 0
    profile_rows: int = 0
    total_rows: int = 0
    error: Optional[str] = None


class AuriDmUser(BaseModel):
    """A Telegram user authorized for DM access with Auri."""

    user_id: str
    display_name: Optional[str] = None


class AuriDmUsersResponse(BaseModel):
    """Response from GET /api/auri/dm-users."""

    users: List[AuriDmUser]
    count: int


class AuriProfileInfo(BaseModel):
    """A single participant profile stored in auri_memory."""

    participant_id: str
    content: str
    created_at: Optional[str] = None


class AuriProfilesResponse(BaseModel):
    """Response from GET /api/auri/profiles."""

    profiles: List[AuriProfileInfo]
    count: int


class AuriCharacterCardExtensions(BaseModel):
    """Glitch-specific extensions block inside a Character Card V2."""

    glitch_version: str = "1.0"
    source: str = "auri-core.md + auri-runtime-rules.md"


class AuriCharacterCardData(BaseModel):
    """The `data` field of a Character Card V2 export."""

    name: str = "Auri"
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    system_prompt: str = ""
    tags: List[str] = ["android", "lion", "caretaker", "auri"]
    extensions: Dict[str, Any] = {}


class AuriCharacterCardResponse(BaseModel):
    """Character Card V2 export (spec: chara_card_v2).

    Compatible with SillyTavern and KoboldCPP character import.
    See: https://github.com/malfoyslastname/character-card-spec-v2
    """

    spec: str = "chara_card_v2"
    spec_version: str = "2.0"
    data: AuriCharacterCardData = AuriCharacterCardData()
