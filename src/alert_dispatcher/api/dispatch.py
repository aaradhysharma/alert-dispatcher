"""
HTTP layer for the dispatcher.

This file is intentionally tiny:
    - FastAPI parses the JSON body into a DispatchRequest (a Pydantic
      model in models.py). If the body is missing fields or the wrong
      types, FastAPI returns 422 automatically -- we don't write that
      code ourselves.
    - We hand the request to the service layer and return whatever it
      returns.
    - The ONLY error we translate is "unknown user" (404). Any other
      crash is a real bug and should bubble up as a 500.
"""

from fastapi import APIRouter, HTTPException

from alert_dispatcher.models import DispatchRequest, DispatchResponse
from alert_dispatcher.services.dispatch_service import UserNotFoundError
from alert_dispatcher.services.dispatch_service import dispatch as dispatch_use_case

# An APIRouter is just a "mini app" we can attach to the main FastAPI
# instance later (in main.py). Lets us split routes across files.
router = APIRouter(tags=["dispatch"])


@router.post("/v1/dispatch", response_model=DispatchResponse)
async def dispatch(req: DispatchRequest) -> DispatchResponse:
    # `req: DispatchRequest` is the magic line: FastAPI sees the type
    # annotation, parses the request body, validates it, and gives us
    # `req` already-typed. If it can't, the client gets a 422 back
    # before this function ever runs.
    try:
        return dispatch_use_case(req)
    except UserNotFoundError as exc:
        # 404 keeps the public contract from the original baseline.
        # Anything else (real bug) intentionally bubbles up to a 500.
        raise HTTPException(status_code=404, detail="unknown user") from exc


@router.get("/health")
def health() -> dict[str, str]:
    # Used by uptime checks / load balancers. No real logic here.
    return {"status": "ok"}
