from __future__ import annotations

import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import branding, db
from app.auth import hash_password, new_session_secret, verify_password
from app.security import (
    CsrfMiddleware,
    apply_security_headers,
    client_ip,
    ensure_csrf,
    establish_session,
    login_fail,
    login_is_blocked,
    login_ok,
    rotate_password_stamp,
    session_is_authenticated,
)
from app.util import (
    RESERVED_SLUGS,
    data_dir,
    normalize_destination,
    normalize_origin,
    origin_host,
    strip_origin_input,
)

BASE_DIR = Path(__file__).resolve().parent
SETUP_STEPS = 4
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _format_when(value: str) -> str:
    try:
        stamp = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        return stamp.strftime("%d %b %Y %H:%M")
    except ValueError:
        return value


templates.env.filters["when"] = _format_when


def _load_session_secret() -> str:
    env = os.environ.get("SESSION_SECRET", "").strip()
    if env:
        return env
    path = Path(data_dir()) / ".session_secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = new_session_secret()
    path.write_text(secret, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def _seed_install() -> None:
    env_origin = os.environ.get("PUBLIC_ORIGIN", "").strip()
    env_password = os.environ.get("ADMIN_PASSWORD", "")
    if db.get_setting("password_is_default") == "1":
        db.delete_setting("password_hash")
        db.delete_setting("password_is_default")
    if env_password and not db.has_password():
        db.set_setting("password_hash", hash_password(env_password))
        db.delete_setting("password_is_default")
    if env_origin and not db.get_setting("public_origin"):
        try:
            db.set_setting("public_origin", normalize_origin(env_origin))
        except ValueError:
            pass
    if env_password and env_origin and db.get_setting("onboarding_complete") is None:
        db.set_setting("onboarding_complete", "1")
        db.set_setting("dns_ready", "1")
    if db.get_setting("slug_prefix_enabled") is None:
        db.set_setting("slug_prefix_enabled", "0")
        db.set_setting("slug_prefix", "")


def _ensure_install() -> None:
    db.init_db()
    _seed_install()


def _https_only() -> bool:
    flag = os.environ.get("HTTPS_ONLY", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    if flag in {"0", "false", "no"}:
        return False
    return os.environ.get("PUBLIC_ORIGIN", "").strip().lower().startswith("https://")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _ensure_install()
    yield


app = FastAPI(title="Vanity Hop", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.add_middleware(CsrfMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=_load_session_secret(),
    session_cookie="vh_session",
    same_site="lax",
    https_only=_https_only(),
    max_age=60 * 60 * 24 * 30,
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    return apply_security_headers(response, https=_https_only())


def _flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def _pop_flash(request: Request) -> dict | None:
    return request.session.pop("flash", None)


def _logged_in(request: Request) -> bool:
    return session_is_authenticated(request)


def _public_origin() -> str:
    return db.get_setting("public_origin") or ""


def _setup_path() -> str | None:
    if db.onboarding_complete():
        return None
    if not db.has_password():
        return "/setup/password"
    if not _public_origin():
        return "/setup/domain"
    if db.get_setting("dns_ready") != "1":
        return "/setup/dns"
    return "/setup/using"


def _render(request: Request, name: str, **context) -> HTMLResponse:
    origin = _public_origin()
    brand = branding.load_branding()
    return templates.TemplateResponse(
        request,
        name,
        {
            "request": request,
            "flash": _pop_flash(request),
            "logged_in": _logged_in(request),
            "public_origin": origin,
            "public_host": origin_host(origin) if origin else "",
            "brand": brand,
            "brand_css": branding.css_variables(brand),
            "slug_prefix": db.slug_prefix(),
            "slug_prefix_enabled": db.get_setting("slug_prefix_enabled") == "1",
            "slug_prefix_value": db.get_setting("slug_prefix") or "",
            "onboarding_complete": db.onboarding_complete(),
            "needs_setup": not db.has_password(),
            "csrf_token": ensure_csrf(request),
            **context,
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/robots.txt")
def robots() -> Response:
    return Response(
        "User-agent: *\nDisallow: /login\nDisallow: /setup\nDisallow: /settings\n",
        media_type="text/plain",
    )


@app.get("/favicon.svg")
def favicon_svg():
    brand = branding.load_branding()
    accent = brand["accent"]
    bg = brand["bg"]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
      <rect width="32" height="32" rx="8" fill="{bg}"/>
      <path d="M8 20c4-10 12-10 16 0" fill="none" stroke="{accent}" stroke-width="2.4" stroke-linecap="round"/>
      <circle cx="22.5" cy="11" r="2" fill="{brand['ink']}"/>
    </svg>"""
    return Response(svg, media_type="image/svg+xml")


@app.get("/media/{name}")
def media(name: str):
    safe = Path(name).name
    path = branding.uploads_dir() / safe
    if not path.is_file() or path.resolve().parent != branding.uploads_dir().resolve():
        return Response("Not found.", status_code=404)
    return FileResponse(path)


def _gate(request: Request, *, allow_setup: bool = False) -> RedirectResponse | None:
    _ensure_install()
    if not db.has_password():
        return RedirectResponse("/login" if not allow_setup else "/setup/password", status_code=303)
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=303)
    setup = _setup_path()
    if setup and not allow_setup:
        return RedirectResponse(setup, status_code=303)
    return None


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    _ensure_install()
    if _logged_in(request):
        return RedirectResponse(_setup_path() or "/", status_code=303)
    return _render(request, "login.html")


@app.post("/login")
def login_post(request: Request, password: str = Form(...)):
    ip = client_ip(request)
    if login_is_blocked(ip):
        _flash(request, "Too many attempts. Try again in 15 minutes.", "error")
        return RedirectResponse("/login", status_code=303)
    stored = db.get_setting("password_hash")
    if not stored or not verify_password(password, stored):
        login_fail(ip)
        _flash(request, "That password is not right.", "error")
        return RedirectResponse("/login", status_code=303)
    login_ok(ip)
    establish_session(request)
    return RedirectResponse(_setup_path() or "/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/setup")
def setup_index(request: Request):
    _ensure_install()
    if not db.has_password():
        return RedirectResponse("/setup/password", status_code=303)
    gate = _gate(request, allow_setup=True)
    if gate:
        return gate
    return RedirectResponse(_setup_path() or "/", status_code=303)


@app.get("/setup/password", response_class=HTMLResponse)
def setup_password_get(request: Request):
    _ensure_install()
    if db.has_password():
        if not _logged_in(request):
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse(_setup_path() or "/", status_code=303)
    return _render(request, "setup_password.html", step=1, step_count=SETUP_STEPS)


@app.post("/setup/password")
def setup_password_post(
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    _ensure_install()
    if db.has_password():
        return RedirectResponse(_setup_path() or "/", status_code=303)
    if password != password_confirm:
        _flash(request, "Passwords did not match.", "error")
        return RedirectResponse("/setup/password", status_code=303)
    if len(password) < 8:
        _flash(request, "Use at least 8 characters.", "error")
        return RedirectResponse("/setup/password", status_code=303)
    db.set_setting("password_hash", hash_password(password))
    db.delete_setting("password_is_default")
    rotate_password_stamp()
    establish_session(request)
    return RedirectResponse(_setup_path() or "/", status_code=303)


@app.get("/setup/domain", response_class=HTMLResponse)
def setup_domain_get(request: Request):
    gate = _gate(request, allow_setup=True)
    if gate:
        return gate
    if not db.has_password():
        return RedirectResponse("/setup/password", status_code=303)
    if _public_origin() and db.onboarding_complete():
        return RedirectResponse("/", status_code=303)
    preset = _public_origin() or os.environ.get("PUBLIC_ORIGIN", "").strip()
    return _render(
        request,
        "setup_domain.html",
        step=2,
        step_count=SETUP_STEPS,
        preset_host=strip_origin_input(preset),
    )


@app.post("/setup/domain")
def setup_domain_post(request: Request, public_origin: str = Form(...)):
    gate = _gate(request, allow_setup=True)
    if gate:
        return gate
    try:
        origin = normalize_origin(public_origin)
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse("/setup/domain", status_code=303)
    db.set_setting("public_origin", origin)
    return RedirectResponse("/setup/dns", status_code=303)


@app.get("/setup/dns", response_class=HTMLResponse)
def setup_dns_get(request: Request):
    gate = _gate(request, allow_setup=True)
    if gate:
        return gate
    if not db.has_password():
        return RedirectResponse("/setup/password", status_code=303)
    if not _public_origin():
        return RedirectResponse("/setup/domain", status_code=303)
    host = origin_host(_public_origin())
    return _render(request, "setup_dns.html", step=3, step_count=SETUP_STEPS, lookup=None, lookup_error=None, dns_host=host)


@app.post("/setup/dns")
def setup_dns_post(request: Request, action: str = Form("continue")):
    gate = _gate(request, allow_setup=True)
    if gate:
        return gate
    origin = _public_origin()
    if not origin:
        return RedirectResponse("/setup/domain", status_code=303)
    host = origin_host(origin)
    if action == "check":
        try:
            answers = socket.getaddrinfo(host, None)
            ips = sorted({item[4][0] for item in answers})
            return _render(
                request,
                "setup_dns.html",
                step=3,
                step_count=SETUP_STEPS,
                dns_host=host,
                lookup=ips,
                lookup_error=None,
            )
        except socket.gaierror:
            return _render(
                request,
                "setup_dns.html",
                step=3,
                step_count=SETUP_STEPS,
                dns_host=host,
                lookup=None,
                lookup_error="This hostname does not resolve yet. DNS can take a few minutes, sometimes longer.",
            )
    db.set_setting("dns_ready", "1")
    return RedirectResponse("/setup/using", status_code=303)


@app.get("/setup/using", response_class=HTMLResponse)
def setup_using_get(request: Request):
    gate = _gate(request, allow_setup=True)
    if gate:
        return gate
    if not db.has_password():
        return RedirectResponse("/setup/password", status_code=303)
    if not _public_origin():
        return RedirectResponse("/setup/domain", status_code=303)
    if db.get_setting("dns_ready") != "1":
        return RedirectResponse("/setup/dns", status_code=303)
    if db.onboarding_complete():
        return RedirectResponse("/", status_code=303)
    return _render(request, "setup_using.html", step=4, step_count=SETUP_STEPS)


@app.post("/setup/using")
def setup_using_post(request: Request):
    gate = _gate(request, allow_setup=True)
    if gate:
        return gate
    db.set_setting("dns_ready", "1")
    db.set_setting("onboarding_complete", "1")
    return RedirectResponse("/", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, created: str | None = None):
    gate = _gate(request)
    if gate:
        return gate
    created_link = db.get_link_by_slug(created) if created else None
    return _render(request, "home.html", links=db.list_links(), created=created_link)


@app.post("/links")
def create_link(request: Request, destination: str = Form(...), slug: str = Form("")):
    gate = _gate(request)
    if gate:
        return gate
    try:
        url = normalize_destination(destination)
        link = db.create_link(url, slug.strip() or None)
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse("/", status_code=303)
    return RedirectResponse(f"/?created={link['slug']}", status_code=303)


@app.post("/links/{link_id}/update")
def edit_link(
    request: Request,
    link_id: int,
    destination: str = Form(...),
    slug: str = Form(...),
):
    gate = _gate(request)
    if gate:
        return gate
    try:
        url = normalize_destination(destination)
        db.update_link(link_id, url, slug)
        _flash(request, "Link updated.")
    except ValueError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/", status_code=303)


@app.post("/links/{link_id}/delete")
def remove_link(request: Request, link_id: int):
    gate = _gate(request)
    if gate:
        return gate
    db.delete_link(link_id)
    _flash(request, "Link deleted.")
    return RedirectResponse("/", status_code=303)


@app.post("/links/bulk-delete")
async def bulk_delete(request: Request):
    gate = _gate(request)
    if gate:
        return gate
    form = await request.form()
    ids = [int(value) for value in form.getlist("ids") if str(value).isdigit()]
    count = db.delete_links(ids)
    if count:
        _flash(request, f"Deleted {count} {'link' if count == 1 else 'links'}.")
    else:
        _flash(request, "Select at least one link.", "error")
    return RedirectResponse("/", status_code=303)


@app.post("/links/delete-older")
def delete_older(request: Request, amount: int = Form(...), unit: str = Form(...)):
    gate = _gate(request)
    if gate:
        return gate
    try:
        count = db.delete_older_than(amount=amount, unit=unit)
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse("/", status_code=303)
    _flash(request, f"Deleted {count} {'link' if count == 1 else 'links'}.")
    return RedirectResponse("/", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request):
    gate = _gate(request)
    if gate:
        return gate
    return _render(request, "settings.html")


@app.post("/settings/domain")
def settings_domain(request: Request, public_origin: str = Form(...)):
    gate = _gate(request)
    if gate:
        return gate
    try:
        origin = normalize_origin(public_origin)
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse("/settings", status_code=303)
    db.set_setting("public_origin", origin)
    _flash(request, "Domain saved.")
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/prefix")
def settings_prefix(
    request: Request,
    slug_prefix: str = Form(""),
    slug_prefix_enabled: str | None = Form(None),
):
    gate = _gate(request)
    if gate:
        return gate
    try:
        db.set_slug_prefix(bool(slug_prefix_enabled), slug_prefix)
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse("/settings", status_code=303)
    _flash(request, "Prefix saved. Existing links are unchanged.")
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/password")
def settings_password(
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    gate = _gate(request)
    if gate:
        return gate
    if password != password_confirm:
        _flash(request, "Passwords did not match.", "error")
        return RedirectResponse("/settings", status_code=303)
    if len(password) < 8:
        _flash(request, "Use at least 8 characters.", "error")
        return RedirectResponse("/settings", status_code=303)
    db.set_setting("password_hash", hash_password(password))
    db.delete_setting("password_is_default")
    rotate_password_stamp()
    establish_session(request)
    _flash(request, "Password saved.")
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/branding")
async def settings_branding(
    request: Request,
    name: str = Form(""),
    bg: str = Form(...),
    surface: str = Form(...),
    ink: str = Form(...),
    muted: str = Form(...),
    line: str = Form(...),
    accent: str = Form(...),
    button_text: str = Form(...),
    background_opacity: str = Form("0.28"),
    logo: UploadFile | None = File(None),
    favicon: UploadFile | None = File(None),
    background_image: UploadFile | None = File(None),
    remove_logo: str | None = Form(None),
    remove_favicon: str | None = Form(None),
    remove_background: str | None = Form(None),
):
    gate = _gate(request)
    if gate:
        return gate
    try:
        updates: dict = branding.parse_colors(
            {
                "bg": bg,
                "surface": surface,
                "ink": ink,
                "muted": muted,
                "line": line,
                "accent": accent,
                "button_text": button_text,
            }
        )
        updates["name"] = name.strip() or branding.DEFAULT_BRANDING["name"]
        opacity = float(background_opacity)
        if opacity < 0 or opacity > 1:
            raise ValueError("Background image strength must be between 0 and 1.")
        updates["background_opacity"] = str(opacity)
        files = {"logo": logo, "favicon": favicon, "background_image": background_image}
        for field, upload in files.items():
            if upload and upload.filename:
                data = await upload.read()
                updates[field] = branding.store_upload(field, data)
        if remove_logo:
            updates["logo"] = ""
        if remove_favicon:
            updates["favicon"] = ""
        if remove_background:
            updates["background_image"] = ""
        branding.save_branding(updates)
    except ValueError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse("/settings", status_code=303)
    _flash(request, "Branding saved.")
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/branding/reset")
def reset_branding(request: Request):
    gate = _gate(request)
    if gate:
        return gate
    branding.reset_branding()
    _flash(request, "Branding reset to defaults.")
    return RedirectResponse("/settings", status_code=303)


@app.get("/{slug}")
def hop(slug: str):
    if slug in RESERVED_SLUGS:
        return RedirectResponse("/", status_code=303)
    link = db.get_link_by_slug(slug)
    if not link:
        return Response("This link does not exist.", status_code=404, media_type="text/plain")
    return RedirectResponse(
        link["destination"],
        status_code=302,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
