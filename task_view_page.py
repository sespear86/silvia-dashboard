# -*- coding: utf-8 -*-
"""Draw the task-view spine as boxed nodes and edges.

Task decisions stay off the giant tree. The words Current step, Path taken,
and Chose stay on the nodes so the diagram can be read at a glance.
"""
from __future__ import annotations

from typing import Any

NODE_W = 230
NODE_H = 72
GAP_X = 36
GAP_Y = 28
ORIGIN_X = 24
ORIGIN_Y = 24


def _short(text: str, limit: int = 42) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def _box(
    canvas: Any,
    x: int,
    y: int,
    title: str,
    body: str,
    *,
    fill: str,
    outline: str,
    text: str,
    title_fill: str,
    width: int = NODE_W,
) -> None:
    canvas.create_rectangle(x, y, x + width, y + NODE_H, fill=fill, outline=outline, width=2)
    canvas.create_rectangle(x, y, x + width, y + 22, fill=title_fill, outline=outline, width=1)
    canvas.create_text(x + 10, y + 3, anchor="nw", text=title, fill=text, font=("Segoe UI", 9, "bold"))
    canvas.create_text(
        x + 10,
        y + 30,
        anchor="nw",
        text=_short(body),
        fill=text,
        font=("Segoe UI", 12),
        width=width - 20,
    )


def _arrow(canvas: Any, x1: int, y1: int, x2: int, y2: int, color: str) -> None:
    canvas.create_line(x1, y1, x2, y2, fill=color, width=2, arrow="last")


def draw_task_view(canvas: Any, view: dict, pal: dict, expanded: set[str] | None = None) -> list[dict]:
    open_rows = expanded or set()
    spine = view.get("task_view") or {}
    text = pal.get("text") or "#d7f6ff"
    fill = pal.get("card") or "#071016"
    outline = pal.get("card_outline") or pal.get("accent") or "#7ef9ff"
    accent = pal.get("accent") or "#00e5ff"
    active = pal.get("active_border") or "#a855f7"
    title_fill = pal.get("active_title") or "#7e22ce"
    hits: list[dict] = []
    if spine.get("hidden"):
        _box(
            canvas,
            ORIGIN_X,
            ORIGIN_Y,
            "Task view",
            "Task view is hidden.",
            fill=fill,
            outline=outline,
            text=text,
            title_fill=fill,
            width=320,
        )
        box = canvas.bbox("all")
        if box:
            canvas.configure(scrollregion=box)
        return hits

    tasks = list(spine.get("tasks") or [])
    if not tasks:
        tasks = [
            {
                "taskId": "current",
                "expanded": True,
                "current_step": spine.get("current_step") or "",
                "path_taken": list(spine.get("path_taken") or []),
                "choices": list(spine.get("choices") or []),
            }
        ]
    expanded = next((task for task in tasks if task.get("expanded")), None)
    y = ORIGIN_Y
    task = expanded or {}
    current = str(task.get("current_step") or spine.get("current_step") or "")
    _box(
        canvas,
        ORIGIN_X,
        y,
        "Current step",
        current,
        fill=fill,
        outline=active,
        text=text,
        title_fill=title_fill,
        width=360,
    )
    choices = list(task.get("choices") or spine.get("choices") or [])
    opened_bottom = 0
    for index, choice in enumerate(choices):
        key = f"choice:{index}"
        col = index % 2
        row = index // 2
        cx = ORIGIN_X + 380 + col * 210
        cy = y + row * (NODE_H + 12)
        if index == 0:
            _arrow(canvas, ORIGIN_X + 360, y + NODE_H // 2, cx, cy + NODE_H // 2, accent)
        label = str(choice.get("row") or "Chose")
        _box(
            canvas,
            cx,
            cy,
            "Choice",
            label,
            fill=fill,
            outline=active,
            text=text,
            title_fill=title_fill,
            width=200,
        )
        hits.append({"id": key, "x0": cx, "y0": cy, "x1": cx + NODE_W, "y1": cy + NODE_H})
        if key in open_rows:
            options = [str(item) for item in (choice.get("options") or [])] or ["none"]
            taken = str(choice.get("taken") or "")
            for opt_index, option in enumerate(options):
                oy = cy + NODE_H + 8 + opt_index * (NODE_H + 8)
                _box(
                    canvas,
                    cx,
                    oy,
                    "Option taken" if option == taken else "Option",
                    option,
                    fill=fill,
                    outline=active if option == taken else outline,
                    text=text,
                    title_fill=title_fill if option == taken else fill,
                )
                opened_bottom = max(opened_bottom, oy + NODE_H)
    choice_rows = (len(choices) + 1) // 2 if choices else 0
    choice_bottom = y + max(NODE_H, choice_rows * (NODE_H + 12))
    if opened_bottom:
        choice_bottom = max(choice_bottom, opened_bottom)
    y = choice_bottom + GAP_Y
    path = [str(line) for line in (task.get("path_taken") or spine.get("path_taken") or [])]
    if path:
        _arrow(canvas, ORIGIN_X + 180, y - GAP_Y, ORIGIN_X + NODE_W // 2, y, accent)
    columns = 5 if len(path) > 12 else 3
    path_w = 130 if columns == 5 else NODE_W
    path_h = 46 if columns == 5 else NODE_H
    row_gap = 8 if columns == 5 else 44
    col_gap = 8 if columns == 5 else GAP_X
    nodes: list[tuple[int, int]] = []
    for index, line in enumerate(path):
        col = index % columns
        row = index // columns
        x = ORIGIN_X + col * (path_w + col_gap)
        ny = y + row * (path_h + row_gap)
        canvas.create_rectangle(x, ny, x + path_w, ny + path_h, fill=fill, outline=outline, width=2)
        canvas.create_rectangle(x, ny, x + path_w, ny + 16, fill=fill, outline=outline, width=1)
        canvas.create_text(x + 6, ny + 1, anchor="nw", text="Path taken", fill=text, font=("Segoe UI", 8, "bold"))
        canvas.create_text(x + 6, ny + 18, anchor="nw", text=_short(line, 28), fill=text, font=("Segoe UI", 9), width=path_w - 12)
        nodes.append((x, ny))
        if col > 0:
            prev_x, prev_y = nodes[-2]
            _arrow(canvas, prev_x + path_w, prev_y + path_h // 2, x, ny + path_h // 2, accent)
        elif index > 0:
            prev_x, prev_y = nodes[-2]
            mid = prev_y + path_h + row_gap // 2
            canvas.create_line(prev_x + path_w // 2, prev_y + path_h, prev_x + path_w // 2, mid, fill=accent, width=2)
            canvas.create_line(prev_x + path_w // 2, mid, x + path_w // 2, mid, fill=accent, width=2)
            _arrow(canvas, x + path_w // 2, mid, x + path_w // 2, ny, accent)
    if path:
        y = y + ((len(path) - 1) // columns) * (path_h + row_gap) + path_h + GAP_Y
    for older in tasks:
        if older.get("expanded"):
            continue
        label = _short(str(older.get("current_step") or older.get("taskId") or "Task"), 48)
        _box(
            canvas,
            ORIGIN_X,
            y,
            "Task",
            label,
            fill=fill,
            outline=outline,
            text=text,
            title_fill=fill,
            width=360,
        )
        y += NODE_H + 12
    box = canvas.bbox("all")
    if box:
        canvas.configure(scrollregion=(0, 0, box[2] + 24, box[3] + 24))
    return hits
