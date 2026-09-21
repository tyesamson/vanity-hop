from __future__ import annotations

import os
import re
import secrets
from urllib.parse import urlparse

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,78}[a-z0-9])?$")
PREFIX_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SLUG_ALPHABET = "abcdefghijkmnopqrstuvwxyz23456789"
RANDOM_SLUG_LENGTH = 4
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
RESERVED_SLUGS = {
    "admin",
    "api",
    "assets",
    "favicon.ico",
    "favicon.svg",
    "health",
    "login",
    "logout",
    "media",
    "robots.txt",
    "settings",
    "setup",
    "static",
}


def strip_origin_input(value: str) -> str:
    raw = value.strip()
    raw = re.sub(r"^https?://", "", raw, flags=re.I)
    return raw.split("/")[0].strip()


def normalize_origin(value: str) -> str:
    host = strip_origin_input(value)
    if not host:
        raise ValueError("Enter a domain.")
    scheme = "http" if host.lower().startswith(("localhost", "127.0.0.1")) else "https"
    parsed = urlparse(f"{scheme}://{host}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a domain like links.example.com")
    if parsed.username or parsed.password:
        raise ValueError("Enter a domain like links.example.com")
    return f"{parsed.scheme}://{parsed.netloc.lower()}"


def origin_host(origin: str) -> str:
    return urlparse(origin).netloc


def normalize_destination(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("Paste a URL to shorten.")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Destination must be an http or https URL.")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed.")
    return raw


def normalize_slug(value: str) -> str:
    slug = value.strip().lower()
    if not slug:
        raise ValueError("Slug cannot be empty.")
    if slug in RESERVED_SLUGS or not SLUG_RE.match(slug):
        raise ValueError("Use letters, numbers, hyphens, or underscores.")
    return slug


def normalize_prefix(value: str) -> str:
    raw = value.strip().lower()
    if not raw:
        return ""
    if not PREFIX_RE.match(raw):
        raise ValueError("Prefix must start with a letter or number, then letters, numbers, hyphens, or underscores.")
    return raw


def generate_slug(length: int = RANDOM_SLUG_LENGTH) -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(length))


def compose_slug(prefix: str, suffix: str) -> str:
    suffix = suffix.strip().lower()
    if prefix and suffix.startswith(prefix):
        return normalize_slug(suffix)
    return normalize_slug(f"{prefix}{suffix}")


def normalize_hex_color(value: str, field: str) -> str:
    raw = value.strip()
    if not HEX_COLOR_RE.match(raw):
        raise ValueError(f"{field} must be a hex colour like #0b0c0e")
    if len(raw) == 4:
        raw = "#" + "".join(ch * 2 for ch in raw[1:])
    return raw.lower()


def data_dir() -> str:
    path = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
    path = os.path.abspath(path)
    os.makedirs(path, exist_ok=True)
    return path
