from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app import db
from app.security import sniff_image_extension

DEFAULT_BRANDING: dict[str, Any] = {
    "name": "Vanity Hop",
    "bg": "#0b0c0e",
    "surface": "#141518",
    "ink": "#f2f2f0",
    "muted": "#8b8d93",
    "line": "#2a2b32",
    "accent": "#8ab4ff",
    "button_text": "#0b0c0e",
    "background_opacity": "0.28",
    "logo": "",
    "favicon": "",
    "background_image": "",
}

COLOR_FIELDS = ("bg", "surface", "ink", "muted", "line", "accent", "button_text")
IMAGE_FIELDS = ("logo", "favicon", "background_image")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def uploads_dir() -> Path:
    path = Path(data_dir()) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_branding() -> dict[str, Any]:
    stored = db.get_setting("branding")
    data: dict[str, Any] = {}
    if stored:
        try:
            parsed = json.loads(stored)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {}
    merged = deepcopy(DEFAULT_BRANDING)
    for key, value in data.items():
        if key in merged and value not in (None, ""):
            merged[key] = value
    if not str(merged.get("name", "")).strip():
        merged["name"] = DEFAULT_BRANDING["name"]
    return merged


def save_branding(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_branding()
    current.update(updates)
    db.set_setting("branding", json.dumps(current))
    return current


def reset_branding() -> None:
    db.set_setting("branding", json.dumps(DEFAULT_BRANDING))
    for path in uploads_dir().glob("*"):
        if path.is_file():
            path.unlink()


def parse_colors(form: dict[str, str]) -> dict[str, str]:
    colors = {}
    labels = {
        "bg": "Background",
        "surface": "Surface",
        "ink": "Text",
        "muted": "Muted text",
        "line": "Borders",
        "accent": "Accent",
        "button_text": "Button text",
    }
    for field in COLOR_FIELDS:
        colors[field] = normalize_hex_color(form.get(field, ""), labels[field])
    return colors


def css_variables(branding: dict[str, Any]) -> str:
    opacity = branding.get("background_opacity") or "0.28"
    try:
        value = min(1.0, max(0.0, float(opacity)))
    except (TypeError, ValueError):
        value = 0.28
    lines = [
        f"--bg: {branding['bg']};",
        f"--surface: {branding['surface']};",
        f"--ink: {branding['ink']};",
        f"--muted: {branding['muted']};",
        f"--line: {branding['line']};",
        f"--accent: {branding['accent']};",
        f"--button-text: {branding['button_text']};",
        f"--bg-image-opacity: {value};",
    ]
    image = branding.get("background_image") or ""
    if image:
        lines.append(f"--bg-image: url('{image}');")
    return "\n      ".join(lines)


def store_upload(field: str, data: bytes) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Images must be 5 MB or smaller.")
    ext = sniff_image_extension(data)
    name = f"{field}{ext}"
    path = uploads_dir() / name
    for old in uploads_dir().glob(f"{field}.*"):
        if old != path:
            old.unlink()
    path.write_bytes(data)
    return f"/media/{name}"
