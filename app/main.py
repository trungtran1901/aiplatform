"""
Agno Runtime Platform - application entrypoint.

This service is responsible ONLY for: agent orchestration, agent
management/registry, team management, prompt management, skill
management, session management, memory management, agent observability,
and MCP tool discovery/execution.

It is explicitly NOT responsible for RBAC, authorization, permission
enforcement, workflow execution, or ERP/CRM integration - those belong to
MCP Gateway. See app/core/auth_context.py and app/agno_runtime/mcp_client.py
for the auth-propagation contract.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AgnoRuntimeError
from app.core.logging import configure_logging, correlation_id_var, get_logger
from app.core.middleware import RequestContextMiddleware
from app.observability.health import router as health_router

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("agno_runtime_starting", app_env=settings.APP_ENV, version=settings.APP_VERSION)

    if settings.OTEL_ENABLED:
        from app.observability.tracing import configure_tracing

        configure_tracing(app)

    yield
    logger.info("agno_runtime_shutting_down")


app = FastAPI(
    title="Agno Runtime Platform",
    description=(
        "Metadata-driven agent orchestration runtime. Agent Orchestration, "
        "Agent/Team/Prompt/Skill Management, Session & Memory Management, "
        "Observability, and MCP Tool Discovery/Execution. "
        "Authorization, RBAC, and workflow execution are delegated entirely "
        "to MCP Gateway."
    ),
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AgnoRuntimeError)
async def agno_runtime_error_handler(request: Request, exc: AgnoRuntimeError) -> JSONResponse:
    logger.error(
        "request_failed",
        error_code=exc.error_code,
        message=exc.message,
        path=str(request.url.path),
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "correlation_id": correlation_id_var.get(),
        },
    )


app.include_router(health_router)
app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
