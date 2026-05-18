"""
HTTP endpoints to manage the in-memory mute list.

Lets operators (or curl) mute a user on a running server before calling
POST /v1/dispatch. Persistence is still in-memory only (see mute repo).
"""

from fastapi import APIRouter

from alert_dispatcher.models import MuteRequest, MuteStatusResponse
from alert_dispatcher.repositories import mute as mute_repo

router = APIRouter(tags=["mute"])


@router.post("/v1/mute", response_model=MuteStatusResponse)
def mute_user(req: MuteRequest) -> MuteStatusResponse:
    mute_repo.mute(req.user_id)
    return MuteStatusResponse(user_id=req.user_id, muted=True)


@router.post("/v1/unmute", response_model=MuteStatusResponse)
def unmute_user(req: MuteRequest) -> MuteStatusResponse:
    mute_repo.unmute(req.user_id)
    return MuteStatusResponse(user_id=req.user_id, muted=False)
