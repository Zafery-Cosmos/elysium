"""Choose where Elysium keeps its data: local SQLite or a PostgreSQL server.

The active connection cannot be swapped under running requests, so saving takes
effect at the next start. The URL goes to the keychain and never comes back.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from elysium_engine.db.external import (
    SECRET_NAME,
    DatabaseConfigError,
    check_connection,
    describe,
    normalize_url,
    prepare,
)

router = APIRouter(prefix="/admin/database", tags=["database"])


class DatabaseUrlIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class DatabaseSaveIn(DatabaseUrlIn):
    copy_data: bool = False


def _bad_request(exc: DatabaseConfigError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("")
def get_database(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    stored = request.app.state.secret_store.get(SECRET_NAME)
    return {
        "backend": engine.dialect.name,
        "location": describe(engine.url.render_as_string(hide_password=False)),
        "configured": describe(stored) if stored else None,
        "fallback_error": request.app.state.db_fallback_error,
    }


@router.post("/test")
def test_database(body: DatabaseUrlIn) -> dict[str, str]:
    try:
        return {"version": check_connection(normalize_url(body.url))}
    except DatabaseConfigError as exc:
        raise _bad_request(exc) from exc


@router.put("")
def save_database(body: DatabaseSaveIn, request: Request) -> dict[str, Any]:
    """Prepare the server and remember it. Applies at the next start."""
    try:
        url = normalize_url(body.url)
        check_connection(url)
        copied = prepare(url, request.app.state.engine if body.copy_data else None)
    except DatabaseConfigError as exc:
        raise _bad_request(exc) from exc
    request.app.state.secret_store.set(SECRET_NAME, url)
    return {"copied_rows": copied, "restart_required": True}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def forget_database(request: Request) -> Response:
    """Back to the local database at the next start; the server keeps its data."""
    request.app.state.secret_store.delete(SECRET_NAME)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
