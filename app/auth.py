"""API-Key-Authentifizierung (X-API-Key oder Bearer-Token)."""
from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, status

from .config import settings


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    presented = x_api_key
    if presented is None and authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not presented or not secrets.compare_digest(presented, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungueltiger oder fehlender API-Key.",
            headers={"WWW-Authenticate": "Bearer"},
        )


ApiKeyDep = Depends(require_api_key)
