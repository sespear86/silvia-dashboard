"""Screenshot capture: raster the shipped graphic to a real PNG file."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from layout import content_extent, layout_tree, tree_root
from theme import DEFAULT_SCHEME, paint_tokens, select


def _hex_rgb(value: str) -> tuple[int, int, int]:
    text = (value or "#888888").lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) < 6:
        text = (text + "000000")[:6]
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def render_graphic_png(graphic: dict[str, Any], path: str | Path, *, max_side: int = 1600) -> dict[str, Any]:
    """Write a real PNG of the node-and-edge layout (not a stub)."""
    from PIL import Image, ImageDraw, ImageFont

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ext = content_extent(graphic)
    cw = max(1, ext["content_width"])
    ch = max(1, ext["content_height"])
    scale = min(1.0, float(max_side) / float(max(cw, ch)))
    iw = max(1, int(cw * scale))
    ih = max(1, int(ch * scale))
    tokens = paint_tokens(graphic.get("scheme") or DEFAULT_SCHEME)
    bg = str(graphic.get("background") or tokens["background"])
    img = Image.new("RGB", (iw, ih), _hex_rgb(bg))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    def xy(x: float, y: float) -> tuple[int, int]:
        return int(x * scale), int(y * scale)

    edge_fill = _hex_rgb(str(graphic.get("edge") or graphic.get("accent") or tokens["fallback_stroke"]))
    for edge in graphic.get("edges") or []:
        path = edge.get("path") or []
        if len(path) >= 4:
            p0 = xy(path[0]["x"], path[0]["y"])
            p1 = xy(path[1]["x"], path[1]["y"])
            p2 = xy(path[2]["x"], path[2]["y"])
            p3 = xy(path[3]["x"], path[3]["y"])
            pts = []
            steps = 20
            for i in range(steps + 1):
                t = i / steps
                u = 1.0 - t
                pts.append(
                    (
                        u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                        u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
                    )
                )
            draw.line(pts, fill=edge_fill, width=max(1, int(2 * scale)))
        else:
            draw.line([xy(edge["x1"], edge["y1"]), xy(edge["x2"], edge["y2"])], fill=edge_fill, width=max(1, int(2 * scale)))
    for box in graphic.get("nodes") or []:
        x, y = xy(box["x"], box["y"])
        w, h = max(4, int(box["w"] * scale)), max(4, int(box["h"] * scale))
        body = _hex_rgb(str(box.get("interior_body") or tokens["interior_body"]))
        header = _hex_rgb(str(box.get("title_fill") or tokens["interior_header"]))
        inset = _hex_rgb(str(box.get("interior_inset") or tokens["interior_inset"]))
        border = _hex_rgb(str(box.get("border") or tokens["outline"]))
        title = _hex_rgb(str(box.get("title_text") or tokens["title_text"]))
        tstroke = _hex_rgb(str(box.get("title_stroke") or tokens["title_stroke"]))
        radius = max(2, int(int(box.get("radius") or graphic.get("radius") or 12) * scale))
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=body, outline=None)
        hh = max(4, int(20 * scale))
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=255)
        band = Image.new("L", img.size, 0)
        ImageDraw.Draw(band).rectangle([x, y, x + w, y + hh], fill=255)
        from PIL import ImageChops

        clip = ImageChops.multiply(mask, band)
        header_layer = Image.new("RGB", img.size, header)
        img.paste(header_layer, (0, 0), clip)
        draw = ImageDraw.Draw(img)
        label = str(box.get("name") or box.get("id") or "")[:22]
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
            draw.text((x + 6 + dx, y + 2 + dy), label, fill=tstroke, font=font)
        draw.text((x + 6, y + 2), label, fill=title, font=font)
        ix0, iy0 = x + int(6 * scale), y + hh + int(3 * scale)
        ix1, iy1 = x + w - int(6 * scale), y + h - int(4 * scale)
        if ix1 > ix0 and iy1 > iy0:
            draw.rectangle([ix0, iy0, ix1, iy1], fill=inset)
            feed = list(box.get("feed") or [])
            if len(feed) >= 2:
                fw, fh = max(1, ix1 - ix0), max(1, iy1 - iy0)
                pts = []
                for i, val in enumerate(feed):
                    pts.append(
                        (
                            ix0 + int(i * (fw - 1) / (len(feed) - 1)),
                            iy1 - int(float(val) * (fh - 2)) - 1,
                        )
                    )
                draw.line(pts, fill=_hex_rgb(tokens["accent"]), width=max(1, int(scale)))
        draw.rounded_rectangle(
            [x, y, x + w, y + h],
            radius=radius,
            outline=border,
            width=max(3, int(3 * scale) or 3),
        )
    img.save(dest, format="PNG")
    size = dest.stat().st_size
    header = dest.read_bytes()[:8]
    return {
        "ok": True,
        "path": str(dest),
        "bytes": size,
        "width": iw,
        "height": ih,
        "png": header[:4] == b"\x89PNG",
        "content_width": cw,
        "content_height": ch,
        "scale": scale,
    }


def sample_box_corners(path: str | Path, graphic: dict[str, Any], box: dict[str, Any]) -> dict[str, Any]:
    """Sample PNG pixels on the rounded outer arc; they should match the box border."""
    import math

    from PIL import Image

    img = Image.open(path).convert("RGB")
    scale = img.width / max(1, int(graphic.get("content_width") or img.width))
    r = max(2, int(int(box.get("radius") or graphic.get("radius") or 12) * scale))
    x = int(int(box["x"]) * scale)
    y = int(int(box["y"]) * scale)
    w = max(4, int(int(box["w"]) * scale))
    pixels = []
    for name, cx, cy, ang in (
        ("tl", x + r, y + r, math.radians(225)),
        ("tr", x + w - r, y + r, math.radians(-45)),
    ):
        px = int(round(cx + r * math.cos(ang)))
        py = int(round(cy + r * math.sin(ang)))
        px = min(max(0, px), img.width - 1)
        py = min(max(0, py), img.height - 1)
        rgb = img.getpixel((px, py))
        pixels.append({"corner": name, "x": px, "y": py, "rgb": rgb})
    return {"scale": scale, "samples": pixels}


def render_systems_png(systems: list[dict[str, Any]], path: str | Path) -> dict[str, Any]:
    """Draw each inventory display name and its presence word. Returns those names."""
    from PIL import Image, ImageDraw, ImageFont

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows = [row for row in systems if isinstance(row, dict)]
    labels = [str(row.get("display_name") or row.get("name") or "") for row in rows]
    line_h = 22
    width = 980
    height = max(48, 16 + line_h * max(1, len(rows)))
    img = Image.new("RGB", (width, height), (8, 12, 16))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    y = 8
    for row, label in zip(rows, labels):
        presence = row.get("presence")
        word = "absent" if presence == "absent" else "present"
        draw.text((12, y), f"{label}  {word}", fill=(120, 230, 230), font=font)
        y += line_h
    img.save(dest, format="PNG")
    size = dest.stat().st_size
    header = dest.read_bytes()[:8]
    return {
        "ok": True,
        "path": str(dest),
        "bytes": size,
        "width": width,
        "height": height,
        "png": header[:4] == b"\x89PNG",
        "labels": labels,
        "graphic": False,
    }


def capture_world(world: dict[str, Any], path: str | Path) -> dict[str, Any]:
    giant = (world.get("diagrams") or {}).get("giant") or {}
    scheme = str(world.get("scheme") or DEFAULT_SCHEME)
    collapsed = list((world.get("diagrams") or {}).get("collapsed") or world.get("collapsed") or [])
    graphic = layout_tree(tree_root(giant), scheme=scheme, collapsed=collapsed)
    result = render_graphic_png(graphic, path)
    result["layout_id"] = world.get("layout_id") or select().get("layout_id")
    result["scheme"] = scheme
    result["graphic"] = True
    result["nodes"] = len(graphic.get("nodes") or [])
    result["edges"] = len(graphic.get("edges") or [])
    return result
