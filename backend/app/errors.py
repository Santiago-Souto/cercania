"""API error shape shared by every route: `{"error": {"code", "message"}}` (docs/contract.md).

Routes `raise api_error(...)`; handlers installed by `install_error_handlers` turn it into the
contract body. Messages shown to users are in Spanish (rioplatense).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        """Errors raised by dependencies use the contract's `{error: {code, message}}` shape."""
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
        return error_response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo the submitted values (they may be health data); the UI gets a fixed message.
        return error_response(422, "invalid_request", "Revisá los datos enviados.")
