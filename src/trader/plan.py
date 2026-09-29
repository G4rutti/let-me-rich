"""Plano do dia do WIN: schema fechado, validação, revisões que só reduzem risco e o motor de gatilhos.

O operador (LLM) escreve o plano; o executor (Python) avalia gatilhos só em fechamento de barra.
Nada de expressão livre: tipos de gatilho enumerados, níveis só de LEVEL_REFS ou preço absoluto.
"""
import json
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from trader.b3.config import hhmm
from trader.b3.features import LEVEL_REFS
from trader.broker.base import Bar
from trader.db import now_iso

LevelRef = Literal[LEVEL_REFS]
HHMM = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Short = Annotated[str, Field(max_length=300)]
TRIGGERS = ("close_above", "close_below", "touch_and_reject", "pullback_to", "break_and_retest")
RISK_ORDER = {"fora": 0, "reduzido": 1, "normal": 2}


class PlanError(Exception):
    def __init__(self, code: str, hint: str):
        super().__init__(f"{code}: {hint}")
        self.code, self.hint = code, hint


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class _Ref(_M):
    level_ref: LevelRef | None = None
    price: Annotated[float, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _one(self):
        if (self.level_ref is None) == (self.price is None):
            raise ValueError("informe exatamente um entre level_ref e price")
        return self


class Trigger(_Ref):
    type: Literal[TRIGGERS]
    timeframe: Literal["1m", "5m", "15m"] = "5m"


class Window(_M):
    from_: HHMM = Field(alias="from")
    to: HHMM


class Stop(_M):
    type: Literal["level", "points", "atr"]
    level_ref: LevelRef | None = None
    price: Annotated[float, Field(gt=0)] | None = None
    offset_ticks: Annotated[int, Field(ge=0, le=20)] = 0
    value: Annotated[float, Field(gt=0, le=1000)] | None = None      # pontos (points) ou múltiplo do ATR5m (atr)

    @model_validator(mode="after")
    def _shape(self):
        if self.type == "level" and (self.level_ref is None) == (self.price is None):
            raise ValueError("stop level exige exatamente um entre level_ref e price")
        if self.type in ("points", "atr") and (self.value is None or self.level_ref or self.price):
            raise ValueError(f"stop {self.type} exige só value")
        return self


class Target(_M):
    type: Literal["r_multiple", "level"]
    value: Annotated[float, Field(gt=0, le=10)] | None = None
    level_ref: LevelRef | None = None
    price: Annotated[float, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _shape(self):
        if self.type == "r_multiple" and (self.value is None or self.level_ref or self.price):
            raise ValueError("target r_multiple exige só value")
        if self.type == "level" and (self.level_ref is None) == (self.price is None):
            raise ValueError("target level exige exatamente um entre level_ref e price")
        return self


class Invalidation(_Ref):
    type: Literal["price_above", "price_below"]
    timeframe: Literal["1m", "5m", "15m"] = "5m"


class BearReview(_M):
    verdict: Literal["OK", "SEM_VETO", "VETO"]
    strength: Annotated[int, Field(ge=1, le=5)]
    points: Annotated[list[Short], Field(max_length=6)] = []


class Setup(_M):
    id: Annotated[str, Field(pattern=r"^s\d{1,2}$")]
    setup: Annotated[str, Field(pattern=r"^[a-z0-9_]{3,40}$")]
    direction: Literal["long", "short"]
    trigger: Trigger
    window: Window
    stop: Stop
    target: Target
    invalidation: Annotated[list[Invalidation], Field(max_length=4)] = []
    max_entries: Annotated[int, Field(ge=1, le=2)] = 1
    active: bool = True
    bull_case: Annotated[str, Field(max_length=600)] = ""
    bear_review: BearReview


class Level(_M):
    name: Annotated[str, Field(max_length=40)]
    price: float | None = None
    ref: LevelRef | None = None


class Plan(_M):
    date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    bias: Literal["long", "short", "neutral"]
    risk_level: Literal["normal", "reduzido", "fora"]
    summary: Annotated[str, Field(max_length=800)]
    levels: Annotated[list[Level], Field(max_length=20)] = []
    setups: Annotated[list[Setup], Field(max_length=6)] = []


# ---------------------------------------------------------------- validação

def validate_plan(raw: dict, cfg, today: date) -> dict:
    try:
        p = Plan.model_validate(raw)
    except ValidationError as e:
        raise PlanError("SCHEMA", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())[:600]) from None
    if p.date != today.isoformat():
        raise PlanError("WRONG_DATE", f"plano para {p.date}, hoje é {today}")
    s, r = cfg["session"], cfg["risk"]
    open_, close = hhmm(s["no_entry_before"]), hhmm(s["no_entry_after"])
    ids = [x.id for x in p.setups]
    if len(ids) != len(set(ids)):
        raise PlanError("DUPLICATE_ID", "ids de setup repetidos")
    stop_max = cfg["reduced_day"]["stop_max_points"] if p.risk_level == "reduzido" else r["stop_max_points"]
    for x in p.setups:
        w0, w1 = hhmm(x.window.from_), hhmm(x.window.to)
        if not (open_ <= w0 < w1 <= close):
            raise PlanError("BAD_WINDOW", f"{x.id}: janela {x.window.from_}-{x.window.to} fora de "
                                          f"{s['no_entry_before']}-{s['no_entry_after']}")
        if x.bear_review.verdict == "VETO" or x.bear_review.strength >= 4:
            raise PlanError("BEAR_VETO", f"{x.id}: veto do bear (força {x.bear_review.strength}); retire o setup")
        if x.stop.type == "points" and not (r["stop_min_points"] <= x.stop.value <= stop_max):
            raise PlanError("STOP_POINTS", f"{x.id}: stop de {x.stop.value} pts fora de {r['stop_min_points']}-{stop_max}")
        if x.stop.type == "atr" and x.stop.value > r["max_stop_atr"]:
            raise PlanError("STOP_ATR", f"{x.id}: stop {x.stop.value} ATR > {r['max_stop_atr']}")
        if x.target.type == "r_multiple" and x.target.value < r["min_rr"]:
            raise PlanError("RR_TOO_LOW", f"{x.id}: alvo {x.target.value}R < {r['min_rr']}R")
        if p.risk_level == "reduzido" and cfg["reduced_day"]["only_with_bias"] and x.active and x.direction != p.bias:
            raise PlanError("AGAINST_BIAS", f"{x.id}: dia reduzido só aceita setups a favor do bias ({p.bias})")
    return p.model_dump(by_alias=True)


def _setup_map(plan: dict) -> dict:
    return {s["id"]: s for s in plan["setups"]}


def validate_revision(old: dict, raw: dict, cfg, today: date) -> dict:
    """Revisão só reduz risco: desativa, estreita janela, aperta stop, reduz risk_level. Setup novo com bear_review."""
    new = validate_plan(raw, cfg, today)
    if RISK_ORDER[new["risk_level"]] > RISK_ORDER[old["risk_level"]]:
        raise PlanError("REVISION_ADDS_RISK", f"risk_level {old['risk_level']} -> {new['risk_level']} aumenta risco")
    if new["bias"] != old["bias"] and new["bias"] != "neutral":
        raise PlanError("REVISION_ADDS_RISK", f"bias {old['bias']} -> {new['bias']}: só pode virar neutral")
    olds, news = _setup_map(old), _setup_map(new)
    for sid, n in news.items():
        o = olds.get(sid)
        if o is None:
            continue                                  # setup novo: já passou pelo schema com bear_review próprio
        for k in ("setup", "direction", "trigger", "target"):
            if n[k] != o[k]:
                raise PlanError("REVISION_ADDS_RISK", f"{sid}: {k} não pode mudar numa revisão (crie outro setup)")
        if n["active"] and not o["active"]:
            raise PlanError("REVISION_ADDS_RISK", f"{sid}: setup desativado não volta")
        if n["max_entries"] > o["max_entries"]:
            raise PlanError("REVISION_ADDS_RISK", f"{sid}: max_entries só diminui")
        if n["window"]["from"] < o["window"]["from"] or n["window"]["to"] > o["window"]["to"]:
            raise PlanError("REVISION_ADDS_RISK", f"{sid}: janela só estreita")
        if not all(i in n["invalidation"] for i in o["invalidation"]):
            raise PlanError("REVISION_ADDS_RISK", f"{sid}: invalidações existentes não podem sair")
        if not _stop_tighter_or_equal(o["stop"], n["stop"]):
            raise PlanError("REVISION_ADDS_RISK", f"{sid}: stop só pode apertar (mesmo tipo e referência)")
    return new


def _stop_tighter_or_equal(o: dict, n: dict) -> bool:
    if n == o:
        return True
    if n["type"] != o["type"] or n.get("level_ref") != o.get("level_ref") or n.get("price") != o.get("price"):
        return False
    if n["type"] == "level":
        return n["offset_ticks"] <= o["offset_ticks"]
    return n["value"] <= o["value"]


# ---------------------------------------------------------------- persistência

def save_plan(conn, plan: dict, kind: str, cycle_id: str | None = None) -> int:
    v = conn.execute("SELECT COALESCE(MAX(version),0)+1 v FROM b3_plans WHERE day=?", (plan["date"],)).fetchone()["v"]
    conn.execute("INSERT INTO b3_plans (day, version, kind, created_at, cycle_id, plan_json) VALUES (?,?,?,?,?,?)",
                 (plan["date"], v, kind, now_iso(), cycle_id, json.dumps(plan, ensure_ascii=False)))
    return v


def active_plan(conn, day: str) -> dict | None:
    row = conn.execute("SELECT version, plan_json FROM b3_plans WHERE day=? ORDER BY version DESC LIMIT 1",
                       (day,)).fetchone()
    return {**json.loads(row["plan_json"]), "version": row["version"]} if row else None


# ---------------------------------------------------------------- motor de gatilhos (puro)

def ref_price(obj: dict, levels: dict) -> float | None:
    return obj["price"] if obj.get("price") is not None else levels.get(obj.get("level_ref"))


def in_window(setup: dict, now: time) -> bool:
    return hhmm(setup["window"]["from"]) <= now < hhmm(setup["window"]["to"])


def fired(setup: dict, closed: list[Bar], levels: dict, tick: float) -> bool:
    """Avalia a ÚLTIMA barra fechada do timeframe do gatilho."""
    tr = setup["trigger"]
    L = ref_price(tr, levels)
    if L is None or len(closed) < 2:
        return False
    last, prev = closed[-1], closed[-2]
    c, o, h, lo, pc = float(last.close), float(last.open), float(last.high), float(last.low), float(prev.close)
    long_ = setup["direction"] == "long"
    t = tr["type"]
    if t == "close_above":
        return c > L >= pc
    if t == "close_below":
        return c < L <= pc
    if t == "touch_and_reject":
        return (lo <= L < c and c > o) if long_ else (h >= L > c and c < o)
    before = closed[-13:-1]
    if t == "pullback_to":   # vinha do lado certo, encostou no nível e fechou a favor
        if long_:
            return min(float(b.low) for b in closed[-4:-1]) > L and lo <= L + tick and c > L and c > o
        return max(float(b.high) for b in closed[-4:-1]) < L and h >= L - tick and c < L and c < o
    if t == "break_and_retest":   # rompeu nas barras anteriores e voltou para testar
        closes = [float(b.close) for b in before]
        broke = any(a <= L < b for a, b in zip(closes, closes[1:])) if long_ else \
            any(a >= L > b for a, b in zip(closes, closes[1:]))
        return broke and ((lo <= L + tick and c > L) if long_ else (h >= L - tick and c < L))
    return False


def invalidated(inv: dict, closed: list[Bar], levels: dict) -> bool:
    L = ref_price(inv, levels)
    if L is None or not closed:
        return False
    c = float(closed[-1].close)
    return c > L if inv["type"] == "price_above" else c < L


def stop_target(setup: dict, entry: float, levels: dict, atr5m: float | None, tick: float) -> tuple[float, float] | None:
    """Preços de stop e alvo para uma entrada em `entry`. None se a referência não existe agora."""
    long_ = setup["direction"] == "long"
    st = setup["stop"]
    if st["type"] == "level":
        L = ref_price(st, levels)
        if L is None:
            return None
        stop = L - st["offset_ticks"] * tick if long_ else L + st["offset_ticks"] * tick
    elif st["type"] == "points":
        stop = entry - st["value"] if long_ else entry + st["value"]
    else:
        if not atr5m:
            return None
        stop = entry - st["value"] * atr5m if long_ else entry + st["value"] * atr5m
    tg = setup["target"]
    if tg["type"] == "r_multiple":
        target = entry + tg["value"] * abs(entry - stop) * (1 if long_ else -1)
    else:
        target = ref_price(tg, levels)
        if target is None:
            return None
    return stop, target


def rule_plan(day: date) -> dict:
    """Plano fixo da sombra_regra: rompimento do opening range 30 min nos dois sentidos, sem LLM e sem macro."""
    def orb(sid, direction, trig, ref):
        return {"id": sid, "setup": "opening_range_breakout", "direction": direction,
                "trigger": {"type": trig, "timeframe": "5m", "level_ref": ref, "price": None},
                "window": {"from": "09:30", "to": "12:00"},
                "stop": {"type": "points", "level_ref": None, "price": None, "offset_ticks": 0, "value": 100},
                "target": {"type": "r_multiple", "value": 2.0, "level_ref": None, "price": None},
                "invalidation": [], "max_entries": 1, "active": True, "bull_case": "regra fixa",
                "bear_review": {"verdict": "OK", "strength": 1, "points": []}}
    return {"date": day.isoformat(), "bias": "neutral", "risk_level": "normal", "summary": "sombra_regra",
            "levels": [], "setups": [orb("s1", "long", "close_above", "or30_high"),
                                     orb("s2", "short", "close_below", "or30_low")], "version": 0}
