"""FastAPI application: the POST /posting endpoint, a platform listing and the web console."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import Settings, get_settings
from app.logging_config import configure_logging
from app.platforms import PLATFORM_CLASSES
from app.schemas import ErrorResponse, PlatformInfo, PostingResponse, PostRequest
from app.services.posting_service import PostingService, build_service

logger = logging.getLogger("posting.api")

STATIC_DIR = Path(__file__).parent / "static"

API_DESCRIPTION = """
Publishes one short message to several third-party platforms through their official APIs.

* **Validation**: at most 200 characters, exactly one call-to-action link, and that link must be a public http(s) URL.
* **Platform selection** is handled by the server: every integration whose credentials are set is used.
* **Isolation**: platforms run concurrently and independently, so one failure never stops the others.
"""


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level, settings.log_file)
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            service = build_service(settings, client)
            app.state.service = service
            logger.info(
                "ready platforms=%s skipped=%s",
                ",".join(p.name for p in service.platforms) or "none",
                ",".join(s.platform for s in service.skipped) or "none",
            )
            yield

    app = FastAPI(
        title="Automated Multi-Platform Posting API",
        version=__version__,
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings

    _register_error_handlers(app)
    _register_routes(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _register_routes(app: FastAPI) -> None:
    @app.post(
        "/posting",
        response_model=PostingResponse,
        tags=["Posting"],
        summary="Publish a message to every configured platform",
        responses={
            200: {"description": "At least one platform published the message"},
            422: {"model": ErrorResponse, "description": "The message failed validation"},
            502: {"model": PostingResponse, "description": "Every platform failed"},
            503: {"model": ErrorResponse, "description": "No platform is configured"},
        },
    )
    async def create_posting(payload: PostRequest, request: Request):
        service: PostingService = request.app.state.service
        if not service.platforms:
            return _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "no_platforms",
                "No platform is configured. Add credentials to .env (see .env.example).",
            )

        result = await service.publish(payload.message, payload.cta_link)
        code = status.HTTP_200_OK if result.success else status.HTTP_502_BAD_GATEWAY
        return JSONResponse(status_code=code, content=result.model_dump())

    @app.get("/platforms", response_model=List[PlatformInfo], tags=["Posting"], summary="List integrations")
    async def list_platforms(request: Request):
        settings: Settings = request.app.state.settings
        enabled_keys = settings.enabled_platform_keys
        return [
            PlatformInfo(
                key=cls.key,
                name=cls.name,
                configured=cls.is_configured(settings),
                missing=cls.missing_settings(settings),
                docs_url=cls.docs_url,
                enabled=enabled_keys is None or cls.key in enabled_keys,
            )
            for cls in PLATFORM_CLASSES
        ]

    @app.get("/health", tags=["Meta"], summary="Liveness check")
    async def health() -> Dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    async def console() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [_describe_validation_error(error) for error in exc.errors()]
        return _error(
            422,
            "validation_error",
            details[0]["message"] if details else "Invalid request.",
            details,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "Something went wrong on the server.")


def _describe_validation_error(error: Dict[str, Any]) -> Dict[str, str]:
    loc = [str(part) for part in error.get("loc", ()) if part != "body"]
    field = ".".join(loc) or "body"
    kind = error.get("type", "invalid")

    if kind == "extra_forbidden":
        message = (
            f"Unknown field '{field}'. Platforms are selected by the server, so send only 'message'."
        )
    elif kind == "missing":
        message = "The 'message' field is required." if field == "message" else "The request body is required."
    elif kind == "json_invalid":
        field = "body"
        message = "The request body is not valid JSON."
    elif kind in ("model_attributes_type", "dict_type"):
        message = 'The request body must be a JSON object like {"message": "..."}.'
    else:
        message = error.get("msg", "Invalid value.")
    return {"field": field, "code": kind, "message": message}


def _error(code: int, error_code: str, message: str, details: Optional[List[Dict[str, str]]] = None) -> JSONResponse:
    body = ErrorResponse(error={"code": error_code, "message": message, "details": details or []})
    return JSONResponse(status_code=code, content=body.model_dump())


app = create_app()
