from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            # numpy/pandas scalar that refuses .item(): fall back to a string so
            # json.dumps() can never fail on it. Returning the raw object here
            # (the previous behaviour) pushed the TypeError into the caller's
            # json.dumps and silently dropped the whole audit line.
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # Anything else (Decimal, datetime.date, custom objects) is stringified
    # rather than risking a serialization failure in the audit writer.
    return str(value)


def build_audit_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    level: str = "info",
    timestamp: str | None = None,
) -> dict[str, Any]:
    event_time = timestamp or pd.Timestamp.now(tz="Asia/Shanghai").isoformat()
    return {
        "timestamp": event_time,
        "level": level,
        "event_type": event_type,
        "run_id": run_id or event_time,
        "payload": _json_safe(payload or {}),
    }


def append_audit_event(path: str | Path, event: dict[str, Any]) -> None:
    audit_path = Path(path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_safe(event), ensure_ascii=False) + "\n")


class AuditLogger:
    def __init__(self, path: str | Path | None = None, run_id: str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.run_id = run_id or pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y%m%dT%H%M%S%z")

    def log(self, event_type: str, level: str = "info", **payload: Any) -> dict[str, Any]:
        event = build_audit_event(event_type, payload, run_id=self.run_id, level=level)
        if self.path is not None:
            append_audit_event(self.path, event)
        return event

    def info(self, event_type: str, **payload: Any) -> dict[str, Any]:
        return self.log(event_type, level="info", **payload)

    def warning(self, event_type: str, **payload: Any) -> dict[str, Any]:
        return self.log(event_type, level="warning", **payload)

    def error(self, event_type: str, **payload: Any) -> dict[str, Any]:
        return self.log(event_type, level="error", **payload)
