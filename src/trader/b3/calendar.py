"""Agenda de eventos de alto impacto e dias bloqueados: config/b3_calendar.yaml (editado à mão)."""
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from trader.config import CONFIG_DIR, ConfigError

TZ = ZoneInfo("America/Sao_Paulo")


def load(config_dir: Path = CONFIG_DIR) -> dict:
    p = config_dir / "b3_calendar.yaml"
    if not p.exists():
        return {"events": [], "blocked_days": []}
    c = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for e in c.get("events") or []:
        try:
            datetime.strptime(f"{e['date']} {e['time']}", "%Y-%m-%d %H:%M")
        except (KeyError, TypeError, ValueError):
            raise ConfigError(f"b3_calendar.yaml: evento inválido {e!r}") from None
    return {"events": c.get("events") or [], "blocked_days": [str(d) for d in c.get("blocked_days") or []]}


def events_on(day: date, cal: dict | None = None) -> list[dict]:
    cal = cal or load()
    return [e for e in cal["events"] if str(e["date"]) == day.isoformat()]


def high_impact_times(day: date, cal: dict | None = None) -> tuple[datetime, ...]:
    return tuple(datetime.strptime(f"{e['date']} {e['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                 for e in events_on(day, cal) if e.get("impact") == "alto")


def blocked(day: date, cal: dict | None = None) -> bool:
    return day.isoformat() in (cal or load())["blocked_days"]


def next_event(now: datetime, cal: dict | None = None) -> dict | None:
    cal = cal or load()
    fut = sorted((datetime.strptime(f"{e['date']} {e['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ), e)
                 for e in cal["events"])
    return next(({**e, "at": t.isoformat(timespec="minutes")} for t, e in fut if t >= now), None)
