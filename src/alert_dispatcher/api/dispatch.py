"""HTTP layer for the dispatcher.

This file intentionally stays thin: validation is done by Pydantic on
the request body (so a 422 with field-level details is automatic for
bad input), and everything else is one call into the service layer.

The only translation we do here is mapping `UserNotFoundError` to a
404 -- every other expected outcome (muted, no_op, partial_failure)
is a normal 200 with a structured body, so callers always parse the
same response shape.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from alert_dispatcher.models import DispatchRequest, DispatchResponse
from alert_dispatcher.services.dispatch_service import UserNotFoundError
from alert_dispatcher.services.dispatch_service import dispatch as dispatch_use_case

router = APIRouter(tags=["dispatch"])


@router.post("/v1/dispatch", response_model=DispatchResponse)
async def dispatch(req: DispatchRequest) -> DispatchResponse:
    try:
        return dispatch_use_case(req)
    except UserNotFoundError as exc:
        # 404 preserves the existing public contract from the baseline.
        raise HTTPException(status_code=404, detail="unknown user") from exc


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
