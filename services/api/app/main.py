from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import create_router
from app.domain.living_memory import JournalNarratorProvider
from app.domain.living_world import load_preset_runtime_bundle
from app.domain.models import WorldDefinition
from app.dto import ErrorDto
from app.errors import (
    DomainInvariantError,
    OcImportNotFound,
    RegisteredOcNotFound,
    RuntimeExecutionError,
    SessionNotFound,
)
from app.storage import SQLiteStorage


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


def load_world() -> WorldDefinition:
    return WorldDefinition.model_validate(
        json.loads(WORLD_PATH.read_text(encoding="utf-8"))
    )


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorDto(
            code=code,
            message=message,
            retryable=retryable,
        ).model_dump(by_alias=True),
    )


def create_app(
    storage: SQLiteStorage | None = None,
    *,
    journal_narrator: JournalNarratorProvider | None = None,
) -> FastAPI:
    runtime_storage = storage or SQLiteStorage(
        os.environ.get(
            "KALEIDOROOM_DB_PATH",
            str(Path(tempfile.gettempdir()) / "kaleidoroom-runtime.sqlite3"),
        )
    )
    app = FastAPI(title="KaleidoRoom Infinite Apartment Runtime", version="0.1.0")
    app.include_router(
        create_router(
            runtime_storage,
            load_world(),
            load_preset_runtime_bundle(),
            journal_narrator=journal_narrator,
        )
    )

    @app.exception_handler(SessionNotFound)
    async def handle_missing_session(
        _request: Request,
        _error: SessionNotFound,
    ) -> JSONResponse:
        return error_response(
            status_code=404,
            code="SESSION_NOT_FOUND",
            message="Session not found.",
            retryable=False,
        )

    @app.exception_handler(OcImportNotFound)
    async def handle_missing_oc_import(
        _request: Request,
        _error: OcImportNotFound,
    ) -> JSONResponse:
        return error_response(
            status_code=404,
            code="OC_IMPORT_NOT_FOUND",
            message="OC import draft not found.",
            retryable=False,
        )

    @app.exception_handler(RegisteredOcNotFound)
    async def handle_missing_registered_oc(
        _request: Request,
        _error: RegisteredOcNotFound,
    ) -> JSONResponse:
        return error_response(
            status_code=404,
            code="REGISTERED_OC_NOT_FOUND",
            message="Registered OC not found.",
            retryable=False,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_invalid_request(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            status_code=422,
            code="INVALID_REQUEST",
            message="Request validation failed.",
            retryable=False,
        )

    @app.exception_handler(RuntimeExecutionError)
    async def handle_runtime_execution_error(
        _request: Request,
        _error: RuntimeExecutionError,
    ) -> JSONResponse:
        return error_response(
            status_code=500,
            code="RUNTIME_EXECUTION_FAILED",
            message="Runtime execution failed.",
            retryable=True,
        )

    @app.exception_handler(DomainInvariantError)
    async def handle_domain_invariant_error(
        _request: Request,
        _error: DomainInvariantError,
    ) -> JSONResponse:
        return error_response(
            status_code=409,
            code="DOMAIN_INVARIANT_VIOLATION",
            message="Domain invariant violation.",
            retryable=False,
        )

    @app.exception_handler(Exception)
    async def handle_internal_error(
        _request: Request,
        _error: Exception,
    ) -> JSONResponse:
        return error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="Internal server error.",
            retryable=True,
        )

    return app


app = create_app()
