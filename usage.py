"""SuperGrok Heavy subscription usage for the Silvia dashboard.

Billing credits come from Grok's live `billing: fetched credits config` lines
in ~/.grok/logs/unified.jsonl. Session token/cost detail comes from
`grok usage <session-id>` (same JSON the TUI /usage ledger uses).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

GROK = Path.home() / ".grok"
DEFAULT_LOG = GROK / "logs" / "unified.jsonl"
GROK_EXE = GROK / "bin" / "grok.exe"
TICKS_PER_USD = 10_000_000_000
TAIL_BYTES = 2_000_000


def _env_path(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    return Path(raw) if raw else default


def _no_console() -> dict[str, int]:
    """pythonw has no console, so a console child would open its own window."""
    if os.name != "nt":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def ticks_to_usd(ticks: Any) -> float:
    try:
        return float(ticks or 0) / TICKS_PER_USD
    except (TypeError, ValueError):
        return 0.0


PRODUCTS = (
    ("chat", "Chat"),
    ("voice", "Voice"),
    ("bot", "Bot"),
    ("imagine", "Imagine"),
    ("build", "Build"),
)


def _short_when(iso: Any) -> str | None:
    text = str(iso or "").strip()
    if not text:
        return None
    day = text[:10]
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(day)
        return dt.strftime("%d %b %Y")
    except ValueError:
        return day


def _pct(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return f"{float(value):g}%"
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text.endswith("%") else f"{text}%"


def _val(obj: Any) -> Any:
    if isinstance(obj, dict) and "val" in obj:
        return obj.get("val")
    return obj


def parse_billing_event(obj: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    if obj.get("msg") != "billing: fetched credits config":
        return None
    ctx = obj.get("ctx") if isinstance(obj.get("ctx"), dict) else {}
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    if not cfg and not ctx.get("subscriptionTier"):
        return None
    period = cfg.get("currentPeriod") if isinstance(cfg.get("currentPeriod"), dict) else {}
    percent = cfg.get("creditUsagePercent")
    try:
        percent_f = float(percent) if percent is not None else None
    except (TypeError, ValueError):
        percent_f = None
    if percent_f is None:
        # After a weekly reset xAI omits creditUsagePercent; treat as 0% used.
        percent_f = 0.0
    remaining = max(0.0, 100.0 - percent_f)
    return {
        "ok": True,
        "source": "billing-log",
        "fetched_at": obj.get("ts"),
        "subscription_tier": ctx.get("subscriptionTier") or "SuperGrok Heavy",
        "credit_usage_percent": percent_f,
        "remaining_percent": remaining,
        "period_type": period.get("type"),
        "period_start": period.get("start") or cfg.get("billingPeriodStart"),
        "period_end": period.get("end") or cfg.get("billingPeriodEnd"),
        "billing_period_start": cfg.get("billingPeriodStart"),
        "billing_period_end": cfg.get("billingPeriodEnd"),
        "on_demand_cap": _val(cfg.get("onDemandCap")),
        "on_demand_used": _val(cfg.get("onDemandUsed")),
        "prepaid_balance": _val(cfg.get("prepaidBalance")),
        "unified_billing": bool(cfg.get("isUnifiedBillingUser")),
        "on_demand_enabled": ctx.get("onDemandEnabled"),
        "grok_version": obj.get("ver"),
        "products": parse_products(cfg),
    }


def load_latest_billing(log_path: Path | None = None) -> dict[str, Any]:
    path = log_path or _env_path("SILVIA_USAGE_LOG", DEFAULT_LOG)
    if not path.is_file():
        return {"ok": False, "error": f"missing billing log: {path}", "subscription_tier": "SuperGrok Heavy"}
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - TAIL_BYTES))
            raw = handle.read().decode("utf-8", "replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc), "subscription_tier": "SuperGrok Heavy"}
    latest: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "fetched credits config" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed = parse_billing_event(obj)
        if not parsed:
            continue
        latest = parsed
        history.append(
            {
                "ts": parsed.get("fetched_at"),
                "percent": parsed.get("credit_usage_percent"),
            }
        )
    if not latest:
        return {"ok": False, "error": "no billing credits config in log tail", "subscription_tier": "SuperGrok Heavy"}
    # Unique percent steps, last 24
    steps: list[dict[str, Any]] = []
    last_p = object()
    for row in history:
        if row.get("percent") != last_p:
            steps.append(row)
            last_p = row.get("percent")
    latest["credit_history"] = steps[-24:]
    if not latest.get("products"):
        latest["products"] = parse_products({})
    latest["ok"] = True
    return latest


def load_session_usage(session_id: str) -> dict[str, Any]:
    sid = (session_id or "").strip()
    if not sid:
        return {"ok": False, "error": "no session id"}
    exe = Path(os.environ.get("SILVIA_GROK_EXE") or GROK_EXE)
    if not exe.is_file():
        return {"ok": False, "error": f"missing grok.exe: {exe}"}
    try:
        proc = subprocess.run(
            [str(exe), "usage", sid],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            check=False,
            **_no_console(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "grok usage failed")[:400]}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "grok usage not JSON"}
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    models = []
    usage_map = session.get("modelUsage") if isinstance(session.get("modelUsage"), dict) else {}
    for mid, rec in usage_map.items():
        if not isinstance(rec, dict):
            continue
        models.append(
            {
                "id": mid,
                "input_tokens": rec.get("inputTokens"),
                "output_tokens": rec.get("outputTokens"),
                "cached_read_tokens": rec.get("cachedReadTokens"),
                "cache_creation_tokens": rec.get("cacheCreationTokens"),
                "reasoning_tokens": rec.get("reasoningTokens"),
                "total_tokens": rec.get("totalTokens"),
                "model_calls": rec.get("modelCalls"),
                "cost_usd": ticks_to_usd(rec.get("costUsdTicks")),
                "usage_incomplete": bool(rec.get("usageIsIncomplete")),
            }
        )
    turns = []
    for turn in payload.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        turns.append(
            {
                "turn": turn.get("turnNumber"),
                "ended_at": turn.get("endedAt"),
                "input_tokens": turn.get("inputTokens"),
                "output_tokens": turn.get("outputTokens"),
                "cached_read_tokens": turn.get("cachedReadTokens"),
                "reasoning_tokens": turn.get("reasoningTokens"),
                "total_tokens": turn.get("totalTokens"),
                "model_calls": turn.get("modelCalls"),
                "cost_usd": ticks_to_usd(turn.get("costUsdTicks")),
                "model": turn.get("primaryModelId"),
            }
        )
    return {
        "ok": True,
        "session_id": payload.get("sessionId") or sid,
        "updated_at": payload.get("updatedAt"),
        "input_tokens": session.get("inputTokens"),
        "output_tokens": session.get("outputTokens"),
        "cached_read_tokens": session.get("cachedReadTokens"),
        "cache_creation_tokens": session.get("cacheCreationTokens"),
        "reasoning_tokens": session.get("reasoningTokens"),
        "total_tokens": session.get("totalTokens"),
        "model_calls": session.get("modelCalls"),
        "turn_count": session.get("turnCount"),
        "primary_model": session.get("primaryModelId"),
        "cost_usd": ticks_to_usd(session.get("costUsdTicks")),
        "usage_incomplete": bool(session.get("usageIsIncomplete")),
        "models": models,
        "turns": turns,
    }


def current_session_id() -> str:
    override = (os.environ.get("SILVIA_USAGE_SESSION") or "").strip()
    if override:
        return override
    path = GROK / "active_sessions.json"
    if not path.is_file():
        return ""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return str(rows[0].get("session_id") or "")
    return ""


def parse_products(cfg: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Product split if xAI sent one. Never invent Chat/Voice/Bot percents."""
    blob = cfg or {}
    raw = (
        blob.get("productUsage")
        or blob.get("usageByProduct")
        or blob.get("products")
        or blob.get("breakdown")
    )
    found: dict[str, Any] = {}
    if isinstance(raw, dict):
        for key, val in raw.items():
            kid = str(key).strip().lower()
            if isinstance(val, dict):
                found[kid] = val.get("percent") if val.get("percent") is not None else val.get("usagePercent")
            else:
                found[kid] = val
    elif isinstance(raw, list):
        for rec in raw:
            if not isinstance(rec, dict):
                continue
            kid = str(rec.get("id") or rec.get("product") or rec.get("name") or "").strip().lower()
            found[kid] = rec.get("percent") if rec.get("percent") is not None else rec.get("usagePercent")
    out = []
    for pid, label in PRODUCTS:
        pct = found.get(pid)
        if pct is None:
            for alias in (label.lower(), pid + "usage"):
                if alias in found:
                    pct = found[alias]
                    break
        out.append(
            {
                "id": f"usage.{pid}",
                "label": label,
                "percent": None if pct is None else _pct(pct),
                "known": pct is not None,
            }
        )
    return out


def _breakdown(billing: dict[str, Any]) -> list[dict[str, Any]]:
    used = _pct(billing.get("credit_usage_percent"))
    left = _pct(billing.get("remaining_percent"))
    week_start = _short_when(billing.get("period_start") or billing.get("billing_period_start"))
    week_end = _short_when(billing.get("period_end") or billing.get("billing_period_end"))
    as_of = _short_when(billing.get("fetched_at"))
    week_range = None
    if week_start and week_end:
        week_range = f"{week_start} – {week_end}"
    elif week_start or week_end:
        week_range = week_start or week_end
    rows: list[dict[str, Any]] = [
        {"id": "usage.tier", "label": "Plan", "value": billing.get("subscription_tier") or "SuperGrok Heavy"},
        {"id": "usage.week", "label": "This week", "value": week_range},
        {"id": "usage.starts", "label": "Week starts", "value": week_start},
        {"id": "usage.resets", "label": "Resets", "value": week_end},
        {"id": "usage.as_of", "label": "As of", "value": as_of},
        {"id": "usage.used", "label": "Used this week", "value": used},
        {"id": "usage.left", "label": "Left this week", "value": left},
    ]
    products = list(billing.get("products") or parse_products({}))
    for rec in products:
        shown = rec.get("percent") if rec.get("known") else "—"
        rows.append({"id": rec.get("id"), "label": rec.get("label"), "value": shown})
    return [r for r in rows if r.get("id") and r.get("value") is not None]


def load_usage(*, log_path: Path | None = None, session_id: str | None = None, tokens: bool = False) -> dict[str, Any]:
    billing = load_latest_billing(log_path)
    if session_id:
        billing["session"] = load_session_usage(session_id)
    report = dict(billing)
    if not report.get("products"):
        report["products"] = parse_products({})
    report["breakdown"] = _breakdown(report)
    report["ok"] = bool(billing.get("ok"))
    if not report.get("subscription_tier"):
        report["subscription_tier"] = "SuperGrok Heavy"
    if tokens:
        from token_history import load_token_history

        history = load_token_history()
        report["tokens"] = history
        report["token_events"] = list(history.get("events") or [])
    return report
