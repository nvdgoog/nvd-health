from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.health_agent import HealthAnalystService

router = APIRouter(prefix="/api/analyst", tags=["analyst"])
_service = HealthAnalystService()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    user_id: str = "default-user"


@router.post("/chat")
async def chat_with_health_analyst(payload: ChatRequest) -> Dict[str, Any]:
    try:
        return await _service.ask(
            message=payload.message,
            session_id=payload.session_id,
            user_id=payload.user_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AI Health Analyst execution error: {exc}",
        ) from exc
