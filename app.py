"""Windows Tkinter window for the Silvia dashboard. Not an HTTP redirect."""
from __future__ import annotations

import importlib
import json
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

import systems
import world as world_mod

from layout import content_extent, layout_tree, tree_root, viewport_overflow
from theme import DEFAULT_SCHEME, kind_fill, paint_tokens, palette, select
from trees import ROW_PX, _match, diagrams_view, expand_tree, list_overflow, popout_node
from world import command_pairs, page_ids, page_view, select_entity, switch_page

# Quiet reload while the window is open. Overview still skips hub, Pi, Grok Bot, and source-bus.
AUTO_REFRESH_MS = 3000
_OVERVIEW_HTTP_PROBES = ("mempalace.hub", "grok.bot", "pi.lan", "cli.source_bus")


def painted_command_pairs() -> tuple[tuple[str, str], ...]:
    """Command names and descriptions the Commands page paints. No file I/O."""
    return command_pairs()


def _brain_detail_lines() -> list[str]:
    """Read the butler brain registry. Overview probes stay off."""
    import sys

    root = Path.home() / ".grok" / "silvia"
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        import brains

        return list(brains.detail_lines())
    except Exception:
        return []


class SilviaDashboard(tk.Tk):
    """Local Windows UI: sidebar pages + named overview game + live diagrams."""

    def __init__(
        self,
        world: dict[str, Any],
        *,
        on_refresh: Callable[[], dict[str, Any]] | None = None,
        start_in_tray: bool = False,
    ):
        super().__init__()
        self.title("Silvia System — Dashboard")
        try:
            from tray_icon import ensure_icon

            self.iconbitmap(default=str(ensure_icon()))
        except Exception:
            pass
        self.geometry("1720x980+40+20")
        self.minsize(1400, 760)
        self._tray = None
        self._hiding = False
        self._allow_show = not start_in_tray
        if start_in_tray:
            self.withdraw()
            self.bind("<Map>", self._stay_in_tray)
        self.world = world
        self.on_refresh = on_refresh
        self.selected_id = None
        pal = palette(world.get("scheme") or DEFAULT_SCHEME)
        self.configure(bg=pal["background"])
        self.diagram_section = select(world.get("layout_id"), world.get("scheme")).get("section") or "giant"
        self.search_var = tk.StringVar()
        self._build()
        self._apply_chrome()
        self.bind("<Configure>", self._on_resize)
        self._refresh_busy = False
        self._pending = None
        self._auto_refresh_after = None
        self._rendering = False
        self._render_again = False
        self._task_open: set[str] = set()
        self._session_popouts: dict[str, Any] = {}
        self._sessions_device: str | None = None
        self._debug_on = True
        self._sessions_pathway: dict[str, str] | None = None
        self._sessions_section: str | None = None
        self._pending_session: dict[str, Any] | None = None
        self._systems_mtime = self._systems_file_mtime()
        self.render()
        self._schedule_auto_refresh()
        self._schedule_update_check(1200)

    def _pal(self) -> dict[str, Any]:
        return paint_tokens(self.world.get("scheme") or DEFAULT_SCHEME)

    def _apply_chrome(self) -> None:
        pal = self._pal()
        bg, chrome, text, accent = pal["background"], pal["chrome"], pal["text"], pal["accent"]
        self.configure(bg=bg)
        for w in (self.header, self.body, self.main, self.tools, self.section_bar, self.status):
            w.configure(bg=bg)
        self.nav.configure(bg=chrome)
        self.nav_label.configure(bg=chrome, fg=text)
        self.page_heading.configure(bg=bg, fg=text)
        self.page_sub.configure(bg=bg, fg=pal["muted"])
        self.refresh_btn.configure(bg=chrome, fg=text, activebackground=chrome, activeforeground=accent)
        self.boot_btn.configure(bg=chrome, fg=text, activebackground=chrome, activeforeground=accent)
        self.update_btn.configure(bg=chrome, fg=accent, activebackground=chrome, activeforeground=accent)
        self.search_label.configure(bg=bg, fg=text)
        self.search_entry.configure(bg=chrome, fg=text, insertbackground=text)
        self.search_count.configure(bg=bg, fg=pal["muted"])
        self.list_frame.configure(bg=bg)
        self.canvas.configure(bg=bg)
        for extra in (getattr(self, "systems_canvas", None), getattr(self, "game_canvas", None)):
            if extra is not None:
                extra.configure(bg=bg)
        self.detail.configure(bg=chrome, fg=text, insertbackground=text)
        self.status.configure(fg=text)
        panes = getattr(self, "overview_panes", None)
        if panes is not None:
            panes.configure(bg=pal["muted"])
        style = ttk.Style(self)
        self._style_scrollbars(style, pal)
        style.configure("Title.TLabel", background=bg, foreground=text, font=("Segoe UI", 16, "bold"))
        style.configure("Sub.TLabel", background=bg, foreground=accent, font=("Segoe UI", 10))
        idle = chrome
        for pid, btn in self.nav_buttons.items():
            if pid != (self.world.get("page") or "overview"):
                btn.configure(bg=idle, fg=text)
        for sid, btn in self.section_btns.items():
            if sid != self.diagram_section:
                btn.configure(bg=idle, fg=text)

    def _build(self) -> None:
        pal = self._pal()
        bg, chrome, text = pal["background"], pal["chrome"], pal["text"]
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", background=bg, foreground=text, font=("Georgia", 22))
        style.configure("Sub.TLabel", background=bg, foreground=pal["muted"], font=("Segoe UI", 10))

        self.header = tk.Frame(self, bg=bg)
        self.header.pack(fill="x", padx=20, pady=(16, 6))
        self.page_heading = tk.Label(self.header, text="Overview", bg=bg, fg=text, font=("Georgia", 22))
        self.page_heading.pack(side="left")
        self.page_sub = tk.Label(self.header, text="", bg=bg, fg=pal["muted"], font=("Segoe UI", 10))
        self.page_sub.pack(side="left", padx=(16, 0), pady=(8, 0))
        self.refresh_btn = tk.Button(
            self.header,
            text="Refresh",
            command=self.refresh,
            bg=chrome,
            fg=text,
            activebackground=chrome,
            activeforeground=pal["accent"],
            relief="flat",
            padx=12,
            pady=4,
            font=("Segoe UI", 10),
        )
        self.refresh_btn.pack(side="right")
        self.boot_btn = tk.Button(
            self.header,
            text=self._boot_label(),
            command=self._toggle_boot,
            bg=chrome,
            fg=text,
            activebackground=chrome,
            activeforeground=pal["accent"],
            relief="flat",
            padx=12,
            pady=4,
            font=("Segoe UI", 10),
        )
        self.boot_btn.pack(side="right", padx=(0, 8))
        self.update_btn = tk.Button(
            self.header,
            text="Update",
            command=self._apply_dashboard_update,
            bg=chrome,
            fg=pal["accent"],
            activebackground=chrome,
            activeforeground=pal["accent"],
            relief="flat",
            padx=12,
            pady=4,
            font=("Segoe UI", 10, "bold"),
        )
        self._update_offer = None
        self._update_after = None

        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        self.nav = tk.Frame(self.body, bg=chrome, width=196)
        self.nav.pack(side="left", fill="y", padx=(0, 16))
        self.nav.pack_propagate(False)
        self.nav_label = tk.Label(self.nav, text="Silvia", bg=chrome, fg=text, font=("Georgia", 18))
        self.nav_label.pack(anchor="w", padx=16, pady=(16, 12))
        self.nav_buttons: dict[str, tk.Button] = {}
        titles = {p["id"]: p["title"] for p in (self.world.get("pages") or [])}
        for pid in page_ids():
            btn = tk.Button(
                self.nav,
                text=titles.get(pid, pid),
                anchor="w",
                bg=chrome,
                fg=text,
                activebackground=chrome,
                activeforeground=pal["accent"],
                relief="flat",
                bd=0,
                padx=16,
                pady=7,
                font=("Segoe UI", 11),
                command=lambda p=pid: self.go(p),
            )
            btn.pack(fill="x", padx=8, pady=1)
            self.nav_buttons[pid] = btn

        self.main = tk.Frame(self.body, bg=bg)
        self.main.pack(side="left", fill="both", expand=True)
        self.tools = tk.Frame(self.main, bg=bg)
        self.tools.pack(fill="x", pady=(0, 8))
        self.search_label = tk.Label(self.tools, text="Find", bg=bg, fg=pal["muted"], font=("Segoe UI", 10))
        self.search_label.pack(side="left", padx=(0, 8))
        self.search_entry = tk.Entry(
            self.tools,
            textvariable=self.search_var,
            bg=chrome,
            fg=text,
            insertbackground=text,
            relief="flat",
            font=("Segoe UI", 11),
        )
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 0))
        self.search_count = tk.Label(self.tools, text="", bg=bg, fg=pal["muted"], font=("Segoe UI", 10))
        self.search_count.pack(side="left", padx=(12, 0))
        self._find_count = 0
        self._find_targets: list[tuple[tk.Canvas, int]] = []
        self._find_match_ids: list[str] = []
        self._find_scrolled_for = ""
        self.search_entry.bind("<Return>", self._find_next)
        self.search_var.trace_add("write", lambda *_: self.render())

        self.section_bar = tk.Frame(self.main, bg=bg)
        self.section_bar.pack(fill="x", pady=(4, 4))
        self.section_btns: dict[str, tk.Button] = {}
        for sid, title in (("running", "Running"), ("available", "Available"), ("giant", "Giant tree")):
            btn = tk.Button(
                self.section_bar,
                text=title,
                bg=chrome,
                fg=text,
                relief="flat",
                command=lambda s=sid: self._set_section(s),
            )
            btn.pack(side="left", padx=4)
            self.section_btns[sid] = btn

        self.list_frame = tk.Frame(self.main, bg=bg)
        self.list_frame.pack(fill="both", expand=True)
        self.list_frame.grid_rowconfigure(0, weight=1)
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.vscroll = ttk.Scrollbar(self.list_frame, orient="vertical", style="Silvia.Vertical.TScrollbar")
        self.hscroll = ttk.Scrollbar(self.list_frame, orient="horizontal", style="Silvia.Horizontal.TScrollbar")
        self.canvas = tk.Canvas(
            self.list_frame,
            bg=bg,
            highlightthickness=0,
            xscrollcommand=self.hscroll.set,
            yscrollcommand=self.vscroll.set,
        )
        self.vscroll.config(command=self.canvas.yview)
        self.hscroll.config(command=self.canvas.xview)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vscroll.grid(row=0, column=1, sticky="ns")
        self.hscroll.grid_remove()
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<B1-Motion>", self._token_drag)
        self.canvas.bind("<ButtonRelease-1>", self._token_release)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._wheel_x)
        self._token_plots = []
        self._token_zoom_hits = []
        self._token_press = None
        self._token_window = None
        self._token_drawn = None
        self.hits: list[dict[str, Any]] = []
        self.system_hits: list[dict[str, Any]] = []
        self.game_hits: list[dict[str, Any]] = []
        self.overview_panes = None
        self.systems_canvas = None
        self.game_canvas = None
        self.detail = tk.Text(
            self.main,
            height=2,
            bg=chrome,
            fg=text,
            insertbackground=text,
            wrap="word",
            relief="flat",
            font=("Segoe UI", 11),
            padx=12,
            pady=6,
        )
        self.detail.pack(fill="x", pady=(10, 0))
        self.status = tk.Label(self, text="", bg=bg, fg=pal["muted"], anchor="w", font=("Segoe UI", 10))
        self.status.pack(fill="x", padx=20, pady=(6, 12))

    def _set_section(self, sid: str) -> None:
        self.diagram_section = sid
        self.render()

    def go(self, page_id: str) -> None:
        self.world = switch_page(self.world, page_id)
        self.render()
        if page_id == "usage":
            self._start_refresh_read()

    def refresh(self) -> None:
        if self.on_refresh is not None:
            page = str(self.world.get("page") or "overview")
            fresh = self.on_refresh(page) if self._refresh_takes_page() else self.on_refresh()
            self.world = switch_page(fresh, page)
        self.render()

    def _refresh_takes_page(self) -> bool:
        fn = self.on_refresh
        if fn is None:
            return False
        try:
            code = getattr(fn, "__code__", None)
            if code is None:
                return True
            # A zero-arg callback still works. A page argument is optional.
            return code.co_argcount + code.co_kwonlyargcount > 0 or bool(code.co_flags & 0x04)
        except Exception:
            return True

    def _schedule_auto_refresh(self, delay_ms: int | None = None) -> None:
        if getattr(self, "_auto_refresh_after", None) is not None:
            return
        delay = AUTO_REFRESH_MS if delay_ms is None else delay_ms
        self._auto_refresh_after = self.after(delay, self._auto_refresh)

    def _schedule_update_check(self, delay_ms: int | None = None) -> None:
        import dashboard_update

        delay = dashboard_update.CHECK_INTERVAL_MS if delay_ms is None else delay_ms
        try:
            self._update_after = self.after(delay, self._check_dashboard_update)
        except Exception:
            self._update_after = None

    def _show_update_button(self, show: bool) -> None:
        button = getattr(self, "update_btn", None)
        if button is None:
            return
        try:
            mapped = bool(button.winfo_ismapped())
        except Exception:
            return
        if show and not mapped:
            button.pack(side="right", padx=(0, 8), before=self.boot_btn)
        elif not show and mapped:
            button.pack_forget()

    def _check_dashboard_update(self) -> None:
        self._update_after = None

        def work() -> None:
            try:
                import dashboard_update

                result = dashboard_update.check_for_update(Path(__file__).resolve().parent)
            except Exception as exc:
                result = {"available": False, "reason": str(exc), "files": []}
            try:
                if result.get("available"):
                    from dashboard_debug import note

                    note("update-available", str(len(result.get("files") or [])))
            except Exception:
                pass

            def apply() -> None:
                if not self.winfo_exists():
                    return
                available = bool(result.get("available"))
                self._update_offer = result if available else None
                self._show_update_button(available)
                if available:
                    self.update_btn.configure(text="Update", state="normal")
                    if not getattr(self, "_update_noted", False):
                        self.status.configure(text="An update is ready.")
                        self._update_noted = True
                else:
                    self._update_noted = False

            try:
                self.after(0, apply)
            except Exception:
                return

        threading.Thread(target=work, daemon=True).start()
        self._schedule_update_check()

    def _apply_dashboard_update(self) -> None:
        if not self._update_offer:
            return
        self.update_btn.configure(state="disabled", text="Updating...")

        def work() -> None:
            try:
                import dashboard_update

                result = dashboard_update.apply_available(Path(__file__).resolve().parent)
            except Exception as exc:
                result = {"ok": False, "reason": str(exc)}

            def done() -> None:
                if not self.winfo_exists():
                    return
                if not result.get("ok"):
                    self.update_btn.configure(state="normal", text="Update")
                    self.status.configure(text=str(result.get("reason") or "The update did not apply."))
                    return
                self.update_btn.configure(text="Restarting...")
                try:
                    import dashboard_update

                    dashboard_update.schedule_restart(Path(__file__).resolve().parent)
                except Exception as exc:
                    self.status.configure(text=str(exc))
                    return
                self.after(200, lambda: os._exit(0))

            try:
                self.after(0, done)
            except Exception:
                return

        threading.Thread(target=work, daemon=True).start()

    def _systems_file_mtime(self) -> float | None:
        path = Path(getattr(systems, "__file__", "") or "")
        try:
            return path.stat().st_mtime if path.is_file() else None
        except OSError:
            return None

    def _reload_systems(self) -> None:
        """Pick up a new inventory row written while this window is open."""
        mtime = self._systems_file_mtime()
        if mtime is None or mtime == getattr(self, "_systems_mtime", None):
            return
        importlib.reload(systems)
        world_mod.is_system = systems.is_system
        world_mod.open_system = systems.open_system
        world_mod.overview_systems = systems.overview_systems
        self._systems_mtime = mtime

    def _reuse_overview_probes(self, fresh: dict[str, Any]) -> dict[str, Any]:
        """A skipped overview read must not erase a health check already on screen."""
        old = self.world.get("probes") if isinstance(self.world.get("probes"), dict) else {}
        probes = dict(fresh.get("probes") or {})
        kept: dict[str, dict[str, Any]] = {}
        for key in _OVERVIEW_HTTP_PROBES:
            body = probes.get(key) if isinstance(probes.get(key), dict) else {}
            previous = old.get(key) if isinstance(old.get(key), dict) else None
            if body.get("skipped") and previous is not None and not previous.get("skipped"):
                probes[key] = previous
                kept[key] = previous
        if not kept:
            return fresh
        out = dict(fresh)
        out["probes"] = probes
        entities = []
        old_ent = {e.get("id"): e for e in self.world.get("entities") or [] if e.get("kind") == "probe"}
        for ent in fresh.get("entities") or []:
            if ent.get("kind") == "probe" and ent.get("id") in kept and ent.get("id") in old_ent:
                prev = old_ent[ent.get("id")]
                ent = dict(ent)
                ent["ok"] = prev.get("ok")
                ent["description"] = prev.get("description")
            entities.append(ent)
        out["entities"] = entities
        return out

    def _world_stamp(self, state: dict[str, Any]) -> tuple[Any, ...]:
        systems_rows = tuple(
            (
                str(row.get("id") or ""),
                str(row.get("name") or ""),
                str(row.get("path") or ""),
                row.get("presence"),
                str(row.get("purpose") or ""),
            )
            for row in (state.get("systems") or [])
            if isinstance(row, dict)
        )
        resources = tuple(
            sorted(
                (
                    str(ent.get("id") or ""),
                    str(ent.get("name") or ""),
                    str(ent.get("category") or ""),
                    str(ent.get("description") or ""),
                )
                for ent in (state.get("entities") or [])
                if isinstance(ent, dict) and ent.get("kind") == "resource"
            )
        )
        capabilities = tuple(
            sorted(
                str(ent.get("id") or "")
                for ent in (state.get("entities") or [])
                if isinstance(ent, dict) and ent.get("kind") == "capability"
            )
        )
        probes = state.get("probes") if isinstance(state.get("probes"), dict) else {}
        probe_rows = tuple(
            (
                str(key),
                body.get("ok") if isinstance(body, dict) else None,
                bool(body.get("skipped")) if isinstance(body, dict) else False,
                str(body.get("path") or "") if isinstance(body, dict) else "",
            )
            for key, body in sorted(probes.items(), key=lambda item: str(item[0]))
        )
        usage = state.get("usage") if isinstance(state.get("usage"), dict) else {}
        products = tuple(
            (
                str(row.get("id") or ""),
                row.get("percent"),
                bool(row.get("known")),
            )
            for row in (usage.get("products") or [])
            if isinstance(row, dict)
        )
        history = usage.get("tokens") if isinstance(usage.get("tokens"), dict) else {}
        usage_row = (
            usage.get("credit_usage_percent"),
            usage.get("remaining_percent"),
            str(usage.get("subscription_tier") or ""),
            str(usage.get("period_end") or ""),
            products,
            history.get("total"),
            history.get("input"),
            history.get("output"),
            (history.get("cost") or {}).get("api") if isinstance(history.get("cost"), dict) else None,
            (history.get("cost") or {}).get("subscription") if isinstance(history.get("cost"), dict) else None,
            str(history.get("earliest") or ""),
        )
        return (systems_rows, resources, capabilities, probe_rows, usage_row)

    def _capture_scroll(self) -> dict[str, tuple[float, float]]:
        saved: dict[str, tuple[float, float]] = {}
        for name in ("canvas", "systems_canvas", "game_canvas"):
            canvas = getattr(self, name, None)
            if canvas is None:
                continue
            try:
                saved[name] = (float(canvas.yview()[0]), float(canvas.xview()[0]))
            except tk.TclError:
                continue
        return saved

    def _restore_scroll(self, saved: dict[str, tuple[float, float]]) -> None:
        for name, (y_pos, x_pos) in saved.items():
            canvas = getattr(self, name, None)
            if canvas is None:
                continue
            try:
                canvas.yview_moveto(y_pos)
                canvas.xview_moveto(x_pos)
            except tk.TclError:
                continue

    def _start_refresh_read(self) -> None:
        if self.on_refresh is None or self._refresh_busy:
            return
        try:
            self._reload_systems()
        except Exception:
            pass
        page = str(self.world.get("page") or "overview")
        self._refresh_busy = True

        def work() -> None:
            try:
                fresh = self.on_refresh(page) if self._refresh_takes_page() else self.on_refresh()
            except Exception:
                fresh = None
            self._pending = (page, fresh)
            self._refresh_busy = False

        threading.Thread(target=work, name="silvia-dashboard-refresh", daemon=True).start()

    def _apply_pending(self) -> bool:
        pending = self._pending
        if pending is None:
            return False
        self._pending = None
        page, fresh = pending
        if not isinstance(fresh, dict):
            return True
        try:
            if str(self.world.get("page") or "overview") != page:
                return True
            if page in ("", "overview"):
                fresh = self._reuse_overview_probes(fresh)
            fresh = switch_page(fresh, page or "overview")
            if self._world_stamp(fresh) == self._world_stamp(self.world):
                # Session liveness is not in the catalog stamp. A quiet reload
                # still has to drop a pid that exited.
                if page == "sessions":
                    scrolls = self._capture_scroll()
                    self.render()
                    self._restore_scroll(scrolls)
                return True
            selected = self.world.get("selected")
            selected_id = selected.get("id") if isinstance(selected, dict) else None
            scrolls = self._capture_scroll()
            self.world = fresh
            if selected_id:
                self.world = select_entity(self.world, str(selected_id))
            self.render()
            self._restore_scroll(scrolls)
        except tk.TclError:
            return True
        except Exception:
            return True
        return True

    def _auto_refresh(self) -> None:
        self._auto_refresh_after = None
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if self._pending is not None:
            self._apply_pending()
            self._schedule_auto_refresh(AUTO_REFRESH_MS)
            return
        if self._refresh_busy:
            self._schedule_auto_refresh(200)
            return
        self._start_refresh_read()
        self._schedule_auto_refresh(200)

    def destroy(self) -> None:
        self._pending_session = None
        try:
            self.unbind("<Configure>")
        except tk.TclError:
            pass
        try:
            pending = self.tk.splitlist(self.tk.call("after", "info"))
        except tk.TclError:
            pending = ()
        for job in pending:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self._auto_refresh_after = None
        for pop in list(getattr(self, "_session_popouts", {}).values()):
            try:
                pop.close_popout()
            except Exception:
                pass
        self._session_popouts = {}
        super().destroy()

    def _on_resize(self, _event: tk.Event | None = None) -> None:  # type: ignore[name-defined]
        if getattr(self, "canvas", None):
            self.after_idle(self.render)

    def _wheel(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        if (self.world.get("page") or "") == "usage":
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)
            plot = self._plot_at(x, y)
            if plot is not None:
                self._zoom_token_wheel(plot, x, int(getattr(event, "delta", 0) or 0))
                return
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _wheel_x(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def _click(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        y = self.canvas.canvasy(event.y)
        x = self.canvas.canvasx(event.x)
        page = self.world.get("page") or "overview"
        if page == "usage":
            for hit in list(getattr(self, "_token_zoom_hits", ()) or ()):
                if hit["x0"] <= x <= hit["x1"] and hit["y0"] <= y <= hit["y1"]:
                    self._token_press = None
                    self.set_token_zoom(str(hit["preset"]))
                    return
            plot = self._plot_at(x, y)
            if plot is not None:
                self._token_press = {"x": x, "y": y, "plot": plot}
                return
        self._token_press = None
        for hit in self.hits:
            if hit.get("x0") is not None:
                inside = hit["x0"] <= x <= hit["x1"] and hit["y0"] <= y <= hit["y1"]
            else:
                inside = hit["y0"] <= y <= hit["y1"]
            if inside:
                if page == "task-view" and str(hit.get("id") or "").startswith("choice:"):
                    key = str(hit["id"])
                    if key in self._task_open:
                        self._task_open.remove(key)
                    else:
                        self._task_open.add(key)
                    self.render()
                    return
                if page == "sessions" and str(hit.get("id") or "").startswith("device:"):
                    self._sessions_device = str(hit["id"]).split(":", 1)[1]
                    self._sessions_section = None
                    self.render()
                    return
                if page == "sessions" and hit.get("id") == "debug-toggle":
                    self._debug_on = not bool(getattr(self, "_debug_on", False))
                    self.render()
                    return
                if page == "sessions" and (
                    str(hit.get("id") or "").startswith("active:")
                    or str(hit.get("id") or "").startswith("history:")
                ):
                    kind, device_id = str(hit["id"]).split(":", 1)
                    self._sessions_device = device_id
                    self._sessions_section = kind
                    self.render()
                    return
                if page == "sessions" and hit.get("id") == "new-session":
                    device = dict(hit.get("device") or {})
                    if device.get("local") and device.get("launcher"):
                        self._launch_new_session()
                    elif device.get("tailscale_ip") and not device.get("local"):
                        self._request_remote_session(device)
                    elif device.get("pathway"):
                        self._show_device_pathway(device)
                    return
                if page == "sessions" and str(hit.get("id") or "").startswith("resume:"):
                    row = dict(hit.get("session") or {})
                    if row.get("remote_ip"):
                        self._request_remote_session(
                            {
                                "id": self._sessions_device,
                                "hostname": row.get("remote_host") or self._sessions_device,
                                "tailscale_ip": row.get("remote_ip"),
                            },
                            resume_session=str(row.get("session_id") or ""),
                        )
                    else:
                        self._launch_resumed_session(row)
                    return
                if page == "sessions" and str(hit.get("id") or "").startswith("background:"):
                    from sessions_live import session_background, set_session_background

                    sid = str(hit["id"]).split(":", 1)[1]
                    set_session_background(sid, not session_background(sid))
                    self.render()
                    return
                if page == "sessions" and str(hit.get("id") or "").startswith("session:"):
                    self._open_session_popout(dict(hit.get("session") or {}))
                    return
                if page == "live-diagrams" and self.diagram_section in ("running", "available"):
                    self._popout_tree(hit["id"])
                elif page == "live-diagrams" and self.diagram_section == "giant":
                    if self._toggle_collapse(hit["id"]):
                        self.render()
                        return
                    self._popout_giant(hit["id"])
                else:
                    self.world = select_entity(self.world, hit["id"])
                    self.selected_id = hit["id"]
                self.render()
                return

    def _popout_tree(self, tree_id: str) -> None:
        diagrams = self.world.get("diagrams") or {}
        items = list(diagrams.get(self.diagram_section) or [])
        for it in items:
            if it.get("id") == tree_id:
                self.world["selected"] = expand_tree(it)
                return

    def _toggle_collapse(self, node_id: str) -> bool:
        graphic = getattr(self, "_last_graphic", None) or {}
        box = next((n for n in (graphic.get("nodes") or []) if n.get("id") == node_id), None)
        if not box or not box.get("collapsible"):
            return False
        diagrams = dict(self.world.get("diagrams") or {})
        collapsed = {str(x) for x in (diagrams.get("collapsed") or [])}
        nid = str(node_id)
        if nid in collapsed:
            collapsed.remove(nid)
        else:
            collapsed.add(nid)
        diagrams["collapsed"] = sorted(collapsed)
        self.world["diagrams"] = diagrams
        return True

    def _popout_giant(self, node_id: str) -> None:
        giant = (self.world.get("diagrams") or {}).get("giant") or {}

        def find(node: dict[str, Any]) -> dict[str, Any] | None:
            if str(node.get("id")) == node_id:
                return popout_node(node)
            for c in node.get("children") or []:
                if isinstance(c, dict):
                    hit = find(c)
                    if hit:
                        return hit
            return None

        found = find(giant)
        if found:
            self.world["selected"] = found

    def render(self) -> None:
        if self._rendering:
            self._render_again = True
            return
        self._rendering = True
        self._render_again = False
        try:
            self._render_now()
        finally:
            self._rendering = False
            if self._render_again:
                self._render_again = False
                self.after_idle(self.render)

    def _apply_task_focus(self) -> None:
        path = Path.home() / ".grok" / "task-view" / "focus.json"
        pref = Path.home() / ".grok" / "task-view" / "preference.json"
        if not path.is_file():
            return
        visible = True
        if pref.is_file():
            try:
                data = json.loads(pref.read_text(encoding="utf-8"))
                if "visible" in data:
                    visible = bool(data["visible"])
            except (OSError, json.JSONDecodeError):
                visible = True
        if not visible:
            return
        try:
            focus = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        try:
            path.unlink()
        except OSError:
            pass
        if str(focus.get("page") or "") == "task-view" and self.world.get("page") != "task-view":
            self.world = switch_page(self.world, "task-view")

    def _render_now(self) -> None:
        self._apply_task_focus()
        self._apply_chrome()
        page = self.world.get("page") or "overview"
        pal = self._pal()
        for pid, btn in self.nav_buttons.items():
            active = pid == page
            btn.configure(
                bg=pal["chrome"],
                fg=pal["accent"] if active else pal["text"],
                font=("Segoe UI", 11, "bold" if active else "normal"),
            )
        show_sections = page == "live-diagrams"
        if show_sections:
            self.section_bar.pack(fill="x", pady=(8, 4), before=self.canvas.master)
            pal = self._pal()
            for sid, btn in self.section_btns.items():
                active = sid == self.diagram_section
                btn.configure(
                    bg=pal["chrome"],
                    fg=pal["accent"] if active else pal["text"],
                    font=("Segoe UI", 10, "bold" if active else "normal"),
                    relief="flat",
                    padx=10,
                    pady=4,
                )
        else:
            self.section_bar.pack_forget()
        if page != "overview":
            self._use_shared_canvas()
        self.canvas.delete("all")
        self.hits = []
        self.system_hits = []
        self.game_hits = []
        self._arm_find(0, [])
        view = page_view(self.world, page)
        if page == "overview":
            self._draw_named_game(view)
        elif page == "live-diagrams":
            self._draw_diagrams(view)
        elif page == "usage":
            self._draw_usage(view)
        elif page == "task-view":
            from task_view_page import draw_task_view

            self.hits = draw_task_view(self.canvas, view, pal, expanded=self._task_open)
        elif page == "sessions":
            self._draw_sessions(view)
        elif page == "commands":
            self._draw_commands(view)
        else:
            self._draw_page_list(view)
        self._present_find()
        self._mark_selected()
        self.page_heading.configure(text=str(view.get("page_title") or page))
        self.page_sub.configure(text=self._page_sub(view))
        self.detail.delete("1.0", "end")
        selected = self.world.get("selected")
        if page == "usage":
            used = view.get("usage_percent")
            left = view.get("usage_remaining")
            week = view.get("usage_week_label") or ""
            as_of = view.get("usage_as_of_label") or ""
            usage_note = str(view.get("usage_note") or "SuperGrok Heavy weekly usage, not disk presence")
            when = f"This week {week}" if week else ""
            if as_of:
                when = f"{when}, as of {as_of}".strip(", ")
            lines = [
                usage_note,
                f"Used {used}%    Left {left}%",
                when,
                "Chat, Voice, Bot, Imagine, and Build share one weekly pool.",
            ]
            drawn = getattr(self, "_token_drawn", None) or {}
            if drawn.get("loaded") and drawn.get("total") is not None:
                lines.append(f"Total tokens {int(drawn['total']):,}")
                if drawn.get("input") is not None:
                    lines.append(f"input {int(drawn['input']):,}")
                if drawn.get("output") is not None:
                    lines.append(f"output {int(drawn['output']):,}")
                if drawn.get("earliest"):
                    lines.append(f"Earliest {drawn['earliest']}")
            self.detail.insert("1.0", "\n".join(line for line in lines if line))
        elif selected:
            self.detail.insert("1.0", self._format_selected(selected))
        elif page == "commands":
            self.detail.insert("1.0", "Entry-point commands for this dashboard.")
        else:
            self.detail.insert("1.0", "Select a name to read where it lives.")
        self._fit_detail()
        probes = {e["id"]: e for e in self.world.get("entities") or [] if e.get("kind") == "probe"}
        bits = []
        for key, label in (
            ("mempalace.hub", "Hub"),
            ("grok.bot", "Bot"),
            ("pi.lan", "Pi"),
            ("probe.orchestrator", "Watch"),
        ):
            ent = probes.get(key) or {}
            ok = ent.get("ok")
            if ok is True:
                state = "up"
            elif ok is None:
                state = "not checked"
            else:
                state = "down"
            bits.append(f"{label} {state}")
        self.status.configure(text="    ".join(bits))

    def _apply_scroll(self, content_h: int, content_w: int | None = None) -> None:
        view_w = max(self.canvas.winfo_width(), 1)
        view_h = max(self.canvas.winfo_height(), 1)
        cw = max(int(content_w or view_w), view_w)
        ch = max(int(content_h), view_h)
        self.canvas.configure(scrollregion=(0, 0, cw, ch))
        ov = viewport_overflow(
            {"nodes": [{"x": 0, "y": 0, "w": cw, "h": ch}]},
            view_w,
            view_h,
        )
        if ov.get("v_scroll_needed"):
            self.vscroll.grid(row=0, column=1, sticky="ns")
        else:
            self.vscroll.grid_remove()
        if ov.get("h_scroll_needed"):
            self.hscroll.grid(row=1, column=0, sticky="ew")
        else:
            self.hscroll.grid_remove()

    def _draw_usage(self, view: dict[str, Any]) -> None:
        pal = self._pal()
        w = max(self.canvas.winfo_width(), 360)
        q = self._find_query()
        used = view.get("usage_percent")
        left = view.get("usage_remaining")
        y = 16
        self.canvas.create_text(
            16,
            y,
            text=str(view.get("usage_tier") or "SuperGrok Heavy"),
            fill=pal["heading"],
            anchor="nw",
            font=("Georgia", 22),
        )
        y += 32
        usage_note = str(view.get("usage_note") or "SuperGrok Heavy weekly usage, not disk presence")
        self.canvas.create_text(16, y, text=usage_note, fill=pal["muted"], anchor="nw", font=("Segoe UI", 11))
        y += 24
        start = view.get("usage_week_start_label")
        end = view.get("usage_week_end_label")
        as_of = view.get("usage_as_of_label")
        week = view.get("usage_week_label")
        date_bits = []
        if week:
            date_bits.append(f"This week: {week}")
        elif start and end:
            date_bits.append(f"This week: {start} – {end}")
        elif end:
            date_bits.append(f"Resets {end}")
        if as_of:
            date_bits.append(f"As of {as_of}")
        if date_bits:
            self.canvas.create_text(
                16,
                y,
                text="    ".join(date_bits),
                fill=pal["muted"],
                anchor="nw",
                font=("Segoe UI", 11),
            )
            y += 28
        half = max((w - 48) // 2, 180)
        for index, (title, val, fill) in enumerate(
            (
                ("Used this week", used, pal["accent"]),
                ("Left this week", left, pal["muted"]),
            )
        ):
            x = 16 + index * (half + 16)
            self.canvas.create_text(x, y, text=title, fill=pal["muted"], anchor="nw", font=("Segoe UI", 11))
            shown = "—" if val is None else f"{val:g}%" if isinstance(val, (int, float)) else str(val)
            self.canvas.create_text(x, y + 22, text=shown, fill=pal["text"], anchor="nw", font=("Georgia", 28))
            bar_w = max(half - 8, 160)
            self.canvas.create_rectangle(x, y + 64, x + bar_w, y + 72, fill=pal["card"], outline="")
            try:
                frac = max(0.0, min(1.0, float(str(val).replace("%", "")) / 100.0))
            except (TypeError, ValueError):
                frac = 0.0
            if frac > 0:
                self.canvas.create_rectangle(x, y + 64, x + int(bar_w * frac), y + 72, fill=fill, outline="")
        y += 96
        self.canvas.create_text(16, y, text="Share of this week", fill=pal["text"], anchor="nw", font=("Segoe UI", 12))
        y += 28
        products = list(view.get("usage_products") or [])
        if not products:
            products = [
                {"id": f"usage.{pid}", "label": label, "percent": None, "known": False}
                for pid, label in (("chat", "Chat"), ("voice", "Voice"), ("bot", "Bot"), ("imagine", "Imagine"), ("build", "Build"))
            ]
        if q:
            products = [
                rec
                for rec in products
                if q in f"{rec.get('label') or ''} {rec.get('id') or ''}".lower()
            ]
        first_product_y: int | None = None
        for rec in products:
            if first_product_y is None:
                first_product_y = y
            label = rec.get("label") or rec.get("id")
            pct = rec.get("percent") if rec.get("known") else "—"
            self.canvas.create_rectangle(16, y, w - 24, y + 36, fill=pal["card"], outline=pal["outline"])
            self.canvas.create_text(28, y + 8, text=str(label), fill=pal["text"], anchor="nw", font=("Segoe UI", 12, "bold"))
            self.canvas.create_text(w - 36, y + 8, text=str(pct), fill=pal["accent"], anchor="ne", font=("Segoe UI", 12, "bold"))
            y += 44
        y += 12
        y = self._draw_token_tracker(view, y, w, pal)
        self._apply_scroll(y + 16, w)
        if q:
            targets: list[tuple[tk.Canvas, int]] = []
            count = len(products)
            tier = str(view.get("usage_tier") or "SuperGrok Heavy")
            if q in tier.lower():
                count += 1
                targets.append((self.canvas, 16))
            if first_product_y is not None:
                targets.append((self.canvas, first_product_y))
            product_id = str(products[0].get("id") or "") if products else ""
            product_ids = [str(rec.get("id") or "") for rec in products if rec.get("id")]
            self._arm_find(count, targets, product_id or None, product_ids)

    def _events_for_zoom(self, view: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if view is None:
            view = page_view(self.world, "usage")
        return [row for row in (view.get("token_events") or []) if isinstance(row, dict)]

    def _active_token_report(self, view: dict[str, Any]) -> dict[str, Any]:
        from token_history import apply_window, report_from_events

        events = self._events_for_zoom(view)
        window = getattr(self, "_token_window", None)
        if not events and not view.get("token_loaded"):
            return {
                "loaded": False,
                "total": view.get("token_total"),
                "input": view.get("token_input"),
                "output": view.get("token_output"),
                "cost": view.get("token_cost") or {},
                "plans": list(view.get("token_plans") or []),
                "sources": list(view.get("token_sources") or []),
                "charts": view.get("token_charts") or {},
                "series": list(view.get("token_series") or []),
                "window": view.get("token_window") or {"preset": "all", "start": None, "end": None},
                "earliest": view.get("token_earliest"),
            }
        plans = list(view.get("token_plans") or [])
        if isinstance(window, dict) and window.get("start") and window.get("end"):
            return apply_window(
                events,
                str(window["start"]),
                str(window["end"]),
                preset=str(window.get("preset") or "custom"),
                plans=plans,
            )
        preset = str((window or {}).get("preset") or "all")
        return report_from_events(events, preset=preset if preset in {"all", "day", "hour"} else "all", plans=plans)

    def set_token_window(self, start: str, end: str, preset: str = "custom") -> None:
        self._token_window = {"preset": preset, "start": start, "end": end}
        self.render()

    def set_token_zoom(self, preset: str) -> None:
        from token_history import window_for_preset

        self._token_window = window_for_preset(self._events_for_zoom(), preset)
        self.render()

    def _plot_at(self, x: float, y: float) -> dict[str, Any] | None:
        for plot in list(getattr(self, "_token_plots", ()) or ()):
            if plot["x0"] <= x <= plot["x1"] and plot["y0"] <= y <= plot["y1"]:
                return plot
        return None

    def _token_scale(self, plot: dict[str, Any]) -> tuple[float, float]:
        origin = float(plot.get("scale_x0", plot["x0"]))
        end = float(plot.get("scale_x1", plot["x1"]))
        return origin, max(1.0, end - origin)

    def _zoom_token_wheel(self, plot: dict[str, Any], x: float, delta: int) -> None:
        from token_history import pointer_window, window_for_preset

        if delta == 0:
            return
        events = self._events_for_zoom()
        current = getattr(self, "_token_window", None) or window_for_preset(events, "all")
        full = window_for_preset(events, "all")
        origin, width = self._token_scale(plot)
        window = pointer_window(
            current,
            x,
            origin,
            width,
            factor=0.5 if delta > 0 else 2.0,
            full=full,
            bars=list(plot.get("bars") or []),
        )
        if window.get("start") and window.get("end"):
            self.set_token_window(str(window["start"]), str(window["end"]), preset=str(window.get("preset") or "custom"))

    def _zoom_token_span(self, plot: dict[str, Any], x0: float, x1: float) -> None:
        from token_history import pointer_window, window_for_preset

        events = self._events_for_zoom()
        current = getattr(self, "_token_window", None) or window_for_preset(events, "all")
        full = window_for_preset(events, "all")
        origin, width = self._token_scale(plot)
        window = pointer_window(current, x0, origin, width, x1=x1, full=full, bars=list(plot.get("bars") or []))
        if window.get("start") and window.get("end"):
            self.set_token_window(str(window["start"]), str(window["end"]), preset=str(window.get("preset") or "custom"))

    def _token_drag(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        press = getattr(self, "_token_press", None)
        if not press:
            return
        x = self.canvas.canvasx(event.x)
        plot = press["plot"]
        self.canvas.delete("token-zoom-rubber")
        left = min(press["x"], x)
        right = max(press["x"], x)
        self.canvas.create_rectangle(
            left,
            plot["y0"],
            right,
            plot["y1"],
            outline=self._pal()["accent"],
            width=2,
            tags=("token-zoom-rubber",),
        )

    def _token_release(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        press = getattr(self, "_token_press", None)
        self._token_press = None
        try:
            self.canvas.delete("token-zoom-rubber")
        except tk.TclError:
            return
        if not press:
            return
        x = self.canvas.canvasx(event.x)
        if abs(x - press["x"]) < 8:
            return
        self._zoom_token_span(press["plot"], press["x"], x)

    def _draw_token_tracker(self, view: dict[str, Any], y: int, w: int, pal: dict[str, Any]) -> int:
        report = self._active_token_report(view)
        self._token_drawn = report
        self._token_plots = []
        self._token_zoom_hits = []
        self.canvas.create_text(16, y, text="Token usage", fill=pal["heading"], anchor="nw", font=("Georgia", 18), tags=("token-heading",))
        y += 30
        total = report.get("total")
        total_text = "—" if total is None else f"{int(total):,}"
        self.canvas.create_text(16, y, text="Total tokens", fill=pal["muted"], anchor="nw", font=("Segoe UI", 11), tags=("token-total-label",))
        self.canvas.create_text(16, y + 18, text=total_text, fill=pal["text"], anchor="nw", font=("Georgia", 26), tags=("token-total-value",))
        earliest = report.get("earliest") or "—"
        self.canvas.create_text(w - 24, y + 10, text=f"Earliest {earliest}", fill=pal["muted"], anchor="ne", font=("Segoe UI", 10), tags=("token-earliest",))
        y += 58
        half = max((w - 48) // 2, 160)
        for index, (label, key) in enumerate((("input", "input"), ("output", "output"))):
            value = report.get(key)
            shown = "—" if value is None else f"{int(value):,}"
            x = 16 + index * (half + 16)
            self.canvas.create_text(x, y, text=label, fill=pal["muted"], anchor="nw", font=("Segoe UI", 11), tags=(f"token-{key}-label",))
            self.canvas.create_text(x, y + 18, text=shown, fill=pal["text"], anchor="nw", font=("Georgia", 18), tags=(f"token-{key}-value",))
        y += 48
        cost = report.get("cost") if isinstance(report.get("cost"), dict) else {}

        def _usd(value: Any) -> str:
            if value is None:
                return "—"
            return f"${float(value):,.2f}"

        for label, key in (("API list price", "api"), ("Subscription", "subscription"), ("Difference", "difference")):
            self.canvas.create_text(16, y, text=label, fill=pal["muted"], anchor="nw", font=("Segoe UI", 11), tags=(f"token-cost-{key}-label",))
            self.canvas.create_text(w - 36, y, text=_usd(cost.get(key)), fill=pal["text"], anchor="ne", font=("Segoe UI", 12, "bold"), tags=(f"token-cost-{key}-value",))
            y += 22
        y += 10
        self.canvas.create_text(16, y, text="By source", fill=pal["text"], anchor="nw", font=("Segoe UI", 12), tags=("token-sources-label",))
        y += 24
        for rec in list(report.get("sources") or []):
            label = str(rec.get("label") or rec.get("id") or "")
            if rec.get("known") and rec.get("tokens") is not None:
                shown = f"{int(rec['tokens']):,}"
            else:
                shown = "—"
            self.canvas.create_rectangle(16, y, w - 24, y + 32, fill=pal["card"], outline=pal["outline"], tags=("token-source-row",))
            self.canvas.create_rectangle(16, y, 22, y + 32, fill=str(rec.get("color") or pal["accent"]), outline="", tags=("token-source-swatch",))
            self.canvas.create_text(32, y + 6, text=label, fill=pal["text"], anchor="nw", font=("Segoe UI", 12, "bold"), tags=("token-source-label",))
            self.canvas.create_text(w - 36, y + 6, text=shown, fill=pal["text"], anchor="ne", font=("Segoe UI", 12, "bold"))
            y += 38
        y += 8
        window = report.get("window") or {}
        active = str(window.get("preset") or "")
        x = 16
        for preset, title in (("all", "All time"), ("day", "Day"), ("hour", "Hour")):
            width = 92
            fill = pal["accent"] if active == preset else pal["card"]
            fg = pal["background"] if active == preset else pal["text"]
            self.canvas.create_rectangle(x, y, x + width, y + 28, fill=fill, outline=pal["outline"], tags=(f"token-zoom-{preset}", "token-zoom"))
            self.canvas.create_text(x + width / 2, y + 14, text=title, fill=fg, font=("Segoe UI", 10, "bold"), tags=(f"token-zoom-{preset}",))
            self._token_zoom_hits.append({"preset": preset, "x0": x, "y0": y, "x1": x + width, "y1": y + 28})
            x += width + 8
        if window.get("start") and window.get("end"):
            self.canvas.create_text(
                x + 8,
                y + 6,
                text=f"{window['start']}  –  {window['end']}",
                fill=pal["muted"],
                anchor="nw",
                font=("Segoe UI", 10),
                tags=("token-window",),
            )
        y += 42
        y = self._draw_token_chart(report, "total", "Total over time", y, w, pal)
        y += 18
        return self._draw_token_chart(report, "by_source", "By source", y, w, pal)

    def _draw_token_chart(self, report: dict[str, Any], which: str, title: str, y: int, w: int, pal: dict[str, Any]) -> int:
        self.canvas.create_text(16, y, text=title, fill=pal["text"], anchor="nw", font=("Segoe UI", 12), tags=(f"token-chart-title-{which}",))
        y += 22
        x0, x1 = 16, max(w - 24, 200)
        plot_h = 140
        y1 = y + plot_h
        tag = "token-chart-total" if which == "total" else "token-chart-sources"
        self.canvas.create_rectangle(x0, y, x1, y1, fill=pal["card"], outline=pal["outline"], tags=(tag, "token-chart"))
        inner_x = x0 + 8
        inner_y = y + 8
        inner_h = plot_h - 16
        plot_w = max(1, x1 - x0 - 16)
        self._token_plots.append(
            {
                "which": which,
                "x0": x0,
                "y0": y,
                "x1": x1,
                "y1": y1,
                "scale_x0": inner_x,
                "scale_x1": inner_x + plot_w,
                "bars": [],
            }
        )
        charts = report.get("charts") or {}
        block = charts.get("total" if which == "total" else "by_source") or {}
        buckets = [bucket for bucket in (block.get("buckets") or []) if isinstance(bucket, dict)]
        window = report.get("window") or {}
        if not buckets or not window.get("start") or not window.get("end"):
            self.canvas.create_text(inner_x, inner_y, text="No tokens in this window", fill=pal["muted"], anchor="nw", font=("Segoe UI", 10))
            return y1
        from token_history import hour_bar_box

        peak = max(int(bucket.get("tokens") or 0) for bucket in buckets) or 1
        color_of = {str(row.get("id")): str(row.get("color") or "#3DDC97") for row in (report.get("sources") or []) if isinstance(row, dict)}
        for bucket in buckets:
            bx, slot = hour_bar_box(str(window["start"]), str(window["end"]), str(bucket.get("start") or ""), inner_x, plot_w)
            if slot <= 0:
                continue
            hour_end_x = bx + slot
            hour_tag = "token-hour-" + str(bucket.get("start") or "").replace("-", "").replace(":", "")
            if which == "total":
                tokens = int(bucket.get("tokens") or 0)
                if tokens <= 0:
                    continue
                height = max(1, int(inner_h * tokens / peak))
                self._token_plots[-1]["bars"].append(
                    {"x0": bx, "x1": hour_end_x, "start": bucket.get("start"), "end": bucket.get("end")}
                )
                self.canvas.create_rectangle(
                    bx,
                    inner_y + inner_h - height,
                    hour_end_x,
                    inner_y + inner_h,
                    fill=pal["accent"],
                    outline="",
                    tags=("token-total-bar", hour_tag),
                )
                continue
            parts = [(str(sid), int(val)) for sid, val in (bucket.get("sources") or {}).items() if int(val or 0) > 0]
            if not parts:
                continue
            count = len(parts)
            for part_index, (sid, val) in enumerate(parts):
                left = bx + slot * part_index / count
                right = hour_end_x if part_index == count - 1 else bx + slot * (part_index + 1) / count
                height = max(1, int(inner_h * val / peak))
                self._token_plots[-1]["bars"].append(
                    {"x0": left, "x1": right, "start": bucket.get("start"), "end": bucket.get("end")}
                )
                self.canvas.create_rectangle(
                    left,
                    inner_y + inner_h - height,
                    right,
                    inner_y + inner_h,
                    fill=color_of.get(sid, "#E8E6D8"),
                    outline="",
                    tags=("token-source-bar", f"token-source-bar-{sid}", hour_tag),
                )
        return y1

    def _style_scrollbars(self, style: ttk.Style, pal: dict[str, Any]) -> None:
        bg, chrome, muted = pal["background"], pal["chrome"], pal["muted"]
        thumb = {
            "background": chrome,
            "troughcolor": bg,
            "bordercolor": bg,
            "darkcolor": chrome,
            "lightcolor": chrome,
            "arrowcolor": muted,
            "gripcount": 0,
            "borderwidth": 0,
            "relief": "flat",
            "width": 10,
        }
        for name, trough, thumb_el in (
            ("Silvia.Vertical.TScrollbar", "Vertical.Scrollbar.trough", "Vertical.Scrollbar.thumb"),
            ("Silvia.Horizontal.TScrollbar", "Horizontal.Scrollbar.trough", "Horizontal.Scrollbar.thumb"),
        ):
            style.layout(
                name,
                [(trough, {"sticky": "nswe", "children": [(thumb_el, {"expand": True, "sticky": "nswe"})]})],
            )
            style.configure(name, **thumb)
            style.map(name, background=[("active", pal["accent"]), ("pressed", pal["accent"])])

    def _fit_detail(self) -> None:
        text = self.detail.get("1.0", "end-1c")
        if not text or text == "Select a name to read where it lives.":
            self.detail.configure(height=2)
            return
        lines = text.count("\n") + 1
        self.detail.configure(height=max(2, min(12, lines)))

    def _mark_sash_user(self, event: tk.Event | None = None) -> None:  # type: ignore[name-defined]
        panes = getattr(self, "overview_panes", None)
        if panes is None or event is None:
            return
        try:
            sash_y = int(panes.sash_coord(0)[1])
        except tk.TclError:
            return
        if abs(int(event.y) - sash_y) <= 8:
            self._sash_user = True

    def _place_overview_sash(self) -> None:
        """Park the split in the gap after a whole system row.

        sash_place's number is not the visible height of the top pane, so this
        measures that height and nudges the sash until the clip lands on the gap.
        """
        self._sash_pending = False
        if getattr(self, "_sash_user", False):
            return
        panes = getattr(self, "overview_panes", None)
        top = getattr(self, "overview_top", None)
        if panes is None or top is None or (self.world.get("page") or "overview") != "overview":
            return
        height = panes.winfo_height()
        if height < 280 or top.winfo_height() < 40:
            tries = getattr(self, "_sash_tries", 0)
            if tries < 6:
                self._sash_tries = tries + 1
                self.after(40, self._place_overview_sash)
            return
        pitch, y0 = 58, 12
        bottom_floor = max(280, int(height * 0.46))
        top_cap = max(height - bottom_floor, y0 + 3 * pitch)
        n = 3
        for candidate in range(3, 8):
            if y0 + candidate * pitch <= top_cap:
                n = candidate
        desired = y0 + n * pitch
        actual = int(top.winfo_height())
        if abs(actual - desired) <= 2:
            self._sash_tries = 0
            return
        tries = getattr(self, "_sash_tries", 0)
        if tries > 6:
            return
        self._sash_tries = tries + 1
        try:
            current = int(panes.sash_coord(0)[1])
        except tk.TclError:
            current = actual
        panes.sash_place(0, 0, int(current + (desired - actual)))
        self.after(40, self._place_overview_sash)

    def _use_shared_canvas(self) -> None:
        panes = getattr(self, "overview_panes", None)
        if panes is not None:
            panes.grid_remove()
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vscroll.grid(row=0, column=1, sticky="ns")
        self.hscroll.grid_remove()

    def _scroll_one(self, canvas: tk.Canvas, content_h: int, content_w: int | None = None) -> None:
        view_w = max(canvas.winfo_width(), 1)
        view_h = max(canvas.winfo_height(), 1)
        cw = max(int(content_w or view_w), view_w)
        ch = max(int(content_h), view_h)
        canvas.configure(scrollregion=(0, 0, cw, ch))

    def _find_query(self) -> str:
        return (self.search_var.get() or "").strip().lower()

    def _arm_find(
        self,
        count: int,
        targets: list[tuple[tk.Canvas, int]],
        select_id: str | None = None,
        match_ids: list[str] | None = None,
    ) -> None:
        self._find_count = count
        self._find_targets = targets
        self._find_select_id = select_id or ""
        seen: list[str] = []
        for raw in match_ids or []:
            eid = str(raw or "").strip()
            if eid and eid not in seen:
                seen.append(eid)
        self._find_match_ids = seen

    def _select_find_match(self, entity_id: str) -> bool:
        """Same detail a click would open. An id with no record leaves the current detail."""
        eid = str(entity_id or "").strip()
        if not eid:
            return False
        chosen = select_entity(self.world, eid)
        if not isinstance(chosen.get("selected"), dict):
            return False
        self.world = chosen
        self.selected_id = eid
        return True

    def _find_next(self, _event: tk.Event | None = None) -> str:
        """Enter in Find: the next match, then the outline and the detail follow."""
        ids = list(getattr(self, "_find_match_ids", []) or [])
        if not ids:
            return "break"
        current = str(self.selected_id or "")
        start = ids.index(current) if current in ids else -1
        for step in range(1, len(ids) + 1):
            if not self._select_find_match(ids[(start + step) % len(ids)]):
                continue
            self.render()
            self._scroll_selected_into_view()
            break
        return "break"

    def _scroll_selected_into_view(self) -> None:
        selected = str(self.selected_id or "")
        if not selected:
            return
        surfaces = (
            (self.canvas, self.hits),
            (getattr(self, "systems_canvas", None), self.system_hits),
            (getattr(self, "game_canvas", None), self.game_hits),
        )
        for canvas, hits in surfaces:
            if canvas is None:
                continue
            for hit in hits or []:
                if str(hit.get("id") or "") == selected and hit.get("y0") is not None:
                    self._scroll_match_into_view(canvas, int(hit["y0"]))
                    return

    def _present_find(self) -> None:
        query = (self.search_var.get() or "").strip()
        if not query:
            self.search_count.configure(text="")
            self._find_scrolled_for = ""
            return
        count = int(getattr(self, "_find_count", 0) or 0)
        if count == 0:
            text = "No matches"
        elif count == 1:
            text = "1 match"
        else:
            text = f"{count} matches"
        self.search_count.configure(text=text)
        if query == getattr(self, "_find_scrolled_for", ""):
            return
        self._find_scrolled_for = query
        for canvas, y in getattr(self, "_find_targets", []) or []:
            self._scroll_match_into_view(canvas, y)
        if count:
            self._select_find_match(str(getattr(self, "_find_select_id", "") or ""))

    def _mark_selected(self) -> None:
        """Accent outline on the card whose detail is open."""
        selected = str(self.selected_id or "")
        if not selected:
            chosen = self.world.get("selected")
            if isinstance(chosen, dict):
                selected = str(chosen.get("id") or "")
        if not selected:
            return
        accent = self._pal()["accent"]
        surfaces = (
            (self.canvas, self.hits),
            (getattr(self, "systems_canvas", None), self.system_hits),
            (getattr(self, "game_canvas", None), self.game_hits),
        )
        for canvas, hits in surfaces:
            if canvas is None:
                continue
            for hit in hits or []:
                if str(hit.get("id") or "") != selected:
                    continue
                y0, y1 = hit.get("y0"), hit.get("y1")
                if y0 is None or y1 is None:
                    continue
                x0 = hit.get("x0")
                x1 = hit.get("x1")
                if x0 is None or x1 is None:
                    x0 = 16
                    x1 = max(int(canvas.winfo_width()) - 24, int(x0) + 200)
                canvas.create_rectangle(
                    int(x0),
                    int(y0),
                    int(x1),
                    int(y1),
                    outline=accent,
                    width=2,
                    fill="",
                    tags=("selected-mark",),
                )

    def _matching_node_ids(self, node: dict[str, Any] | None, query: str) -> list[str]:
        """Ids whose own name matches. Ancestors kept only to draw a child do not count."""
        found: list[str] = []

        def walk(cur: dict[str, Any]) -> None:
            if _match(cur, query=query):
                nid = str(cur.get("id") or "")
                if nid:
                    found.append(nid)
            for child in cur.get("children") or cur.get("nodes") or []:
                if isinstance(child, dict):
                    walk(child)

        if isinstance(node, dict):
            walk(node)
        return found

    def _arm_diagram_list(self, query: str, items: list[dict[str, Any]], first_y: int | None) -> None:
        if not str(query).strip():
            return
        targets = [(self.canvas, first_y)] if first_y is not None else []
        select_id = str(items[0].get("id") or "") if items else ""
        match_ids = [str(it.get("id") or "") for it in items if it.get("id")]
        self._arm_find(len(items), targets, select_id or None, match_ids)

    def _arm_diagram_tree(self, query: str, root: dict[str, Any] | None) -> None:
        if not str(query).strip():
            return
        ids = self._matching_node_ids(root, query)
        wanted = set(ids)
        target: int | None = None
        for hit in self.hits:
            if str(hit.get("id") or "") in wanted and hit.get("y0") is not None:
                target = int(hit["y0"])
                break
        targets = [(self.canvas, target)] if target is not None else []
        self._arm_find(len(ids), targets, ids[0] if ids else None, ids)

    def _scroll_match_into_view(self, canvas: tk.Canvas, y: int) -> None:
        try:
            canvas.update_idletasks()
            parts = str(canvas.cget("scrollregion") or "").split()
            total = float(parts[3]) if len(parts) == 4 else 0.0
            view_h = max(int(canvas.winfo_height()), 1)
            if total <= view_h or total <= 0:
                canvas.yview_moveto(0)
                return
            top = max(0.0, float(y) - 8.0)
            canvas.yview_moveto(min(1.0, top / total))
        except (tk.TclError, ValueError, IndexError):
            return

    def _clip(self, text: str, limit: int) -> str:
        raw = " ".join(str(text or "").split())
        if len(raw) <= limit:
            return raw
        if limit < 2:
            return raw[:limit]
        return raw[: limit - 1] + "…"

    def _region_title(self, region: str) -> str:
        names = {
            "hostlands": "Hosting",
            "silvia-precinct": "Butler",
            "memory-archipelago": "Memory",
            "catalog-continents": "Catalog",
            "watch-range": "Watch",
            "usage-bay": "Usage",
        }
        return names.get(region, region.replace("-", " ").strip().capitalize() or "Other")

    def _page_sub(self, view: dict[str, Any]) -> str:
        page = view.get("page") or ""
        if page == "overview":
            rows = list(view.get("systems") or [])
            here = sum(1 for row in rows if row.get("presence") is True)
            missing = len(rows) - here
            return f"{here} on disk, {missing} missing"
        if page == "sessions":
            count = len(view.get("sessions") or [])
            if count == 1:
                return "1 active session"
            return f"{count} active sessions"
        if page == "commands":
            count = len(view.get("commands") or [])
            if count == 1:
                return "1 command"
            return f"{count} commands"
        if page == "usage":
            return str(view.get("usage_note") or "")
        count = len(view.get("view_ids") or [])
        if count == 1:
            return "1 row"
        return f"{count} rows"

    def _format_selected(self, selected: dict[str, Any]) -> str:
        if selected.get("path") and (selected.get("purpose") or selected.get("presence") is not None):
            presence = selected.get("presence")
            word = "Missing from disk" if presence == "absent" else "On disk"
            lines = [
                str(selected.get("title") or selected.get("name") or selected.get("id") or ""),
                word,
                str(selected.get("path") or ""),
                str(selected.get("purpose") or ""),
            ]
            if str(selected.get("id") or "") == "silvia":
                lines.extend(_brain_detail_lines())
            return "\n".join(lines)
        name = str(selected.get("name") or selected.get("title") or selected.get("id") or "")
        role = str(selected.get("role") or selected.get("kind") or "")
        ok = selected.get("ok")
        if ok is True:
            state = "Up"
        elif ok is False:
            state = "Down"
        elif selected.get("kind") == "probe":
            state = "Not checked"
        else:
            state = ""
        desc = str(selected.get("description") or selected.get("preview") or "")
        kids = selected.get("nodes") or selected.get("children") or []
        if kids and not desc:
            desc = ", ".join(str(c.get("name") or c.get("id")) for c in kids if isinstance(c, dict))
        lines = [line for line in (name, role, state, desc) if line]
        return "\n".join(lines[:4])

    def _wheel_systems(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        if self.systems_canvas is not None:
            self.systems_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _wheel_game(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        if self.game_canvas is not None:
            self.game_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _click_systems(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        self._click_surface(self.systems_canvas, self.system_hits, event)

    def _click_game(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        self._click_surface(self.game_canvas, self.game_hits, event)

    def _click_surface(self, canvas: tk.Canvas | None, hits: list[dict[str, Any]], event: tk.Event) -> None:  # type: ignore[name-defined]
        if canvas is None:
            return
        y = canvas.canvasy(event.y)
        x = canvas.canvasx(event.x)
        for hit in hits:
            if hit.get("x0") is not None:
                inside = hit["x0"] <= x <= hit["x1"] and hit["y0"] <= y <= hit["y1"]
            else:
                inside = hit["y0"] <= y <= hit["y1"]
            if inside:
                self.world = select_entity(self.world, hit["id"])
                self.selected_id = hit["id"]
                self.render()
                return

    def _draw_named_game(self, view: dict[str, Any]) -> None:
        """Systems on the top canvas. Catalog game pieces on the bottom canvas."""
        self.canvas.grid_remove()
        self.vscroll.grid_remove()
        self.hscroll.grid_remove()
        pal = self._pal()
        bg = pal["background"]
        if self.overview_panes is None:
            self.overview_panes = tk.PanedWindow(
                self.list_frame, orient=tk.VERTICAL, sashwidth=3, sashrelief="flat", bg=pal["muted"], bd=0
            )
            self.overview_panes.bind("<ButtonRelease-1>", self._mark_sash_user, add="+")
            top = tk.Frame(self.overview_panes, bg=bg)
            bottom = tk.Frame(self.overview_panes, bg=bg)
            self.overview_top = top
            self.overview_bottom = bottom
            for frame in (top, bottom):
                frame.grid_rowconfigure(0, weight=1)
                frame.grid_columnconfigure(0, weight=1)
            self.systems_scroll = ttk.Scrollbar(top, orient="vertical", style="Silvia.Vertical.TScrollbar")
            self.systems_canvas = tk.Canvas(top, bg=bg, highlightthickness=0, yscrollcommand=self.systems_scroll.set)
            self.systems_scroll.config(command=self.systems_canvas.yview)
            self.systems_canvas.grid(row=0, column=0, sticky="nsew")
            self.systems_scroll.grid(row=0, column=1, sticky="ns")
            self.game_scroll = ttk.Scrollbar(bottom, orient="vertical", style="Silvia.Vertical.TScrollbar")
            self.game_canvas = tk.Canvas(bottom, bg=bg, highlightthickness=0, yscrollcommand=self.game_scroll.set)
            self.game_scroll.config(command=self.game_canvas.yview)
            self.game_canvas.grid(row=0, column=0, sticky="nsew")
            self.game_scroll.grid(row=0, column=1, sticky="ns")
            self.overview_panes.add(top, stretch="always", minsize=180)
            self.overview_panes.add(bottom, stretch="always", minsize=220)
            self.systems_canvas.bind("<Button-1>", self._click_systems)
            self.game_canvas.bind("<Button-1>", self._click_game)
            self.systems_canvas.bind("<MouseWheel>", self._wheel_systems)
            self.game_canvas.bind("<MouseWheel>", self._wheel_game)
        self.overview_panes.grid(row=0, column=0, columnspan=2, sticky="nsew")
        if not getattr(self, "_sash_pending", False):
            self._sash_pending = True
            self.after_idle(self._place_overview_sash)
        systems_canvas = self.systems_canvas
        game_canvas = self.game_canvas
        assert systems_canvas is not None and game_canvas is not None
        systems_canvas.delete("all")
        game_canvas.delete("all")
        q = (self.search_var.get() or "").strip().lower()
        systems = list(view.get("systems") or [])
        ents = list(view.get("view_entities") or [])
        if q:
            systems = [
                row
                for row in systems
                if q in f"{row.get('name')} {row.get('id')} {row.get('purpose')} {row.get('path')}".lower()
            ]
            ents = [e for e in ents if q in f"{e.get('name')} {e.get('role')} {e.get('id')}".lower()]
        canvas_w = max(systems_canvas.winfo_width(), 720)
        margin = 16
        gap = 10
        cols = 2 if canvas_w >= 680 else 1
        col_w = (canvas_w - margin * 2 - gap * (cols - 1)) // cols
        row_h = 50
        y0 = 12
        for index, row in enumerate(systems):
            col = index % cols
            x = margin + col * (col_w + gap)
            y = y0 + (index // cols) * (row_h + 8)
            here = row.get("presence") is True
            mark = pal["accent"] if here else pal["muted"]
            word = "here" if here else "missing"
            systems_canvas.create_rectangle(x, y, x + 3, y + row_h, fill=mark, outline="")
            systems_canvas.create_rectangle(x + 3, y, x + col_w, y + row_h, fill=pal["card"], outline="")
            systems_canvas.create_text(
                x + 14,
                y + 6,
                text=self._clip(str(row.get("name") or ""), 28),
                fill=pal["text"],
                anchor="nw",
                font=("Segoe UI", 12),
            )
            systems_canvas.create_text(x + col_w - 12, y + 8, text=word, fill=mark, anchor="ne", font=("Segoe UI", 9))
            path = self._clip(str(row.get("path") or ""), max(18, (col_w - 36) // 7))
            systems_canvas.create_text(
                x + 14,
                y + 28,
                text=f"{row.get('id')}    {path}",
                fill=pal["muted"],
                anchor="nw",
                font=("Segoe UI", 9),
            )
            self.system_hits.append({"id": row.get("id"), "x0": x, "x1": x + col_w, "y0": y, "y1": y + row_h})
        used_rows = (len(systems) + cols - 1) // cols if systems else 1
        self._scroll_one(systems_canvas, y0 + used_rows * (row_h + 8) + 8, canvas_w)

        gwidth = max(game_canvas.winfo_width(), 720)
        chip_w = 168
        chip_h = 30
        chip_gap = 8
        per_row = max(1, (gwidth - margin * 2 + chip_gap) // (chip_w + chip_gap))
        groups: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for ent in ents:
            region = str(ent.get("region") or "other")
            if region not in groups:
                groups[region] = []
                order.append(region)
            groups[region].append(ent)
        gy = 22
        first_chip_y: int | None = None
        chip_ids: list[str] = []
        for region in order:
            items = groups[region]
            game_canvas.create_text(
                margin,
                gy,
                text=f"{self._region_title(region)}  {len(items)}",
                fill=pal["text"],
                anchor="w",
                font=("Georgia", 14),
            )
            gy += 26
            for index, ent in enumerate(items):
                col = index % per_row
                row_index = index // per_row
                x = margin + col * (chip_w + chip_gap)
                y = gy + row_index * (chip_h + chip_gap)
                if first_chip_y is None:
                    first_chip_y = y
                kind_color = kind_fill(str(ent.get("kind")), self.world.get("scheme") or DEFAULT_SCHEME)
                game_canvas.create_rectangle(x, y, x + 3, y + chip_h, fill=kind_color, outline="")
                game_canvas.create_rectangle(x + 3, y, x + chip_w, y + chip_h, fill=pal["card"], outline="")
                game_canvas.create_text(
                    x + 12,
                    y + 7,
                    text=self._clip(str(ent.get("name") or ent.get("label") or ent.get("id") or ""), 20),
                    fill=pal["text"],
                    anchor="nw",
                    font=("Segoe UI", 10),
                )
                self.game_hits.append({"id": ent.get("id"), "x0": x, "x1": x + chip_w, "y0": y, "y1": y + chip_h})
                if ent.get("id"):
                    chip_ids.append(str(ent.get("id")))
            band = (len(items) + per_row - 1) // per_row if items else 0
            gy += band * (chip_h + chip_gap) + 14
        self._scroll_one(game_canvas, max(gy, 40), gwidth)
        if q:
            targets: list[tuple[tk.Canvas, int]] = []
            select_id = ""
            if systems:
                select_id = str(systems[0].get("id") or "")
                targets.append((systems_canvas, y0))
            if first_chip_y is not None:
                targets.append((game_canvas, first_chip_y))
            if not select_id and ents:
                select_id = str(ents[0].get("id") or "")
            match_ids = [str(row.get("id") or "") for row in systems if row.get("id")] + chip_ids
            self._arm_find(len(systems) + len(ents), targets, select_id or None, match_ids)

    def _draw_commands(self, view: dict[str, Any]) -> None:
        pal = self._pal()
        rows = list(view.get("commands") or [])
        query = self._find_query()
        if query:
            rows = [
                row
                for row in rows
                if query in f"{row.get('name')} {row.get('description')}".lower()
            ]
        width = max(self.canvas.winfo_width(), 720)
        wrap = max(width - 64, 280)
        y = 16
        for row in rows:
            name = str(row.get("name") or "")
            description = str(row.get("description") or "")
            item = self.canvas.create_text(
                24,
                y,
                text=f"{name}: {description}",
                fill=pal["text"],
                anchor="nw",
                font=("Segoe UI", 11),
                width=wrap,
            )
            bbox = self.canvas.bbox(item)
            height = max((bbox[3] - bbox[1]) if bbox else 22, 18)
            self.hits.append(
                {
                    "id": f"command:{name}",
                    "x0": 16,
                    "x1": width - 16,
                    "y0": y,
                    "y1": y + height,
                }
            )
            y += height + 12
        self._apply_scroll(y + 16, width)
        if query and rows:
            self._arm_find(len(rows), [(self.canvas, 16)])

    def _draw_sessions(self, view: dict[str, Any]) -> None:
        from sessions_live import device_sections

        pal = self._pal()
        devices = list(view.get("devices") or [])
        if not devices:
            devices = device_sections(list(view.get("sessions") or []))
        query = (self.search_var.get() or "").strip().lower()
        width = max(self.canvas.winfo_width(), 720)
        y = 12
        debug_on = bool(getattr(self, "_debug_on", False))
        self.canvas.create_rectangle(16, y, 140, y + 28, fill=pal["card"], outline=pal["accent"] if debug_on else "")
        self.canvas.create_text(
            28,
            y + 6,
            text="Debug on" if debug_on else "Debug",
            fill=pal["accent"],
            anchor="nw",
            font=("Segoe UI", 11, "bold"),
        )
        self.hits.append({"id": "debug-toggle", "x0": 16, "x1": 140, "y0": y, "y1": y + 28})
        y += 36
        if debug_on:
            from dashboard_debug import log_path, recent

            lines = [f"Log {log_path()}"] + (recent() or ["No picture events yet."])
            for line in lines:
                item = self.canvas.create_text(
                    32,
                    y,
                    text=str(line),
                    fill=pal["muted"],
                    anchor="nw",
                    font=("Consolas", 9),
                    width=width - 64,
                )
                bbox = self.canvas.bbox(item)
                y += max((bbox[3] - bbox[1]) if bbox else 16, 16) + 4
            y += 8
        selected = self._sessions_device
        for device in devices:
            label = str(device.get("label") or device.get("hostname") or device.get("id") or "")
            if query and query not in f"{label} {device.get('id')}".lower():
                sessions = list(device.get("sessions") or [])
                if not any(query in f"{row.get('title')} {row.get('session_id')} {row.get('cwd')}".lower() for row in sessions):
                    continue
            open_device = str(device.get("id") or "") == selected
            self.canvas.create_rectangle(16, y, width - 24, y + 44, fill=pal["card"], outline=pal["accent"] if open_device else "")
            self.canvas.create_text(
                32,
                y + 12,
                text=label,
                fill=pal["text"],
                anchor="nw",
                font=("Segoe UI", 13, "bold"),
            )
            self.hits.append(
                {
                    "id": f"device:{device.get('id')}",
                    "x0": 16,
                    "x1": width - 24,
                    "y0": y,
                    "y1": y + 44,
                    "device": device,
                }
            )
            y += 52
            if not open_device:
                continue
            if not device.get("local"):
                reach = []
                if device.get("tailscale_ip"):
                    reach.append(f"Tailscale {device.get('tailscale_ip')}")
                if device.get("rustdesk_id"):
                    reach.append(f"RustDesk {device.get('rustdesk_id')}")
                state = str(device.get("remote_state") or "")
                if state == "ok":
                    remote_line = "Connected. A click opens the session on this computer."
                elif state == "checking":
                    remote_line = "Asking this computer for its sessions."
                elif state == "offline":
                    remote_line = "This computer did not answer."
                else:
                    remote_line = "A click asks this computer to open the session."
                if reach:
                    remote_line = remote_line + " " + " · ".join(reach)
                self.canvas.create_text(32, y, text=remote_line, fill=pal["muted"], anchor="nw", font=("Segoe UI", 10), width=width - 64)
                y += 28
            note = self._sessions_pathway if isinstance(getattr(self, "_sessions_pathway", None), dict) else None
            if note and note.get("device") == str(device.get("id") or ""):
                item = self.canvas.create_text(
                    32,
                    y,
                    text=str(note.get("text") or ""),
                    fill=pal["text"],
                    anchor="nw",
                    font=("Consolas", 9),
                    width=width - 64,
                )
                bbox = self.canvas.bbox(item)
                y += max((bbox[3] - bbox[1]) if bbox else 36, 36) + 8
            if device.get("launcher") or device.get("pathway"):
                self.canvas.create_rectangle(32, y, width - 24, y + 36, fill=pal["card"], outline=pal["accent"])
                self.canvas.create_text(
                    48,
                    y + 8,
                    text="New session",
                    fill=pal["accent"],
                    anchor="nw",
                    font=("Segoe UI", 12, "bold"),
                )
                self.hits.append(
                    {
                        "id": "new-session",
                        "x0": 32,
                        "x1": width - 24,
                        "y0": y,
                        "y1": y + 36,
                        "device": device,
                    }
                )
                y += 46
            device_id = str(device.get("id") or "")
            state = str(device.get("remote_state") or "")
            if device.get("local") or state == "ok":
                active_empty = "No open sessions"
                history_empty = "No session history"
            elif state == "checking":
                active_empty = "Asking this computer for its sessions."
                history_empty = active_empty
            else:
                active_empty = "This computer did not answer."
                history_empty = active_empty
            y = self._draw_session_group(
                y,
                width,
                pal,
                device_id,
                "active",
                "Active sessions",
                list(device.get("sessions") or []),
                active_empty,
                query,
                openable=True,
            )
            history = list(device.get("history") or [])
            if self._sessions_section == "history" and device_id == selected and not history and device.get("local"):
                from sessions_live import session_history

                home = self.world.get("sessions_home")
                open_ids = {str(row.get("session_id") or "") for row in device.get("sessions") or []}
                history = session_history(Path(home) if home else None, active_ids=open_ids)
            y = self._draw_session_group(
                y,
                width,
                pal,
                device_id,
                "history",
                "Session history",
                history,
                history_empty,
                query,
                openable=False,
                launch=True,
            )
        self._scroll_one(self.canvas, y + 8, width)

    def _draw_session_group(
        self,
        y: int,
        width: int,
        pal: dict[str, Any],
        device_id: str,
        kind: str,
        label: str,
        rows: list[dict[str, Any]],
        empty: str,
        query: str,
        *,
        openable: bool,
        launch: bool = False,
    ) -> int:
        from sessions_live import session_background

        open_group = self._sessions_section == kind and self._sessions_device == device_id
        self.canvas.create_rectangle(32, y, width - 24, y + 36, fill=pal["card"], outline=pal["accent"] if open_group else "")
        self.canvas.create_text(48, y + 8, text=label, fill=pal["text"], anchor="nw", font=("Segoe UI", 12, "bold"))
        self.hits.append({"id": f"{kind}:{device_id}", "x0": 32, "x1": width - 24, "y0": y, "y1": y + 36})
        y += 44
        if not open_group:
            return y
        shown = rows
        if query:
            shown = [
                row
                for row in rows
                if query in f"{row.get('title')} {row.get('session_id')} {row.get('cwd')} {row.get('pid')}".lower()
            ]
        if not shown:
            self.canvas.create_text(64, y, text=empty, fill=pal["muted"], anchor="nw", font=("Segoe UI", 11))
            return y + 28
        for row in shown:
            self.canvas.create_rectangle(48, y, width - 24, y + 52, fill=pal["card"], outline="")
            self.canvas.create_text(
                64,
                y + 6,
                text=self._clip(str(row.get("title") or row.get("session_id") or ""), 80),
                fill=pal["text"],
                anchor="nw",
                font=("Segoe UI", 12),
            )
            detail = str(row.get("session_id") or "")
            if row.get("pid"):
                detail = f"{detail}    pid {row.get('pid')}"
            self.canvas.create_text(64, y + 28, text=self._clip(detail, 110), fill=pal["muted"], anchor="nw", font=("Segoe UI", 9))
            sid = str(row.get("session_id") or "")
            if sid:
                on = session_background(sid)
                tx0, tx1 = width - 152, width - 32
                self.canvas.create_rectangle(tx0, y + 10, tx1, y + 42, fill=pal["card"], outline=pal["accent"] if on else pal["muted"])
                self.canvas.create_text(
                    (tx0 + tx1) // 2,
                    y + 18,
                    text="Background on" if on else "Background off",
                    fill=pal["accent"] if on else pal["muted"],
                    anchor="n",
                    font=("Segoe UI", 9, "bold"),
                )
                self.hits.append({"id": f"background:{sid}", "x0": tx0, "x1": tx1, "y0": y + 10, "y1": y + 42})
            if openable or launch:
                kind = "session" if openable else "resume"
                self.hits.append(
                    {
                        "id": f"{kind}:{row.get('session_id')}",
                        "x0": 48,
                        "x1": width - 24,
                        "y0": y,
                        "y1": y + 52,
                        "session": row,
                    }
                )
            y += 60
        return y

    def _show_device_pathway(self, device: dict[str, Any], resume_session: str = "") -> None:
        """Show the command for another device. Do not start it on this PC."""
        from sessions_live import session_pathway

        command = session_pathway(resume_session)
        host = str(device.get("hostname") or device.get("id") or "that device")
        lines = [f"Run on {host}, not on this PC.", command]
        if device.get("tailscale_ip"):
            lines.append(f"Tailscale {device.get('tailscale_ip')}")
        if device.get("rustdesk_id"):
            lines.append(f"RustDesk {device.get('rustdesk_id')}")
        self._sessions_pathway = {"device": str(device.get("id") or ""), "text": "\n".join(lines), "command": command}
        try:
            self.clipboard_clear()
            self.clipboard_append(command)
        except Exception:
            pass
        self.render()

    def _request_remote_session(self, device: dict[str, Any], resume_session: str = "") -> None:
        """Ask that device to open the session. Do not start it on this PC."""
        from remote_sessions import ask_device

        host = str(device.get("hostname") or device.get("id") or "that device")
        ip = str(device.get("tailscale_ip") or "")
        session_id = str(resume_session or "").strip()
        action = "resume" if session_id else "new-session"
        result = ask_device(ip, action, session_id=session_id)
        if result.get("ok"):
            text = f"Asked {host} to resume {session_id}." if session_id else f"Asked {host} to open a new session."
        else:
            text = f"{host} did not open the session. {result.get('reason') or 'it did not answer'}."
        self._sessions_pathway = {"device": str(device.get("id") or ""), "text": text, "command": ""}
        self.render()

    def _launch_resumed_session(self, row: dict[str, Any]) -> None:
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
            return
        self._launch_new_session(resume_session=session_id)

    def _launch_new_session(self, resume_session: str = "") -> None:
        from sessions_live import device_sections, launch_new_session

        selected = self._sessions_device
        devices = list(self.world.get("devices") or []) or device_sections(list(self.world.get("sessions") or []))
        device = next((item for item in devices if str(item.get("id") or "") == selected), None)
        if device is None:
            return
        launcher = str(device.get("launcher") or "")
        if not launcher:
            return
        before = {str(row.get("session_id") or "") for row in device.get("sessions") or []}
        proc = launch_new_session(launcher=launcher, resume_session=resume_session or None)
        self._pending_session = {
            "before": before,
            "device": selected,
            "started": time.time(),
            "launcher_pid": getattr(proc, "pid", None),
            "resume_session": str(resume_session or ""),
        }
        self._launch_found = None
        threading.Thread(target=self._poll_new_session, daemon=True).start()
        self.after(400, self._check_launch_found)

    def _check_launch_found(self) -> None:
        """Read the launch result on the window thread. The worker never calls Tk."""
        found = getattr(self, "_launch_found", None)
        if found is not None:
            self._launch_found = None
            self._show_launched_session(found)
            return
        if self._pending_session is None:
            return
        try:
            self.after(400, self._check_launch_found)
        except Exception:
            return

    def _poll_new_session(self) -> None:
        """Find the new TUI off the window thread so the dashboard can still close."""
        from sessions_live import (
            grok_descendants,
            is_new_tui_command,
            is_resumed_tui_command,
            live_sessions,
            place_launched_window,
            process_command_line,
        )

        while True:
            pending = self._pending_session
            if not pending:
                return
            if time.time() - float(pending["started"]) > 180:
                self._pending_session = None
                return
            target = None
            launcher_pid = pending.get("launcher_pid")
            if launcher_pid:
                for child in grok_descendants(int(launcher_pid)):
                    try:
                        command = process_command_line(child)
                    except OSError:
                        command = ""
                    wanted = str(pending.get("resume_session") or "")
                    if wanted:
                        matched = is_resumed_tui_command(command, wanted)
                    else:
                        matched = is_new_tui_command(command) and "--resume" not in command.lower()
                    if matched:
                        target = child
                        break
            if target:
                rows = live_sessions()
                match = next((row for row in rows if int(row.get("pid") or 0) == int(target)), None)
                if match is not None:
                    try:
                        place_launched_window(int(target))
                    except OSError:
                        pass
                    self._launch_found = dict(match)
                    self._pending_session = None
                    return
            time.sleep(0.8)

    def _show_launched_session(self, row: dict[str, Any]) -> None:
        from sessions_live import device_sections, live_sessions

        self._pending_session = None
        rows = live_sessions()
        self.world["sessions"] = rows
        roster = self.world.get("devices_roster")
        self.world["devices"] = device_sections(rows, roster_path=Path(roster) if roster else None)
        self._sessions_section = "active"
        self.render()
        self._open_session_popout(row)

    def _open_session_popout(self, row: dict[str, Any]) -> None:
        from sessions_live import SessionPopout

        session_id = str(row.get("session_id") or "")
        if not session_id:
            return
        existing = self._session_popouts.get(session_id)
        if existing is not None:
            try:
                if existing.alive():
                    existing.lift()
                    return
            except Exception:
                pass
        self._session_popouts[session_id] = SessionPopout(self, row)

    def _draw_page_list(self, view: dict[str, Any]) -> None:
        q = (self.search_var.get() or "").strip().lower()
        ents = list(view.get("view_entities") or [])
        if q:
            ents = [e for e in ents if q in f"{e.get('name')} {e.get('id')} {e.get('kind')}".lower()]
        pal = self._pal()
        width = max(self.canvas.winfo_width(), 720)
        y = 8
        system = view.get("system") if isinstance(view.get("system"), dict) else None
        system_match = False
        if system and system.get("id") and q:
            system_match = q in f"{system.get('name')} {system.get('id')} {system.get('path')} {system.get('purpose')}".lower()
        if system and system.get("id"):
            here = system.get("presence") is True
            mark = pal["accent"] if here else pal["muted"]
            self.canvas.create_rectangle(16, y, 19, y + 52, fill=mark, outline="")
            self.canvas.create_rectangle(19, y, width - 24, y + 52, fill=pal["card"], outline="")
            self.canvas.create_text(32, y + 6, text=str(system.get("name") or ""), fill=pal["text"], anchor="nw", font=("Segoe UI", 13))
            self.canvas.create_text(
                32,
                y + 28,
                text=self._clip(f"{'here' if here else 'missing'}    {system.get('path') or ''}", 90),
                fill=pal["muted"],
                anchor="nw",
                font=("Segoe UI", 9),
            )
            self.hits.append({"id": system.get("id"), "x0": 16, "x1": width - 24, "y0": y, "y1": y + 52})
            if system_match:
                self._arm_find(1, [(self.canvas, y)])
            y += 64
        if view.get("page") == "butler-host":
            labels = {
                "mempalace.hub": "Hub",
                "grok.bot": "Bot",
                "pi.lan": "Source",
                "silvia.butler": "Butler",
                "silvia.voice": "Voice",
                "orchestrator": "Watch file",
                "cli.money_loop": "Money loop",
                "cli.steam_lan": "Steam LAN",
                "app.silvia_android": "Android",
                "cli.source_bus": "Bus",
            }
            x = 16
            for row in view.get("health") or []:
                ok = row.get("ok")
                if ok is True:
                    mark = "up"
                    color = pal["accent"]
                elif row.get("skipped") or ok is None:
                    mark = "not checked"
                    color = pal["muted"]
                else:
                    mark = "down"
                    color = pal["muted"]
                label = labels.get(str(row.get("id")), str(row.get("id")))
                box_w = 132
                if x > 16 and x + box_w > width - 16:
                    x = 16
                    y += 52
                self.canvas.create_rectangle(x, y, x + box_w, y + 44, fill=pal["card"], outline="")
                self.canvas.create_text(x + 10, y + 6, text=label, fill=pal["text"], anchor="nw", font=("Segoe UI", 10))
                self.canvas.create_text(x + 10, y + 24, text=mark, fill=color, anchor="nw", font=("Segoe UI", 9))
                hit_id = "probe.orchestrator" if row.get("id") == "orchestrator" else row.get("id")
                self.hits.append({"id": hit_id, "x0": x, "x1": x + box_w, "y0": y, "y1": y + 44})
                x += box_w + 8
            y += 56
        chip_w = 220
        chip_h = 36
        gap = 8
        per_row = max(1, (width - 32 + gap) // (chip_w + gap))
        first_chip_y: int | None = None
        for index, ent in enumerate(ents):
            col = index % per_row
            row_index = index // per_row
            x = 16 + col * (chip_w + gap)
            cy = y + row_index * (chip_h + gap)
            if first_chip_y is None:
                first_chip_y = cy
            self.canvas.create_rectangle(x, cy, x + chip_w, cy + chip_h, fill=pal["card"], outline="")
            self.canvas.create_text(
                x + 10,
                cy + 4,
                text=self._clip(str(ent.get("name") or ent.get("id") or ""), 26),
                fill=pal["text"],
                anchor="nw",
                font=("Segoe UI", 10),
            )
            self.canvas.create_text(
                x + 10,
                cy + 20,
                text=self._clip(str(ent.get("role") or ent.get("kind") or ""), 28),
                fill=pal["muted"],
                anchor="nw",
                font=("Segoe UI", 8),
            )
            self.hits.append({"id": ent.get("id"), "x0": x, "x1": x + chip_w, "y0": cy, "y1": cy + chip_h})
        bands = (len(ents) + per_row - 1) // per_row if ents else 0
        self._apply_scroll(y + bands * (chip_h + gap) + 16, width)
        if q:
            targets: list[tuple[tk.Canvas, int]] = list(getattr(self, "_find_targets", []))
            count = len(ents) + (1 if system_match else 0)
            if first_chip_y is not None and not system_match:
                targets = [(self.canvas, first_chip_y)]
            elif first_chip_y is not None:
                targets.append((self.canvas, first_chip_y))
            select_id = ""
            if system_match and system:
                select_id = str(system.get("id") or "")
            elif ents:
                select_id = str(ents[0].get("id") or "")
            match_ids: list[str] = []
            if system_match and system and system.get("id"):
                match_ids.append(str(system.get("id")))
            match_ids.extend(str(ent.get("id") or "") for ent in ents if ent.get("id"))
            self._arm_find(count, targets, select_id or None, match_ids)

    def _draw_diagrams(self, view: dict[str, Any]) -> None:
        diagrams = view.get("diagrams") or self.world.get("diagrams") or {}
        q = self.search_var.get() or ""
        expand_id = None
        selected = self.world.get("selected") or {}
        if self.diagram_section in ("running", "available") and selected.get("popout") and selected.get("id"):
            expand_id = selected.get("id")
        shown = diagrams_view(
            diagrams,
            section=self.diagram_section,
            query=q,
            expand_id=expand_id,
            scheme=self.world.get("scheme"),
            collapsed=list(diagrams.get("collapsed") or []),
        )
        pal = self._pal()
        y = 8
        if self.diagram_section == "giant":
            self.canvas.create_text(16, y, text="Active tree", fill=pal["heading"], anchor="nw", font=("Georgia", 16))
            y += 32
            self._draw_graphic(shown.get("graphic") or layout_tree(tree_root(shown.get("giant") or {}), scheme=self.world.get("scheme")), 0, y)
            self._arm_diagram_tree(q, shown.get("giant"))
        elif expand_id and shown.get("graphic"):
            self.canvas.create_text(16, y, text=str(selected.get("name") or expand_id), fill=pal["heading"], anchor="nw", font=("Georgia", 16))
            y += 32
            self._draw_graphic(shown["graphic"], 0, y)
            self._arm_diagram_tree(q, shown.get("expanded"))
        else:
            items = list(shown.get(self.diagram_section) or [])
            title = "Running" if self.diagram_section == "running" else "Available"
            self.canvas.create_text(16, y, text=title, fill=pal["heading"], anchor="nw", font=("Georgia", 16))
            y += 32
            first_y: int | None = None
            for it in items:
                if first_y is None:
                    first_y = y
                preview = it.get("preview") or it.get("description") or ""
                self.canvas.create_rectangle(16, y, max(self.canvas.winfo_width() - 24, 220), y + 48, fill=pal["card"], outline="")
                self.canvas.create_text(28, y + 6, text=str(it.get("name") or it.get("id")), fill=pal["text"], anchor="nw", font=("Segoe UI", 12))
                self.canvas.create_text(28, y + 26, text=self._clip(str(preview), 80), fill=pal["muted"], anchor="nw", font=("Segoe UI", 9))
                self.hits.append({"id": it.get("id"), "y0": y, "y1": y + 48})
                y += 56
            self._apply_scroll(y + 8)
            self._arm_diagram_list(q, items, first_y)

    def _round_rect(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        fill: str,
        outline: str,
        width: int = 1,
    ) -> None:
        r = min(max(1, int(radius)), (x2 - x1) // 2, (y2 - y1) // 2)
        self.canvas.create_polygon(
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
            smooth=True,
            fill=fill or "",
            outline=outline,
            width=width,
        )

    def _round_header(self, x: int, y: int, w: int, h: int, hh: int, radius: int, fill: str) -> None:
        """Title strip clipped to the rounded top, including the corner fans."""
        r = min(max(1, int(radius)), w // 2, h // 2, max(1, hh))
        self.canvas.create_arc(x, y, x + 2 * r, y + 2 * r, start=90, extent=90, fill=fill, outline="")
        self.canvas.create_arc(x + w - 2 * r, y, x + w, y + 2 * r, start=0, extent=90, fill=fill, outline="")
        self.canvas.create_rectangle(x + r, y, x + w - r, y + hh, fill=fill, outline="")
        if hh > r:
            self.canvas.create_rectangle(x, y + r, x + w, y + hh, fill=fill, outline="")

    def _draw_graphic(self, graphic: dict[str, Any], ox: int, oy: int) -> tuple[int, int]:
        """Draw the shipped layout boxes and edges — not an indent-text fallback."""
        self._last_graphic = graphic
        max_y = oy
        max_x = ox
        pal = self._pal()
        stroke = graphic.get("edge") or graphic.get("accent") or pal["fallback_stroke"]
        for edge in graphic.get("edges") or []:
            path = edge.get("path") or []
            coords: list[float] = []
            if len(path) >= 4:
                for pt in path:
                    coords.extend([ox + float(pt["x"]), oy + float(pt["y"])])
            else:
                coords = [
                    ox + int(edge["x1"]),
                    oy + int(edge["y1"]),
                    ox + int(edge["x2"]),
                    oy + int(edge["y2"]),
                ]
            self.canvas.create_line(*coords, fill=stroke, width=2, smooth=True, splinesteps=24)
            max_x = max(max_x, int(edge["x1"]) + ox, int(edge["x2"]) + ox)
            max_y = max(max_y, int(edge["y1"]) + oy, int(edge["y2"]) + oy)
        for box in graphic.get("nodes") or []:
            x, y = ox + int(box["x"]), oy + int(box["y"])
            w, h = int(box["w"]), int(box["h"])
            radius = int(box.get("radius") or graphic.get("radius") or 12)
            header = box.get("title_fill") or pal["interior_header"]
            body = box.get("interior_body") or pal["interior_body"]
            inset = box.get("interior_inset") or pal["interior_inset"]
            border = box.get("border") or pal["outline"]
            title = box.get("title_text") or pal["text"]
            stroke = box.get("title_stroke") or title
            chip = box.get("chip") or pal["accent"]
            self._round_rect(x, y, x + w, y + h, radius, body, "")
            hh = 20
            self._round_header(x, y, w, h, hh, radius, header)
            if box.get("chip"):
                self.canvas.create_rectangle(x + radius + 2, y + 5, x + radius + 8, y + 15, fill=chip, outline="")
            mark = " ▸" if box.get("collapsed") else (" ▾" if box.get("collapsible") else "")
            label = str(box.get("name") or box.get("id")) + mark
            for dx, dy in (
                (-2, 0),
                (2, 0),
                (0, -2),
                (0, 2),
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
                (-1, -1),
                (1, -1),
                (-1, 1),
                (1, 1),
            ):
                self.canvas.create_text(x + 14 + dx, y + 4 + dy, text=label, fill=stroke, anchor="nw", font=("Segoe UI", 9, "bold"))
            self.canvas.create_text(x + 14, y + 4, text=label, fill=title, anchor="nw", font=("Segoe UI", 9, "bold"))
            ix0, iy0, ix1, iy1 = x + 8, y + hh + 4, x + w - 8, y + h - 6
            self.canvas.create_rectangle(ix0, iy0, ix1, iy1, fill=inset, outline="")
            feed = list(box.get("feed") or [])
            if len(feed) >= 2:
                fw, fh = max(1, ix1 - ix0), max(1, iy1 - iy0)
                pts = []
                for i, val in enumerate(feed):
                    px = ix0 + int(i * (fw - 1) / (len(feed) - 1))
                    py = iy1 - int(float(val) * (fh - 2)) - 1
                    pts.extend([px, py])
                if len(pts) >= 4:
                    self.canvas.create_line(*pts, fill=pal["accent"], width=1, smooth=True)
            self._round_rect(x, y, x + w, y + h, radius, "", border, width=3)
            self.hits.append({"id": box.get("id"), "y0": y, "y1": y + h, "x0": x, "x1": x + w})
            max_y = max(max_y, y + h + 12)
            max_x = max(max_x, x + w + 12)
        ext = content_extent(graphic)
        self._apply_scroll(max(max_y, ext["content_height"] + oy), max(max_x, ext["content_width"] + ox))
        return max_x, max_y


    def _boot_label(self) -> str:
        from boot_start import enabled

        return "Start at boot: On" if enabled() else "Start at boot: Off"

    def _toggle_boot(self) -> None:
        from boot_start import enabled, set_enabled

        set_enabled(not enabled())
        self.boot_btn.configure(text=self._boot_label())

    def install_tray(self) -> None:
        from tray_icon import TrayBridge

        bridge = TrayBridge(self.after)
        bridge.start(self._show_from_tray, self._quit_from_tray, self._toggle_boot)
        self._tray = bridge
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self.bind("<Unmap>", self._on_unmap)

    def _on_unmap(self, event: Any) -> None:
        if self._tray is None or self._hiding or event.widget is not self:
            return
        try:
            iconic = str(self.state()) == "iconic"
        except tk.TclError:
            return
        if not iconic:
            return
        self._hiding = True
        try:
            self.withdraw()
        finally:
            self._hiding = False

    def _hide_to_tray(self) -> None:
        if self._tray is None:
            self.destroy()
            return
        self.withdraw()

    def _stay_in_tray(self, event: Any) -> None:
        if self._allow_show or event.widget is not self:
            return
        self.after_idle(self.withdraw)

    def _show_from_tray(self) -> None:
        self._allow_show = True
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
        except tk.TclError:
            return

    def _quit_from_tray(self) -> None:
        bridge = self._tray
        self._tray = None
        if bridge is not None:
            bridge.close()
        self.destroy()


def run_window(
    world: dict[str, Any],
    *,
    on_refresh: Callable[[], dict[str, Any]] | None = None,
    start_in_tray: bool = False,
) -> None:
    from tray_icon import claim_or_signal

    if not claim_or_signal():
        return
    app = SilviaDashboard(world, on_refresh=on_refresh, start_in_tray=start_in_tray)
    try:
        app.install_tray()
    except Exception as exc:
        try:
            app.status.configure(text=f"The tray icon did not start: {exc}")
        except Exception:
            pass
        app._allow_show = True
        app.deiconify()
    if start_in_tray and not app._allow_show:
        app.withdraw()
    app.mainloop()
