from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.util import compose_slug, data_dir, generate_slug, normalize_prefix, normalize_slug

_lock = threading.Lock()
_DB_PATH = Path(data_dir()) / "vanity-hop.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                destination TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_links_created ON links(created_at DESC);
            """
        )


def get_setting(key: str) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def delete_setting(key: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def has_password() -> bool:
    return bool(get_setting("password_hash"))


def onboarding_complete() -> bool:
    return get_setting("onboarding_complete") == "1"


def is_configured() -> bool:
    return bool(get_setting("password_hash") and onboarding_complete() and get_setting("public_origin"))


def slug_prefix() -> str:
    if get_setting("slug_prefix_enabled") != "1":
        return ""
    return get_setting("slug_prefix") or ""


def set_slug_prefix(enabled: bool, prefix: str) -> None:
    clean = normalize_prefix(prefix)
    if enabled and not clean:
        raise ValueError("Enter a prefix, or turn the prefix off.")
    set_setting("slug_prefix_enabled", "1" if enabled else "0")
    set_setting("slug_prefix", clean)


def list_links() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, slug, destination, created_at, updated_at FROM links ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_link_by_slug(slug: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, slug, destination, created_at, updated_at FROM links WHERE slug = ?",
            (slug,),
        ).fetchone()
        return dict(row) if row else None


def get_link(link_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, slug, destination, created_at, updated_at FROM links WHERE id = ?",
            (link_id,),
        ).fetchone()
        return dict(row) if row else None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unique_random_slug(conn: sqlite3.Connection, prefix: str) -> str:
    while True:
        candidate = compose_slug(prefix, generate_slug())
        if not conn.execute("SELECT 1 FROM links WHERE slug = ?", (candidate,)).fetchone():
            return candidate


def create_link(destination: str, slug: str | None = None) -> dict[str, Any]:
    stamp = _now()
    prefix = slug_prefix()
    with get_db() as conn:
        if slug:
            clean = compose_slug(prefix, slug)
            if conn.execute("SELECT 1 FROM links WHERE slug = ?", (clean,)).fetchone():
                raise ValueError("That slug is already taken.")
        else:
            clean = _unique_random_slug(conn, prefix)
        cur = conn.execute(
            "INSERT INTO links(slug, destination, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (clean, destination, stamp, stamp),
        )
        return {
            "id": cur.lastrowid,
            "slug": clean,
            "destination": destination,
            "created_at": stamp,
            "updated_at": stamp,
        }


def update_link(link_id: int, destination: str, slug: str) -> dict[str, Any]:
    clean = normalize_slug(slug)
    stamp = _now()
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM links WHERE id = ?", (link_id,)).fetchone()
        if not existing:
            raise ValueError("Link not found.")
        taken = conn.execute(
            "SELECT id FROM links WHERE slug = ? AND id != ?",
            (clean, link_id),
        ).fetchone()
        if taken:
            raise ValueError("That slug is already taken.")
        conn.execute(
            "UPDATE links SET slug = ?, destination = ?, updated_at = ? WHERE id = ?",
            (clean, destination, stamp, link_id),
        )
    link = get_link(link_id)
    if not link:
        raise ValueError("Link not found.")
    return link


def delete_link(link_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM links WHERE id = ?", (link_id,))


def delete_links(ids: list[int]) -> int:
    clean = [int(item) for item in ids if str(item).isdigit() or isinstance(item, int)]
    if not clean:
        return 0
    placeholders = ",".join("?" * len(clean))
    with get_db() as conn:
        cur = conn.execute(f"DELETE FROM links WHERE id IN ({placeholders})", clean)
        return cur.rowcount


def delete_older_than(*, amount: int, unit: str) -> int:
    if amount < 1:
        raise ValueError("Choose a period of at least 1.")
    deltas = {
        "hours": timedelta(hours=amount),
        "days": timedelta(days=amount),
        "weeks": timedelta(weeks=amount),
        "months": timedelta(days=30 * amount),
        "years": timedelta(days=365 * amount),
    }
    delta = deltas.get(unit)
    if not delta:
        raise ValueError("Choose hours, days, weeks, months, or years.")
    cutoff = (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_db() as conn:
        cur = conn.execute("DELETE FROM links WHERE created_at < ?", (cutoff,))
        return cur.rowcount
