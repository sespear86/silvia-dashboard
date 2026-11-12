"""Token tracker: fixture ledgers drive the shipped aggregate, window, and charts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from token_history import (  # noqa: E402
    aggregate_tokens,
    apply_window,
    clear_memory_cache,
    load_token_history,
    parse_time,
    window_for_preset,
)
from world import build_world, page_view, switch_page  # noqa: E402

PARENT_TURN = "2026-08-01T10:15:00Z"
LATER_SAME_DAY = "2026-08-01T12:15:00Z"
NEXT_DAY = "2026-08-02T10:15:00Z"
SAME_HOUR_SUB = "2026-08-01T10:20:00Z"
SAME_HOUR_BOT = "2026-08-01T10:40:00Z"
DAYS_LATER = "2026-08-03T09:05:00Z"
HOUR_START = "2026-08-01T10:00:00Z"
HOUR_END = "2026-08-01T11:00:00Z"


def _fixture() -> list[dict]:
    """Parent, a resume that repeats one parent turn, a subagent, a bot, and no voice ledger."""
    return [
        {
            "session_id": "parent",
            "turns": [
                {"turn": 1, "ended_at": PARENT_TURN, "total_tokens": 100},
                {"turn": 2, "ended_at": LATER_SAME_DAY, "total_tokens": 40},
            ],
        },
        {
            "session_id": "fork",
            "parent_session_id": "parent",
            "session_kind": "subagent_resume",
            "turns": [
                {"turn": 1, "ended_at": PARENT_TURN, "total_tokens": 100},
                {"turn": 3, "ended_at": NEXT_DAY, "total_tokens": 25},
            ],
        },
        {
            "session_id": "child",
            "parent_session_id": "parent",
            "session_kind": "subagent",
            "turns": [
                {"turn": 1, "ended_at": SAME_HOUR_SUB, "total_tokens": 7},
            ],
        },
        {
            "session_id": "bot-1",
            "source": "bots",
            "turns": [
                {"turn": 1, "ended_at": SAME_HOUR_BOT, "total_tokens": 9},
            ],
        },
        {
            "session_id": "later",
            "turns": [
                {"turn": 1, "ended_at": DAYS_LATER, "total_tokens": 11},
            ],
        },
        {
            "session_id": "zero",
            "turns": [
                {"turn": 1, "ended_at": "2026-08-04T00:00:00Z", "total_tokens": 0},
            ],
        },
        {
            "session_id": "broken",
            "usage_incomplete": True,
            "turns": [
                {"turn": 1, "ended_at": "2026-08-04T01:00:00Z", "total_tokens": 999},
            ],
        },
        {"source": "voice", "ledger": False},
    ]


def _by_id(report: dict) -> dict:
    return {row["id"]: row for row in report["sources"]}


def test_fixture_totals_dedupe_sources_and_hourly_window():
    report = aggregate_tokens(_fixture())
    sources = _by_id(report)
    counted = 100 + 40 + 25 + 7 + 9 + 11
    assert report["total"] == counted
    assert report["total"] == sum(row["tokens"] for row in report["sources"] if row["known"])
    print("total equals the sum of source totals")

    keys = [(row["turn"], row["ended_at"]) for row in report["events"]]
    assert keys.count((1, PARENT_TURN)) == 1
    assert report["total"] != counted + 100
    print("the inherited turn is counted once")

    assert sources["subagents"]["tokens"] == 25 + 7
    assert any(row["session_id"] == "child" and row["tokens"] == 7 for row in report["events"])
    print("the subagent turn is counted")

    assert sources["voice"]["known"] is False
    assert sources["voice"]["tokens"] is None
    assert sources["voice"]["label"] == "voice"
    assert sources["bots"]["label"] == "bots"
    assert sources["tui"]["label"] == "TUI"
    assert sources["bots"]["tokens"] == 9
    assert sources["tui"]["tokens"] == 100 + 40 + 11
    print("voice is unknown rather than a fabricated number")

    bucket_sum = sum(bucket["tokens"] for bucket in report["charts"]["total"]["buckets"])
    assert bucket_sum == report["total"]
    assert report["earliest"] == PARENT_TURN
    print("the all-time total equals the sum of the hourly buckets")

    hour = apply_window(report["events"], HOUR_START, HOUR_END, preset="hour")
    assert hour["total"] == 100 + 7 + 9
    assert hour["window"]["start"] == HOUR_START
    assert hour["window"]["end"] == HOUR_END
    assert hour["charts"]["total"]["buckets"]
    assert hour["charts"]["by_source"]["buckets"]
    for bucket in hour["charts"]["total"]["buckets"] + hour["charts"]["by_source"]["buckets"]:
        assert bucket["start"] == HOUR_START
        assert LATER_SAME_DAY not in bucket["start"]
        assert NEXT_DAY not in bucket["start"]
        assert DAYS_LATER not in bucket["start"]
    assert hour["total"] != report["total"]
    print("an hourly window excludes events outside that hour")

    assert hour["window"] == {"preset": "hour", "start": HOUR_START, "end": HOUR_END}
    assert [series["id"] for series in hour["series"]] == ["total", "by_source"]
    assert hour["series"][0]["buckets"] == hour["charts"]["total"]["buckets"]
    assert hour["series"][1]["buckets"] == hour["charts"]["by_source"]["buckets"]
    print("both series use that window")

    colors = [row["color"] for row in report["sources"]]
    assert len(colors) == len(set(colors))
    assert all(colors)
    print("each source has one color and the colors differ")

    all_window = report["window"]
    day = window_for_preset(report["events"], "day")
    hour_preset = window_for_preset(report["events"], "hour")
    all_span = parse_time(all_window["end"]) - parse_time(all_window["start"])
    day_span = parse_time(day["end"]) - parse_time(day["start"])
    hour_span = parse_time(hour_preset["end"]) - parse_time(hour_preset["start"])
    assert hour_span.total_seconds() == 3600
    assert hour_span < day_span < all_span
    day_report = apply_window(report["events"], day["start"], day["end"], preset="day")
    assert day_report["total"] == 25 + 11
    assert 100 not in [bucket["tokens"] for bucket in day_report["charts"]["total"]["buckets"]]


def test_usage_charts_and_hour_window_on_withdrawn_dashboard():
    report = aggregate_tokens(_fixture())
    world = build_world(
        {
            "resources": [],
            "capabilities": [],
            "probes": {},
            "usage": {
                "subscription_tier": "SuperGrok Heavy",
                "credit_usage_percent": 38.0,
                "remaining_percent": 62.0,
                "period_start": "2026-08-28T23:06:18Z",
                "period_end": "2026-09-04T23:06:18Z",
                "products": [
                    {"id": "usage.chat", "label": "Chat", "percent": "12%", "known": True},
                    {"id": "usage.voice", "label": "Voice", "percent": None, "known": False},
                    {"id": "usage.bot", "label": "Bot", "percent": None, "known": False},
                    {"id": "usage.imagine", "label": "Imagine", "percent": None, "known": False},
                    {"id": "usage.build", "label": "Build", "percent": None, "known": False},
                ],
                "tokens": report,
                "token_events": report["events"],
            },
        }
    )
    view = page_view(world, "usage")
    assert view["usage_percent"] == 38.0
    assert view["usage_remaining"] == 62.0
    assert view["token_total"] == report["total"]
    assert len(view["token_series"]) == 2

    from app import SilviaDashboard

    app = SilviaDashboard(switch_page(world, "usage"))
    app.withdraw()
    job = app._auto_refresh_after
    if job is not None:
        app.after_cancel(job)
        app._auto_refresh_after = None
    try:
        app.update()
        assert len(app.canvas.find_withtag("token-chart-total")) == 1
        assert len(app.canvas.find_withtag("token-chart-sources")) == 1
        print("two separate chart surfaces")
        all_hours = {app.canvas.gettags(item) for item in app.canvas.find_withtag("token-total-bar")}
        app.set_token_window(HOUR_START, HOUR_END, preset="hour")
        app.update()
        hour_bars = app.canvas.find_withtag("token-total-bar")
        source_bars = app.canvas.find_withtag("token-source-bar")
        assert len(hour_bars) == 1
        assert len(all_hours) > len(hour_bars)
        fills = [app.canvas.itemcget(item, "fill") for item in source_bars]
        assert len(source_bars) == 3
        assert len(set(fills)) == len(fills)
        texts = []
        for item in app.canvas.find_all():
            if app.canvas.type(item) == "text":
                texts.append(app.canvas.itemcget(item, "text"))
        blob = "\n".join(texts)
        assert "Used this week" in blob
        assert "38%" in blob
        assert "62%" in blob
        assert "—" in blob
        print("one bar item per source with distinct fills")
        print("setting the window to a single hour changes which buckets are drawn")
    finally:
        app.destroy()


def test_loader_uses_grok_usage_and_skips_a_second_spawn(tmp_path, monkeypatch):
    calls = tmp_path / "calls.txt"
    script = tmp_path / "fake_usage.py"
    script.write_text(
        "import json, sys\n"
        f"from pathlib import Path\n"
        f"Path(r'{calls}').open('a', encoding='utf-8').write('call\\n')\n"
        "sid = sys.argv[2] if len(sys.argv) > 2 else ''\n"
        "print(json.dumps({\n"
        "  'sessionId': sid,\n"
        "  'updatedAt': '2026-08-01T10:15:00Z',\n"
        "  'session': {'totalTokens': 50, 'usageIsIncomplete': False},\n"
        "  'turns': [{'turnNumber': 1, 'endedAt': '2026-08-01T10:15:00Z', 'totalTokens': 50}],\n"
        "}))\n",
        encoding="utf-8",
    )
    cmd = tmp_path / "fake-grok.cmd"
    cmd.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    session = tmp_path / "sessions" / "work" / "finished-session"
    session.mkdir(parents=True)
    (session / "summary.json").write_text(
        json.dumps({"info": {"id": "finished-session", "cwd": "C:\\work"}, "agent_name": "grok-build-plan"}),
        encoding="utf-8",
    )
    (session / "usage.json").write_text(
        json.dumps(
            {
                "session": {"totalTokens": 1},
                "turns": [{"turnNumber": 1, "endedAt": "2026-08-01T10:15:00Z", "totalTokens": 1}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SILVIA_GROK_EXE", str(cmd))
    monkeypatch.setenv("SILVIA_SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setenv("SILVIA_TOKEN_CACHE", str(tmp_path / "cache.json"))
    clear_memory_cache()
    first = load_token_history(sessions_root=tmp_path / "sessions", cache_path=tmp_path / "cache.json")
    sources = _by_id(first)
    assert sources["tui"]["tokens"] == 50
    assert sources["voice"]["known"] is False
    assert sources["bots"]["known"] is False
    assert calls.read_text(encoding="utf-8").count("call") == 1
    clear_memory_cache()
    second = load_token_history(sessions_root=tmp_path / "sessions", cache_path=tmp_path / "cache.json")
    assert _by_id(second)["tui"]["tokens"] == 50
    assert calls.read_text(encoding="utf-8").count("call") == 1


def _window_contains_hour(window: dict, hour_start: str, hour_end: str) -> bool:
    start = parse_time(window.get("start"))
    end = parse_time(window.get("end"))
    hour = parse_time(hour_start)
    hour_stop = parse_time(hour_end)
    return bool(start and end and hour and hour_stop and start <= hour and end >= hour_stop)


def test_pointer_on_post_gap_bar_keeps_that_hour():
    """A bar after an empty stretch stays in the window when the wheel or drag hits it."""
    later = "2026-10-01T17:00:00Z"
    report = aggregate_tokens(
        [
            {
                "session_id": "early",
                "turns": [{"turn": 1, "ended_at": "2026-08-31T18:15:00Z", "total_tokens": 10}],
            },
            {
                "session_id": "after-gap",
                "turns": [{"turn": 1, "ended_at": "2026-10-01T17:15:00Z", "total_tokens": 20}],
            },
        ]
    )
    buckets = report["charts"]["total"]["buckets"]
    assert [bucket["start"] for bucket in buckets] == ["2026-08-31T18:00:00Z", later]
    world = build_world(
        {
            "resources": [],
            "capabilities": [],
            "probes": {},
            "usage": {
                "subscription_tier": "SuperGrok Heavy",
                "credit_usage_percent": 1,
                "remaining_percent": 99,
                "tokens": report,
                "token_events": report["events"],
            },
        }
    )
    from app import SilviaDashboard

    app = SilviaDashboard(switch_page(world, "usage"))
    app.withdraw()
    job = app._auto_refresh_after
    if job is not None:
        app.after_cancel(job)
        app._auto_refresh_after = None
    try:
        app.update()
        tag = "token-hour-" + later.replace("-", "").replace(":", "")
        bars = app.canvas.find_withtag(tag)
        assert bars
        coords = app.canvas.coords(bars[0])
        plot = next(row for row in app._token_plots if row["which"] == "total")
        scale_x0 = float(plot["scale_x0"])
        scale_w = float(plot["scale_x1"]) - scale_x0
        bar_frac = (float(coords[0]) - scale_x0) / scale_w
        index_frac = 1 / len(buckets)
        assert bar_frac > 0.9
        assert abs(bar_frac - index_frac) > 0.2
        pointer = (float(coords[0]) + float(coords[2])) / 2
        app._zoom_token_wheel(plot, pointer, 120)
        assert _window_contains_hour(app._token_window, later, "2026-10-01T18:00:00Z")
        app.set_token_zoom("all")
        app.update()
        bars = app.canvas.find_withtag(tag)
        coords = app.canvas.coords(bars[0])
        plot = next(row for row in app._token_plots if row["which"] == "total")
        app._zoom_token_span(plot, float(coords[0]), float(coords[2]))
        assert _window_contains_hour(app._token_window, later, "2026-10-01T18:00:00Z")
        print("a pointer on a post-gap bucket keeps that hour")
    finally:
        app.destroy()


def test_drag_on_second_source_color_keeps_that_hour():
    """An all-time hour about one pixel wide still owns its second source color."""
    from token_history import hour_bar_box

    hour = "2026-08-07T18:00:00Z"
    report = aggregate_tokens(
        [
            {
                "session_id": "open",
                "turns": [{"turn": 1, "ended_at": "2026-08-01T00:10:00Z", "total_tokens": 4}],
            },
            {
                "session_id": "tui-hour",
                "turns": [{"turn": 1, "ended_at": "2026-08-07T18:10:00Z", "total_tokens": 8}],
            },
            {
                "session_id": "bot-hour",
                "source": "bots",
                "turns": [{"turn": 1, "ended_at": "2026-08-07T18:40:00Z", "total_tokens": 6}],
            },
            {
                "session_id": "close",
                "turns": [{"turn": 1, "ended_at": "2026-08-13T15:10:00Z", "total_tokens": 4}],
            },
        ]
    )
    world = build_world(
        {
            "resources": [],
            "capabilities": [],
            "probes": {},
            "usage": {
                "subscription_tier": "SuperGrok Heavy",
                "credit_usage_percent": 1,
                "remaining_percent": 99,
                "tokens": report,
                "token_events": report["events"],
            },
        }
    )
    from app import SilviaDashboard

    app = SilviaDashboard(switch_page(world, "usage"))
    app.withdraw()
    job = app._auto_refresh_after
    if job is not None:
        app.after_cancel(job)
        app._auto_refresh_after = None
    try:
        app.update()
        plot = next(row for row in app._token_plots if row["which"] == "by_source")
        scale_x0 = float(plot["scale_x0"])
        scale_w = float(plot["scale_x1"]) - scale_x0
        left, slot = hour_bar_box(report["window"]["start"], report["window"]["end"], hour, scale_x0, scale_w)
        assert 0.7 <= slot <= 1.6
        tag = "token-hour-" + hour.replace("-", "").replace(":", "")
        painted = [item for item in app.canvas.find_withtag("token-source-bar") if tag in app.canvas.gettags(item)]
        painted.sort(key=lambda item: app.canvas.coords(item)[0])
        assert len(painted) >= 2
        coords = app.canvas.coords(painted[1])
        assert float(coords[0]) >= left - 0.05
        assert float(coords[2]) <= left + slot + 0.05
        app._zoom_token_span(plot, float(coords[0]), float(coords[2]))
        assert _window_contains_hour(app._token_window, hour, "2026-08-07T19:00:00Z")
        print("a drag on the second source color keeps that hour")
    finally:
        app.destroy()


_PRICE_SCHEDULE = [
    {
        "models": ["grok-a"],
        "effective": "2026-08-01T00:00:00Z",
        "threshold": 200_000,
        "input": "2.00",
        "cached": "0.50",
        "output": "6.00",
        "long_input": "4.00",
        "long_cached": "1.00",
        "long_output": "12.00",
    },
    {
        "models": ["grok-a"],
        "effective": "2026-09-01T00:00:00Z",
        "threshold": 200_000,
        "input": "3.00",
        "cached": "0.75",
        "output": "9.00",
        "long_input": "8.00",
        "long_cached": "2.00",
        "long_output": "18.00",
    },
]


def test_api_cost_uses_the_price_in_effect_and_skips_unpriced_turns():
    """List price follows the turn's time. Ticks and credit percents are not the dollar sides."""
    plans = [{"start": "2026-08-01T00:00:00Z", "end": "2026-10-01T00:00:00Z", "usd": "300"}]
    report = aggregate_tokens(
        [
            {
                "session_id": "parent",
                "turns": [
                    {
                        "turn": 1,
                        "endedAt": "2026-08-15T10:00:00Z",
                        "model": "grok-a",
                        "inputTokens": 100_000,
                        "cachedReadTokens": 40_000,
                        "outputTokens": 10_000,
                        "totalTokens": 150_000,
                        "costUsdTicks": 99_000_000_000_000,
                    },
                    {
                        "turn": 2,
                        "endedAt": "2026-08-20T10:00:00Z",
                        "model": "grok-a",
                        "inputTokens": 250_000,
                        "cachedReadTokens": 50_000,
                        "outputTokens": 10_000,
                        "totalTokens": 260_000,
                    },
                    {
                        "turn": 3,
                        "endedAt": "2026-08-25T10:00:00Z",
                        "model": "grok-a",
                        "totalTokens": 10_000_000,
                    },
                    {
                        "turn": 4,
                        "endedAt": "2026-09-15T10:00:00Z",
                        "model": "grok-a",
                        "inputTokens": 100_000,
                        "cachedReadTokens": 0,
                        "outputTokens": 50_000,
                        "totalTokens": 150_000,
                    },
                ],
            },
            {
                "session_id": "fork",
                "parent_session_id": "parent",
                "session_kind": "subagent_resume",
                "turns": [
                    {
                        "turn": 1,
                        "endedAt": "2026-08-15T10:00:00Z",
                        "model": "grok-a",
                        "inputTokens": 100_000,
                        "cachedReadTokens": 40_000,
                        "outputTokens": 10_000,
                        "totalTokens": 150_000,
                    },
                ],
            },
            {
                "session_id": "no-price",
                "turns": [
                    {
                        "turn": 1,
                        "endedAt": "2026-09-20T10:00:00Z",
                        "model": "grok-nope",
                        "inputTokens": 1_000_000,
                        "outputTokens": 1_000_000,
                        "totalTokens": 2_000_000,
                    },
                ],
            },
        ],
        schedule=_PRICE_SCHEDULE,
        plans=plans,
    )
    early = (60_000 * 2 + 40_000 * 0.5 + 10_000 * 6) / 1_000_000
    later = (100_000 * 3 + 50_000 * 9) / 1_000_000
    long_context = (200_000 * 4 + 50_000 * 1 + 10_000 * 12) / 1_000_000
    assert early == 0.2
    assert later == 0.75
    assert long_context == 0.97
    assert report["cost"]["api"] == early + later + long_context
    assert report["cost"]["api"] != early + early + later + long_context
    print("the earlier turn uses the earlier price and the later turn uses the later price")
    print("the inherited turn is priced once")
    doubled_cache = (100_000 * 2 + 40_000 * 0.5 + 10_000 * 6) / 1_000_000
    assert report["cost"]["api"] != doubled_cache + later + long_context
    print("cached tokens are not billed again at the full input rate")
    assert report["cost"]["api"] != early + later + long_context + (10_000_000 * 2) / 1_000_000
    print("the turn with no input or output adds nothing")
    assert report["cost"]["api"] != early + later + long_context + (1_000_000 * 3 + 1_000_000 * 9) / 1_000_000
    assert report["cost"]["unpriced_turns"] >= 1
    print("the unpriced turn is unknown rather than today's rate")
    assert report["cost"]["api"] == early + later + long_context
    print("the API total is the sum of the priced turns")
    narrowed = apply_window(
        report["events"],
        "2026-08-01T00:00:00Z",
        "2026-09-01T00:00:00Z",
        plans=plans,
    )
    assert narrowed["cost"]["api"] == early + long_context
    assert narrowed["cost"]["api"] != report["cost"]["api"]
    print("a window that drops the later turn drops that turn's dollars")
    assert report["cost"]["subscription"] == 300
    assert report["cost"]["subscription"] != 38
    print("the subscription figure is the fixture's plan price and is not a rewrite of a credit percent")
    assert report["cost"]["difference"] == report["cost"]["api"] - 300
    print("both sides and the difference are numeric for that fixture")

    world = build_world(
        {
            "resources": [],
            "capabilities": [],
            "probes": {},
            "usage": {
                "subscription_tier": "SuperGrok Heavy",
                "credit_usage_percent": 38.0,
                "remaining_percent": 62.0,
                "tokens": report,
                "token_events": report["events"],
            },
        }
    )
    from app import SilviaDashboard

    app = SilviaDashboard(switch_page(world, "usage"))
    app.withdraw()
    job = app._auto_refresh_after
    if job is not None:
        app.after_cancel(job)
        app._auto_refresh_after = None
    try:
        app.update()
        texts = [
            app.canvas.itemcget(item, "text")
            for item in app.canvas.find_all()
            if app.canvas.type(item) == "text"
        ]
        assert "API list price" in texts
        assert "Subscription" in texts
        assert "Difference" in texts
        assert "$1.92" in texts
        assert "$300.00" in texts
        assert "38%" in texts
        assert "62%" in texts
        assert any(text.endswith("%") for text in texts if text in ("38%", "62%"))
    finally:
        app.destroy()


def test_input_and_output_follow_the_counted_turns():
    """Input and output are the fixture fields on the same turns as the total."""
    report = aggregate_tokens(
        [
            {
                "session_id": "parent",
                "turns": [
                    {
                        "turn": 1,
                        "ended_at": "2026-08-01T10:15:00Z",
                        "totalTokens": 100,
                        "inputTokens": 70,
                        "outputTokens": 20,
                    },
                    {
                        "turn": 2,
                        "ended_at": "2026-08-01T12:15:00Z",
                        "totalTokens": 40,
                        "inputTokens": 30,
                        "outputTokens": 9,
                    },
                    {
                        "turn": 3,
                        "ended_at": "2026-08-02T10:15:00Z",
                        "totalTokens": 15,
                    },
                ],
            },
            {
                "session_id": "fork",
                "parent_session_id": "parent",
                "session_kind": "subagent_resume",
                "turns": [
                    {
                        "turn": 1,
                        "ended_at": "2026-08-01T10:15:00Z",
                        "totalTokens": 100,
                        "inputTokens": 70,
                        "outputTokens": 20,
                    },
                ],
            },
        ]
    )
    assert report["input"] == 70 + 30
    assert report["input"] != 70 + 70 + 30
    print("input equals the fixture input sum with the inherited turn once")
    assert report["output"] == 20 + 9
    assert report["output"] != 20 + 20 + 9
    print("output equals the fixture output sum with the inherited turn once")
    assert report["input"] == 70 + 30
    assert report["output"] == 20 + 9
    print("the turn that lacks both fields does not change either sum")
    assert report["total"] == 100 + 40 + 15
    assert report["total"] == sum(row["tokens"] for row in report["sources"] if row["known"])
    assert report["total"] != report["input"] + report["output"]
    print("the total is still the sum of totalTokens and equals the sum of known source totals")
    hour = apply_window(report["events"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z", preset="hour")
    assert hour["input"] == 70
    assert hour["output"] == 20
    assert hour["total"] == 100

    world = build_world(
        {
            "resources": [],
            "capabilities": [],
            "probes": {},
            "usage": {
                "subscription_tier": "SuperGrok Heavy",
                "credit_usage_percent": 38.0,
                "remaining_percent": 62.0,
                "tokens": report,
                "token_events": report["events"],
            },
        }
    )
    from app import SilviaDashboard

    app = SilviaDashboard(switch_page(world, "usage"))
    app.withdraw()
    job = app._auto_refresh_after
    if job is not None:
        app.after_cancel(job)
        app._auto_refresh_after = None
    try:
        app.update()

        def text_y(label: str) -> float:
            for item in app.canvas.find_all():
                if app.canvas.type(item) == "text" and app.canvas.itemcget(item, "text") == label:
                    return float(app.canvas.coords(item)[1])
            raise AssertionError(label)

        total_y = text_y("Total tokens")
        input_y = text_y("input")
        output_y = text_y("output")
        source_y = text_y("By source")
        assert total_y < input_y < source_y
        assert total_y < output_y < source_y
        texts = [
            app.canvas.itemcget(item, "text")
            for item in app.canvas.find_all()
            if app.canvas.type(item) == "text"
        ]
        assert "100" in texts
        assert "29" in texts
        assert "38%" in texts
        assert "62%" in texts
    finally:
        app.destroy()
