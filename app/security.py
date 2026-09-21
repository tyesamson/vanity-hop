from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.responses import Response

from app import db

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 8
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

_login_lock = threading.Lock()
_login_failures: dict[str, list[float]] = defaultdict(list)


def ensure_csrf(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def password_stamp() -> str:
    stamp = db.get_setting("password_stamp")
    if not stamp:
        stamp = secrets.token_hex(16)
        db.set_setting("password_stamp", stamp)
    return stamp


def rotate_password_stamp() -> str:
    stamp = secrets.token_hex(16)
    db.set_setting("password_stamp", stamp)
    return stamp


def establish_session(request: Request) -> None:
    request.session["auth"] = True
    request.session["pw"] = password_stamp()
    ensure_csrf(request)


def _tokens_match(got: str, expected: str) -> bool:
    if not got or not expected or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def session_is_authenticated(request: Request) -> bool:
    if not request.session.get("auth"):
        return False
    return _tokens_match(str(request.session.get("pw") or ""), password_stamp())


def client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def login_is_blocked(ip: str) -> bool:
    now = time.monotonic()
    with _login_lock:
        recent = [stamp for stamp in _login_failures[ip] if now - stamp < LOGIN_WINDOW_SECONDS]
        _login_failures[ip] = recent
        return len(recent) >= LOGIN_MAX_FAILURES


def login_fail(ip: str) -> None:
    with _login_lock:
        _login_failures[ip].append(time.monotonic())


def login_ok(ip: str) -> None:
    with _login_lock:
        _login_failures.pop(ip, None)


def sniff_image_extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith((b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")):
        return ".ico"
    raise ValueError("Use PNG, JPG, WEBP, GIF, or ICO.")


def apply_security_headers(response: Response, *, https: bool) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    if https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


async def _read_body(receive) -> bytes:
    chunks: list[bytes] = []
    more = True
    while more:
        message = await receive()
        chunks.append(message.get("body", b""))
        more = message.get("more_body", False)
    return b"".join(chunks)


def _replay(body: bytes):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


class CsrfMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in MUTATING:
            await self.app(scope, receive, send)
            return

        body = await _read_body(receive)
        request = Request(scope, _replay(body))
        form = await request.form()
        try:
            token = str(request.session.get("csrf_token") or "")
            got = str(form.get("csrf_token") or "")
            if not _tokens_match(got, token):
                response = PlainTextResponse("Invalid CSRF token.", status_code=403)
                await response(scope, _replay(body), send)
                return
        finally:
            await form.close()

        await self.app(scope, _replay(body), send)


def forwarded_allow_ips() -> str:
    raw = os.environ.get("FORWARDED_ALLOW_IPS")
    if raw is None or raw.strip() == "":
        return "127.0.0.1"
    return raw.strip()
