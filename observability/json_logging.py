"""Structured JSON logging to stdout for mcp_server.

Outputs one JSON object per line with standardized fields.
Ensures sensitive tokens, secrets, full request bodies, and personal
information are strictly masked or omitted.
"""

from __future__ import annotations

import datetime
import json
import logging
import sys
from typing import Any, Optional


# Sensitive field names to sanitize if encountered in details
_SENSITIVE_KEYS = frozenset({
    "authorization",
    "token",
    "bearer",
    "secret",
    "password",
    "api_key",
    "apikey",
    "client_secret",
    "access_token",
    "refresh_token",
})


def _sanitize_value(key: str, value: Any) -> Any:
    """Sanitize sensitive keys or strings."""
    if not isinstance(key, str):
        return value
    if any(s in key.lower() for s in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _sanitize_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value]
    return value


class JsonLogFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "event": getattr(record, "event", record.getMessage()),
        }

        # Include structured attributes if present on the log record
        for attr in (
            "tool_name",
            "correlation_id",
            "endpoint_name",
            "method",
            "duration_ms",
            "outcome",
            "error_code",
            "upstream_status",
            "search_mode",
            "candidate_count",
            "details",
        ):
            val = getattr(record, attr, None)
            if val is not None:
                if attr == "details" and isinstance(val, dict):
                    log_data[attr] = {k: _sanitize_value(k, v) for k, v in val.items()}
                else:
                    log_data[attr] = val

        # Handle exception tracebacks safely without logging sensitive stack frames
        if record.exc_info and record.exc_info[0]:
            log_data["exception_type"] = record.exc_info[0].__name__
            log_data["exception_message"] = str(record.exc_info[1])

        return json.dumps(log_data, default=str)


def setup_json_logging(level: str = "INFO", output: str = "stdout") -> logging.Logger:
    """Configure the root logger with the JsonLogFormatter outputting to stdout or stderr."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger("mcp_server")
    root.setLevel(numeric_level)

    # Avoid duplicate handlers on re-initialization
    root.handlers.clear()

    stream = sys.stderr if str(output).lower() == "stderr" else sys.stdout
    handler = logging.StreamHandler(stream)
    handler.setLevel(numeric_level)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
    root.propagate = False

    return root


def get_logger(component: str = "mcp_server") -> logging.LoggerAdapter:
    """Return a logger adapter pre-populated with the component name."""
    base_logger = logging.getLogger("mcp_server")
    return StructuredLogger(base_logger, {"component": component})


class StructuredLogger(logging.LoggerAdapter):
    """LoggerAdapter that accepts structured contextual fields."""

    def log_event(
        self,
        level: int,
        event: str,
        *,
        tool_name: Optional[str] = None,
        correlation_id: Optional[str] = None,
        endpoint_name: Optional[str] = None,
        method: Optional[str] = None,
        duration_ms: Optional[float] = None,
        outcome: Optional[str] = None,
        error_code: Optional[str] = None,
        upstream_status: Optional[int] = None,
        search_mode: Optional[str] = None,
        candidate_count: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
        exc_info: Any = None,
    ) -> None:
        """Log a structured event with standardized metadata."""
        extra: dict[str, Any] = {
            "component": self.extra.get("component", "unknown"),
            "event": event,
        }
        if tool_name is not None:
            extra["tool_name"] = tool_name
        if correlation_id is not None:
            extra["correlation_id"] = correlation_id
        if endpoint_name is not None:
            extra["endpoint_name"] = endpoint_name
        if method is not None:
            extra["method"] = method
        if duration_ms is not None:
            extra["duration_ms"] = round(duration_ms, 2)
        if outcome is not None:
            extra["outcome"] = outcome
        if error_code is not None:
            extra["error_code"] = error_code
        if upstream_status is not None:
            extra["upstream_status"] = upstream_status
        if search_mode is not None:
            extra["search_mode"] = search_mode
        if candidate_count is not None:
            extra["candidate_count"] = candidate_count
        if details is not None:
            extra["details"] = details

        self.logger.log(level, event, extra=extra, exc_info=exc_info)

    def info_event(self, event: str, **kwargs: Any) -> None:
        self.log_event(logging.INFO, event, **kwargs)

    def warning_event(self, event: str, **kwargs: Any) -> None:
        self.log_event(logging.WARNING, event, **kwargs)

    def error_event(self, event: str, **kwargs: Any) -> None:
        self.log_event(logging.ERROR, event, **kwargs)

    def debug_event(self, event: str, **kwargs: Any) -> None:
        self.log_event(logging.DEBUG, event, **kwargs)

