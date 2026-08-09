"""FastAPI application factory.

Routes stay thin on purpose: validate, resolve identity, delegate to a service.
No business logic, no SQL, no model calls in this layer.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger, request_id_var

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    logger.info(
        "startup",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        database=settings.safe_database_url,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
        llm_model=settings.anthropic_model,
        llm_configured=settings.llm_configured,
    )
    if not settings.llm_configured:
        # Not fatal: retrieval and evaluation of retrieval work fine without a
        # key. Only the generation layer needs it.
        logger.warning(
            "llm_not_configured",
            detail="ANTHROPIC_API_KEY is unset or still a placeholder; "
            "/api/v1/query will return 503 until it is set in .env",
        )

    yield

    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Permission-aware enterprise RAG platform. "
            "Hybrid retrieval (BM25 + dense vectors) with reciprocal rank fusion, "
            "ACL enforcement inside the retrieval query, and citation-grounded generation."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Assign (or accept) a request id, bind it to the log context, and
        record wall-clock latency for every request."""
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            request_id_var.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        # Health probes fire every few seconds; logging them at INFO would bury
        # everything else.
        if request.url.path not in {"/healthz", "/readyz"}:
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                request_id=request_id,
            )
        return response

    register_exception_handlers(app)

    app.include_router(health.router)
    # Ingestion, search, and query routers land Saturday and Sunday under
    # settings.api_v1_prefix.

    return app


app = create_app()
