"""Token history for the Silvia dashboard usage page.

Totals, source split, inherited-turn dedupe, and the shared zoom window are
pure functions of ledger records. The loader asks `grok usage` for each local
session that has a ledger and caches that JSON so a later read does not spawn
a process per session.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

GROK = Path.home() / ".grok"
SESSIONS = GROK / "sessions"
GROK_EXE = GROK / "bin" / "grok.exe"
CACHE_PATH = GROK / "silvia-dashboard" / "state" / "token-history.json"


def _no_console() -> dict[str, int]:
    """pythonw has no console, so a console child would open its own window."""
    if os.name != "nt":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}

# Voice and bots are always listed. A missing ledger stays unknown.
REQUIRED_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("tui", "TUI", "#3DDC97"),
    ("bots", "bots", "#F0A202"),
    ("voice", "voice", "#7AA2FF"),
)
EXTRA_COLORS = (
    ("subagents", "subagents", "#FF6B6B"),
    ("headless", "headless", "#C77DFF"),
    ("other", "other", "#E8E6D8"),
)
_COLOR_MAP = {sid: color for sid, _label, color in (*REQUIRED_SOURCES, *EXTRA_COLORS)}
_LABEL_MAP = {sid: label for sid, label, _color in (*REQUIRED_SOURCES, *EXTRA_COLORS)}
_SOURCE_ALIASES = {
    "tui": "tui",
    "bots": "bots",
    "bot": "bots",
    "voice": "voice",
    "subagents": "subagents",
    "subagent": "subagents",
    "headless": "headless",
    "other": "other",
}

_LOCK = threading.Lock()
_MEM: dict[str, Any] = {"sig": None, "report": None}

# Trees checked once per process for a token ledger outside grok sessions.
_EXTERNAL_ROOTS = (
    (Path(r"C:\Users\Irika\si-butler"), "voice"),
    (GROK / "silvia", "voice"),
    (GROK / "silvia-android", "voice"),
    (GROK / "grok-bot-roster", "bots"),
)
_EXTERNAL_SCANNED = False
_EXTERNAL_RECORDS: list[dict[str, Any]] = []


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    if "." in text:
        head, rest = text.split(".", 1)
        digits: list[str] = []
        index = 0
        while index < len(rest) and rest[index].isdigit():
            digits.append(rest[index])
            index += 1
        frac = "".join(digits[:6])
        text = f"{head}.{frac}{rest[index:]}" if frac else f"{head}{rest[index:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def hour_start(moment: datetime) -> datetime:
    moment = moment.astimezone(timezone.utc)
    return moment.replace(minute=0, second=0, microsecond=0)


def classify_source(record: dict[str, Any]) -> str:
    """Voice, bots, and TUI come from the record. Anything else is named or other."""
    for key in ("source", "client"):
        raw = str(record.get(key) or "").strip().lower()
        if raw in _SOURCE_ALIASES:
            return _SOURCE_ALIASES[raw]
        if "voice" in raw:
            return "voice"
        if "bot" in raw:
            return "bots"
    kind = str(record.get("session_kind") or "").strip().lower()
    if kind.startswith("subagent"):
        return "subagents"
    if kind == "headless":
        return "headless"
    if kind in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[kind]
    if record.get("session_id") or record.get("turns"):
        return "tui"
    return "other"


def _turn_tokens(turn: dict[str, Any]) -> int | None:
    if "total_tokens" in turn:
        return _int(turn.get("total_tokens"))
    return _int(turn.get("totalTokens"))


def _present_int(obj: dict[str, Any], *keys: str) -> int | None:
    """A missing field stays missing. Zero is a real count."""
    for key in keys:
        if key in obj and obj.get(key) is not None:
            return _int(obj.get(key))
    return None


def spendable_turns(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Drop an incomplete ledger and an all-zero ledger. Keep positive turns."""
    if record.get("ledger") is False:
        return []
    if record.get("usage_incomplete") or record.get("usageIsIncomplete"):
        return []
    raw_turns = record.get("turns") if isinstance(record.get("turns"), list) else []
    turns: list[dict[str, Any]] = []
    for turn in raw_turns:
        if not isinstance(turn, dict):
            continue
        if turn.get("usage_incomplete") or turn.get("usageIsIncomplete"):
            continue
        tokens = _turn_tokens(turn)
        if tokens is None:
            continue
        ended = turn.get("ended_at") or turn.get("endedAt")
        number = turn.get("turn") if "turn" in turn else turn.get("turnNumber")
        turns.append(
            {
                "turn": number,
                "ended_at": str(ended).strip() if ended else "",
                "total_tokens": tokens,
                "input_tokens": _present_int(turn, "input_tokens", "inputTokens"),
                "output_tokens": _present_int(turn, "output_tokens", "outputTokens"),
                "cached_tokens": _present_int(turn, "cached_tokens", "cachedReadTokens", "cached_read_tokens"),
                "model": str(turn.get("model") or turn.get("primaryModelId") or turn.get("primary_model") or "").strip(),
            }
        )
    if not turns:
        total = _int(record.get("total_tokens"))
        if total is None:
            total = _int(record.get("totalTokens"))
        ended = record.get("updated_at") or record.get("updatedAt") or record.get("ended_at")
        if total is not None and total > 0 and ended and not (
            record.get("usage_incomplete") or record.get("usageIsIncomplete")
        ):
            return [
                {
                    "turn": None,
                    "ended_at": str(ended).strip(),
                    "total_tokens": total,
                    "input_tokens": _present_int(record, "input_tokens", "inputTokens"),
                    "output_tokens": _present_int(record, "output_tokens", "outputTokens"),
                    "cached_tokens": _present_int(record, "cached_tokens", "cachedReadTokens", "cached_read_tokens"),
                    "model": str(record.get("model") or record.get("primaryModelId") or record.get("primary_model") or "").strip(),
                }
            ]
        return []
    if all(turn["total_tokens"] == 0 for turn in turns):
        return []
    return [turn for turn in turns if turn["total_tokens"] > 0]


def _session_id(record: dict[str, Any]) -> str:
    return str(record.get("session_id") or record.get("sessionId") or "")


def _parent_id(record: dict[str, Any]) -> str:
    return str(record.get("parent_session_id") or record.get("parentSessionId") or "")


def _family_and_depth(records: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, int]]:
    parent_of = {_session_id(row): _parent_id(row) for row in records if _session_id(row)}
    family: dict[str, str] = {}
    depth: dict[str, int] = {}
    for sid in parent_of:
        seen: list[str] = []
        guard: set[str] = set()
        cur = sid
        while cur and cur not in guard:
            guard.add(cur)
            seen.append(cur)
            cur = parent_of.get(cur) or ""
        root = seen[-1] if seen else sid
        for index, item in enumerate(reversed(seen)):
            family[item] = root
            depth[item] = index
    return family, depth


def count_events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per turn. A resume or fork that repeats a parent turn counts once."""
    prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        turns = spendable_turns(record)
        if not turns:
            continue
        prepared.append((record, turns))
    family, depth = _family_and_depth([row for row, _turns in prepared])
    ordered = sorted(
        prepared,
        key=lambda item: (depth.get(_session_id(item[0]), 0), _session_id(item[0])),
    )
    seen: set[tuple[str, Any, str]] = set()
    events: list[dict[str, Any]] = []
    for record, turns in ordered:
        sid = _session_id(record)
        source = classify_source(record)
        root = family.get(sid, sid or source)
        for turn in turns:
            ended = turn["ended_at"]
            if ended:
                key = (root, turn["turn"], ended)
            else:
                key = (root, sid, f"notime:{turn['turn']}")
            if key in seen:
                continue
            moment = parse_time(ended)
            if moment is None:
                continue
            seen.add(key)
            events.append(
                {
                    "session_id": sid,
                    "source": source,
                    "turn": turn["turn"],
                    "ended_at": ended,
                    "tokens": turn["total_tokens"],
                    "input_tokens": turn.get("input_tokens"),
                    "output_tokens": turn.get("output_tokens"),
                    "cached_tokens": turn.get("cached_tokens"),
                    "model": turn.get("model") or "",
                    "at": moment.timestamp(),
                }
            )
    events.sort(key=lambda row: (row["at"] is None, row["at"] or 0, str(row["session_id"]), str(row["turn"])))
    return events


def _window_bounds(events: list[dict[str, Any]], preset: str) -> dict[str, Any]:
    moments = [datetime.fromtimestamp(row["at"], timezone.utc) for row in events if row.get("at") is not None]
    if not moments:
        return {"preset": preset, "start": None, "end": None}
    earliest = hour_start(min(moments))
    latest_end = hour_start(max(moments)) + timedelta(hours=1)
    if preset == "hour":
        start = hour_start(max(moments))
        end = start + timedelta(hours=1)
    elif preset == "day":
        end = latest_end
        start = end - timedelta(hours=24)
        if start < earliest:
            start = earliest
    else:
        preset = "all"
        start = earliest
        end = latest_end
    return {"preset": preset, "start": iso_z(start), "end": iso_z(end)}


def window_for_preset(events: list[dict[str, Any]], preset: str) -> dict[str, Any]:
    return _window_bounds(events, preset if preset in {"all", "day", "hour"} else "all")


def _in_window(event: dict[str, Any], start: datetime | None, end: datetime | None) -> bool:
    if event.get("at") is None:
        return start is None and end is None
    moment = datetime.fromtimestamp(event["at"], timezone.utc)
    if start is not None and moment < start:
        return False
    if end is not None and moment >= end:
        return False
    return True


def _source_row(source_id: str, tokens: int | None, known: bool) -> dict[str, Any]:
    return {
        "id": source_id,
        "label": _LABEL_MAP.get(source_id, source_id),
        "tokens": tokens if known else None,
        "known": known,
        "color": _COLOR_MAP.get(source_id, "#E8E6D8"),
    }


def _extra_color(source_id: str, used: set[str]) -> str:
    if source_id in _COLOR_MAP and _COLOR_MAP[source_id] not in used:
        return _COLOR_MAP[source_id]
    palette = ("#5AD1C4", "#F2C14E", "#9B5DE5", "#F15BB5", "#00BBF9", "#FEE440")
    for color in palette:
        if color not in used:
            return color
    return "#FFFFFF"


def _side_sum(rows: list[dict[str, Any]], key: str) -> int:
    """Sum one side. A turn with no field for that side adds nothing."""
    total = 0
    for row in rows:
        if key not in row or row.get(key) is None:
            continue
        value = _int(row.get(key))
        if value is None:
            continue
        total += value
    return total


def report_from_events(
    events: list[dict[str, Any]],
    *,
    window: dict[str, Any] | None = None,
    preset: str | None = None,
    plans: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    """Build totals and both chart series for one shared window."""
    rows = [row for row in events if isinstance(row, dict)]
    if window is None:
        window = window_for_preset(rows, preset or "all")
    start = parse_time(window.get("start"))
    end = parse_time(window.get("end"))
    if start is None and end is None and rows and any(row.get("at") is not None for row in rows):
        window = window_for_preset(rows, preset or str(window.get("preset") or "all"))
        start = parse_time(window.get("start"))
        end = parse_time(window.get("end"))
    shown = [row for row in rows if _in_window(row, start, end)]
    known_ids = {str(row.get("source") or "other") for row in rows if row.get("tokens")}
    totals: dict[str, int] = {}
    sessions: dict[str, dict[str, Any]] = {}
    for row in shown:
        source = str(row.get("source") or "other")
        tokens = _int(row.get("tokens")) or 0
        totals[source] = totals.get(source, 0) + tokens
        sid = str(row.get("session_id") or "")
        if not sid:
            continue
        slot = sessions.setdefault(sid, {"id": sid, "source": source, "tokens": 0})
        slot["tokens"] += tokens
        slot["source"] = source
    input_tokens = _side_sum(shown, "input_tokens")
    output_tokens = _side_sum(shown, "output_tokens")
    order: list[str] = [sid for sid, _label, _color in REQUIRED_SOURCES]
    for source in sorted(set(totals) | known_ids):
        if source not in order:
            order.append(source)
    used_colors: set[str] = set()
    sources: list[dict[str, Any]] = []
    for source in order:
        if source not in _LABEL_MAP:
            _LABEL_MAP[source] = source
        color = _COLOR_MAP.get(source) or _extra_color(source, used_colors)
        if color in used_colors:
            color = _extra_color(source + color, used_colors)
        _COLOR_MAP[source] = color
        used_colors.add(color)
        known = source in known_ids
        sources.append(_source_row(source, totals.get(source, 0) if known else None, known))
    numeric = [row["tokens"] for row in sources if row["known"] and row["tokens"] is not None]
    total = sum(numeric)
    buckets: dict[str, dict[str, Any]] = {}
    for row in shown:
        if row.get("at") is None:
            continue
        moment = datetime.fromtimestamp(row["at"], timezone.utc)
        start_hour = hour_start(moment)
        key = iso_z(start_hour)
        bucket = buckets.setdefault(key, {"start": key, "end": iso_z(start_hour + timedelta(hours=1)), "tokens": 0, "sources": {}})
        tokens = _int(row.get("tokens")) or 0
        source = str(row.get("source") or "other")
        bucket["tokens"] += tokens
        bucket["sources"][source] = bucket["sources"].get(source, 0) + tokens
    ordered_buckets = [buckets[key] for key in sorted(buckets)]
    total_buckets = [{"start": bucket["start"], "end": bucket["end"], "tokens": bucket["tokens"]} for bucket in ordered_buckets]
    source_buckets = [
        {"start": bucket["start"], "end": bucket["end"], "sources": dict(bucket["sources"]), "tokens": bucket["tokens"]}
        for bucket in ordered_buckets
    ]
    earliest = None
    dated = [row for row in rows if row.get("at") is not None and row.get("ended_at")]
    if dated:
        earliest = min(dated, key=lambda row: row["at"])["ended_at"]
    session_rows = sorted(sessions.values(), key=lambda row: row["id"])
    from token_cost import cost_summary

    cost = cost_summary(shown, plans, start=window.get("start"), end=window.get("end"))
    return {
        "loaded": True,
        "total": total,
        "input": input_tokens,
        "output": output_tokens,
        "cost": cost,
        "plans": list(plans or []),
        "earliest": earliest,
        "sources": sources,
        "window": {"preset": window.get("preset") or preset or "custom", "start": window.get("start"), "end": window.get("end")},
        "charts": {
            "total": {"id": "token-chart-total", "buckets": total_buckets},
            "by_source": {"id": "token-chart-sources", "buckets": source_buckets},
        },
        "series": [
            {"id": "total", "buckets": total_buckets},
            {"id": "by_source", "buckets": source_buckets},
        ],
        "events": rows,
        "sessions": session_rows,
    }


def aggregate_tokens(
    records: list[dict[str, Any]],
    *,
    preset: str = "all",
    schedule: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    plans: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    from token_cost import PUBLISHED_PLANS, stamp_api_usd

    events = stamp_api_usd(count_events(records), schedule)
    return report_from_events(events, preset=preset, plans=plans if plans is not None else PUBLISHED_PLANS)


def apply_window(
    events: list[dict[str, Any]],
    start: str,
    end: str,
    *,
    preset: str = "custom",
    plans: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    """Same events, one shared window, both chart series."""
    return report_from_events(events, window={"preset": preset, "start": start, "end": end}, plans=plans)


def _seconds(start: datetime, end: datetime) -> float:
    return max(1.0, (end - start).total_seconds())


def time_at_x(window_start: str, window_end: str, x: float, scale_x0: float, scale_width: float) -> datetime | None:
    """Invert the bar axis: plot x is a fraction of the window, not of the bucket index."""
    start = parse_time(window_start)
    end = parse_time(window_end)
    width = float(scale_width)
    if start is None or end is None or width <= 0:
        return None
    frac = (float(x) - float(scale_x0)) / width
    frac = min(1.0, max(0.0, frac))
    return start + timedelta(seconds=_seconds(start, end) * frac)


def hour_bar_box(
    window_start: str,
    window_end: str,
    bucket_start: str,
    scale_x0: float,
    scale_width: float,
) -> tuple[float, float]:
    """Left edge and width of one clock hour on the axis time_at_x reads."""
    start = parse_time(window_start)
    end = parse_time(window_end)
    bucket = parse_time(bucket_start)
    width = float(scale_width)
    origin = float(scale_x0)
    if start is None or end is None or bucket is None or width <= 0:
        return origin, 1.0
    span = _seconds(start, end)
    offset = min(span, max(0.0, (bucket - start).total_seconds()))
    left = origin + width * offset / span
    hour_end = min(end, bucket + timedelta(hours=1))
    covered = max(0.0, (hour_end - bucket).total_seconds())
    return left, max(0.0, width * covered / span)


def _fit_hour(
    start: datetime,
    end: datetime,
    hour: datetime,
    full_start: datetime,
    full_end: datetime,
) -> tuple[datetime, datetime]:
    """Shift a window so the clock hour under the pointer stays inside it."""
    hour_end = hour + timedelta(hours=1)
    span = end - start
    if span < timedelta(hours=1):
        span = timedelta(hours=1)
    if start <= hour and end >= hour_end:
        return start, end
    if span <= timedelta(hours=1):
        new_start, new_end = hour, hour_end
    else:
        new_start = min(start, hour)
        new_end = new_start + span
        if new_end < hour_end:
            new_end = hour_end
            new_start = new_end - span
    if new_start < full_start:
        new_start = full_start
        new_end = new_start + span
    if new_end > full_end:
        new_end = full_end
        new_start = new_end - span
        if new_start < full_start:
            new_start = full_start
    if new_start > hour or new_end < hour_end:
        new_start = max(full_start, min(hour, full_end - timedelta(hours=1)))
        new_end = min(full_end, max(hour_end, new_start + span))
        if new_end < hour_end <= full_end:
            new_end = hour_end
            new_start = max(full_start, new_end - span)
    return new_start, new_end


def _bar_hit(bars: list[dict[str, Any]] | None, x: float) -> dict[str, Any] | None:
    hits = [bar for bar in (bars or []) if float(bar.get("x0", 0)) <= float(x) <= float(bar.get("x1", 0))]
    if not hits:
        return None
    return min(hits, key=lambda bar: abs((float(bar["x0"]) + float(bar["x1"])) / 2 - float(x)))


def pointer_window(
    window: dict[str, Any],
    x: float,
    scale_x0: float,
    scale_width: float,
    *,
    factor: float | None = None,
    x1: float | None = None,
    full: dict[str, Any] | None = None,
    bars: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Next zoom window for a wheel factor or a drag end x. Bars use this same axis."""
    start = parse_time(window.get("start"))
    end = parse_time(window.get("end"))
    bounds = full or window
    full_start = parse_time(bounds.get("start"))
    full_end = parse_time(bounds.get("end"))
    if start is None or end is None or full_start is None or full_end is None:
        return {
            "preset": str(window.get("preset") or "custom"),
            "start": window.get("start"),
            "end": window.get("end"),
        }
    if x1 is not None:
        points: list[datetime] = []
        for hit_x in (x, x1):
            hit = _bar_hit(bars, hit_x)
            if hit is not None and parse_time(hit.get("start")) is not None:
                points.append(parse_time(hit.get("start")))  # type: ignore[arg-type]
            else:
                moment = time_at_x(str(window.get("start")), str(window.get("end")), hit_x, scale_x0, scale_width)
                if moment is not None:
                    points.append(moment)
        if not points:
            return {"preset": "custom", "start": window.get("start"), "end": window.get("end")}
        new_start = hour_start(min(points))
        new_end = hour_start(max(points)) + timedelta(hours=1)
        anchor = new_start
    else:
        zoom = 0.5 if factor is None else float(factor)
        span = _seconds(start, end)
        full_span = _seconds(full_start, full_end)
        if zoom > 1 and span * zoom >= full_span * 0.98:
            return {"preset": "all", "start": iso_z(full_start), "end": iso_z(full_end)}
        width = float(scale_width) if float(scale_width) > 0 else 1.0
        hit = _bar_hit(bars, x)
        hit_hour = parse_time(hit.get("start")) if hit else None
        if hit_hour is not None:
            cursor = hit_hour + timedelta(minutes=30)
            frac = min(1.0, max(0.0, (cursor - start).total_seconds() / span))
        else:
            frac = min(1.0, max(0.0, (float(x) - float(scale_x0)) / width))
            cursor = start + timedelta(seconds=span * frac)
        new_span = max(3600.0, min(full_span, span * zoom))
        new_start = cursor - timedelta(seconds=new_span * frac)
        new_end = new_start + timedelta(seconds=new_span)
        if new_start < full_start:
            new_start = full_start
            new_end = new_start + timedelta(seconds=new_span)
        if new_end > full_end:
            new_end = full_end
            new_start = new_end - timedelta(seconds=new_span)
            if new_start < full_start:
                new_start = full_start
        anchor = hit_hour if hit_hour is not None else hour_start(cursor)
    new_start, new_end = _fit_hour(new_start, new_end, anchor, full_start, full_end)
    preset = "hour" if (new_end - new_start).total_seconds() <= 3600.1 else "custom"
    if abs((new_start - full_start).total_seconds()) < 1 and abs((new_end - full_end).total_seconds()) < 1:
        preset = "all"
    return {"preset": preset, "start": iso_z(new_start), "end": iso_z(new_end)}


def empty_report() -> dict[str, Any]:
    sources = [_source_row(sid, None, False) for sid, _label, _color in REQUIRED_SOURCES]
    return {
        "loaded": False,
        "total": None,
        "input": None,
        "output": None,
        "cost": {"api": None, "subscription": None, "difference": None, "unpriced_turns": 0, "priced_turns": 0},
        "plans": [],
        "earliest": None,
        "sources": sources,
        "window": {"preset": "all", "start": None, "end": None},
        "charts": {
            "total": {"id": "token-chart-total", "buckets": []},
            "by_source": {"id": "token-chart-sources", "buckets": []},
        },
        "series": [
            {"id": "total", "buckets": []},
            {"id": "by_source", "buckets": []},
        ],
        "events": [],
        "sessions": [],
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _summary_meta(path: Path) -> dict[str, Any]:
    data = _read_json(path) or {}
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    return {
        "session_id": str(info.get("id") or path.parent.name),
        "parent_session_id": data.get("parent_session_id") or "",
        "session_kind": data.get("session_kind") or "",
        "agent_name": data.get("agent_name") or "",
    }


def _record_from_payload(payload: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    return {
        "session_id": str(payload.get("sessionId") or meta.get("session_id") or ""),
        "parent_session_id": meta.get("parent_session_id") or "",
        "session_kind": meta.get("session_kind") or "",
        "agent_name": meta.get("agent_name") or "",
        "usage_incomplete": bool(session.get("usageIsIncomplete")),
        "updated_at": payload.get("updatedAt"),
        "turns": payload.get("turns") if isinstance(payload.get("turns"), list) else [],
    }


def _fetch_grok_usage(session_id: str) -> dict[str, Any] | None:
    exe = Path(os.environ.get("SILVIA_GROK_EXE") or GROK_EXE)
    if not exe.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(exe), "usage", session_id],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            **_no_console(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _scan_sessions(root: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in {".git", "node_modules", "__pycache__"}]
        if "usage.json" not in filenames:
            continue
        folder = Path(dirpath)
        usage = folder / "usage.json"
        summary = folder / "summary.json"
        try:
            usage_mtime = usage.stat().st_mtime_ns
        except OSError:
            continue
        try:
            summary_mtime = summary.stat().st_mtime_ns if summary.is_file() else 0
        except OSError:
            summary_mtime = 0
        found.append(
            {
                "session_id": folder.name,
                "usage": usage,
                "summary": summary,
                "usage_mtime_ns": usage_mtime,
                "summary_mtime_ns": summary_mtime,
            }
        )
    return found


def _load_disk_cache(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if not data:
        return {}
    sessions = data.get("sessions")
    return sessions if isinstance(sessions, dict) else {}


def _write_disk_cache(path: Path, sessions: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"sessions": sessions}), encoding="utf-8")
    os.replace(temp, path)


def _external_records() -> list[dict[str, Any]]:
    """A voice or bot usage.json in a known tree is a ledger. Absence stays unknown."""
    global _EXTERNAL_SCANNED, _EXTERNAL_RECORDS
    if _EXTERNAL_SCANNED:
        return list(_EXTERNAL_RECORDS)
    found: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for root, source in _EXTERNAL_ROOTS:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in {".git", "node_modules", "__pycache__", "dist"}]
            if "usage.json" not in filenames:
                continue
            payload = _read_json(Path(dirpath) / "usage.json")
            if not payload or "totalTokens" not in json.dumps(payload):
                continue
            found.append(
                {
                    "session_id": f"{source}:{Path(dirpath).name}",
                    "source": source,
                    "usage_incomplete": bool((payload.get("session") or {}).get("usageIsIncomplete"))
                    if isinstance(payload.get("session"), dict)
                    else False,
                    "turns": payload.get("turns") if isinstance(payload.get("turns"), list) else [],
                    "total_tokens": (payload.get("session") or {}).get("totalTokens")
                    if isinstance(payload.get("session"), dict)
                    else payload.get("totalTokens"),
                    "updated_at": payload.get("updatedAt"),
                }
            )
            seen_sources.add(source)
            break
    for source in ("voice", "bots"):
        if source not in seen_sources:
            found.append({"source": source, "ledger": False})
    _EXTERNAL_RECORDS = found
    _EXTERNAL_SCANNED = True
    return list(found)


def load_token_history(*, sessions_root: Path | None = None, cache_path: Path | None = None) -> dict[str, Any]:
    """Load cached `grok usage` ledgers. Unchanged sessions are not spawned again."""
    root = sessions_root or Path(os.environ.get("SILVIA_SESSIONS") or SESSIONS)
    cache = cache_path or Path(os.environ.get("SILVIA_TOKEN_CACHE") or CACHE_PATH)
    with _LOCK:
        scanned = _scan_sessions(root)
        signature = tuple(sorted((row["session_id"], row["usage_mtime_ns"], row["summary_mtime_ns"]) for row in scanned))
        if _MEM.get("sig") == signature and isinstance(_MEM.get("report"), dict):
            return _MEM["report"]
        disk = _load_disk_cache(cache)
        records: list[dict[str, Any]] = []
        fresh: dict[str, Any] = {}
        missing: list[dict[str, Any]] = []
        for row in scanned:
            sid = row["session_id"]
            cached = disk.get(sid) if isinstance(disk.get(sid), dict) else None
            payload = cached.get("payload") if cached else None
            meta = cached.get("meta") if cached else None
            usage_matches = bool(cached) and cached.get("usage_mtime_ns") == row["usage_mtime_ns"] and isinstance(payload, dict)
            summary_matches = bool(cached) and cached.get("summary_mtime_ns") == row["summary_mtime_ns"] and isinstance(meta, dict)
            if usage_matches and summary_matches:
                records.append(_record_from_payload(payload, meta))
                fresh[sid] = cached
                continue
            if usage_matches and row["summary"].is_file():
                meta = _summary_meta(row["summary"])
                item = {
                    "usage_mtime_ns": row["usage_mtime_ns"],
                    "summary_mtime_ns": row["summary_mtime_ns"],
                    "payload": payload,
                    "meta": meta,
                }
                fresh[sid] = item
                records.append(_record_from_payload(payload, meta))
                continue
            missing.append(row)
        if missing:
            fetched = {}
            workers = min(8, len(missing))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_fetch_grok_usage, row["session_id"]): row for row in missing}
                for future in as_completed(futures):
                    row = futures[future]
                    try:
                        fetched[row["session_id"]] = future.result()
                    except Exception:
                        fetched[row["session_id"]] = None
            for row in missing:
                payload = fetched.get(row["session_id"])
                if not isinstance(payload, dict):
                    continue
                meta = _summary_meta(row["summary"]) if row["summary"].is_file() else {"session_id": row["session_id"]}
                fresh[row["session_id"]] = {
                    "usage_mtime_ns": row["usage_mtime_ns"],
                    "summary_mtime_ns": row["summary_mtime_ns"],
                    "payload": payload,
                    "meta": meta,
                }
                records.append(_record_from_payload(payload, meta))
        records.extend(_external_records())
        report = aggregate_tokens(records, preset="all")
        try:
            _write_disk_cache(cache, fresh)
        except OSError:
            pass
        _MEM["sig"] = signature
        _MEM["report"] = report
        return report


def clear_memory_cache() -> None:
    """Drop the in-process snapshot. The disk cache is left in place."""
    with _LOCK:
        _MEM["sig"] = None
        _MEM["report"] = None
