"""OpenTelemetry integration hooks.

Disabled by default (OTEL_ENABLED=false). When enabled, instruments
FastAPI and exports traces to the configured OTLP collector endpoint.
This module is intentionally minimal - it wires the standard
auto-instrumentation rather than hand-rolling spans, so it stays
correct as the FastAPI/SQLAlchemy instrumentation packages evolve.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def configure_tracing(app: FastAPI) -> None:
    settings = get_settings()
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource(attributes={SERVICE_NAME: settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)

        if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
            exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
            provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        logger.info("otel_tracing_configured", endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    except ImportError as exc:
        logger.warning("otel_tracing_unavailable", error=str(exc))
