"""
SecureCallOps caller application.

Security model
──────────────
- Names are served as server-rendered PNG images instead of plain text.
- Phone numbers are never placed in HTML. Clicking "Call" hits
  GET /pb/api/call/{id}; the server decrypts the number and returns a
  302 to tel: so the digit string does not touch the DOM.
- Both name and phone are Fernet-encrypted in the database.
- Contacts are served one at a time; callers cannot enumerate the list.
- A 20-second cooldown (server-enforced) prevents rapid cycling.
- Strict CSP reduces data exfiltration risk from injected scripts.

Run with:
    uvicorn app.phonebanking.main:app --port 8001
"""

import hashlib
import io
import logging
import os
import re
import secrets as _secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont

from app.common.crypto import decrypt_text
from app.common.db import get_ops, init_pools, purge_expired_rows, put_ops
from app.common.util import fetchone_dict

logger = logging.getLogger(__name__)

PB_SESSION_COOKIE = "pb_session"
ASSIGNMENT_COOLDOWN_SECONDS = 20

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── Startup ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pools()
    purge_expired_rows()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/pb/static", StaticFiles(directory="app/phonebanking/static"), name="pb-static")
templates = Jinja2Templates(directory="app/phonebanking/templates")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _security_headers(resp: Response) -> None:
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )


def _cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    base = str(request.base_url).rstrip("/")
    # Strip scheme: a cloud ingress may terminate TLS at the edge while the
    # container sees http:// internally and the browser sends https:// origin.
    def _host(url: str) -> str:
        return url.split("://", 1)[-1].rstrip("/")
    if not (_host(origin) == _host(base) or _host(origin).startswith(_host(base) + "/")):
        raise HTTPException(403, "Forbidden")


def _require_pb_session(req: Request) -> dict:
    token = (req.cookies.get(PB_SESSION_COOKIE) or "").strip()
    if not token:
        raise HTTPException(401, "Not authenticated")

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.session_token,
                           s.volunteer_email,
                           s.display_name,
                           EXTRACT(EPOCH FROM (now() - (
                               SELECT MAX(s2.last_assigned_at)
                               FROM pb_sessions s2
                               WHERE s2.volunteer_email = s.volunteer_email
                                 AND s2.expires_at > now()
                           )))::int AS secs_since_last
                    FROM pb_sessions s
                    WHERE s.session_token = %s
                      AND s.expires_at > now()
                    """,
                    (token,),
                )
                sess = fetchone_dict(cur)
                if not sess:
                    raise HTTPException(401, "Session expired")
                return sess
    finally:
        put_ops(conn)


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_FONT_PATH = next((path for path in _FONT_CANDIDATES if os.path.exists(path)), None)


def _load_font(size: int):
    if _FONT_PATH:
        try:
            return ImageFont.truetype(_FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _partition_name(words, line_count: int):
    if line_count == 1:
        yield (" ".join(words),)
        return

    max_split = len(words) - line_count + 1
    for split_at in range(1, max_split + 1):
        head = " ".join(words[:split_at])
        for tail in _partition_name(words[split_at:], line_count - 1):
            yield (head, *tail)


def _candidate_name_layouts(name: str):
    words = name.split()
    if not words:
        yield (name or "Unknown",)
        return

    max_lines = min(len(words), 3)
    for line_count in range(1, max_lines + 1):
        yield from _partition_name(words, line_count)


def _measure_name_block(draw, lines, font, spacing: int):
    bbox = draw.multiline_textbbox(
        (0, 0),
        "\n".join(lines),
        font=font,
        spacing=spacing,
        align="center",
    )
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _pick_name_layout(draw, name: str, max_width: int, max_height: int):
    best = None
    best_score = None

    for lines in _candidate_name_layouts(name):
        low, high = 24, 420
        layout = None

        while low <= high:
            size = (low + high) // 2
            font = _load_font(size)
            spacing = max(8, size // 6)
            text_width, text_height = _measure_name_block(draw, lines, font, spacing)

            if text_width <= max_width and text_height <= max_height:
                layout = (lines, font, spacing, text_width, text_height, size)
                low = size + 1
            else:
                high = size - 1

        if layout:
            _, _, _, text_width, text_height, size = layout
            width_ratio = text_width / max_width
            height_ratio = text_height / max_height
            score = (
                min(width_ratio, height_ratio),
                width_ratio * height_ratio,
                size,
                -len(lines),
            )
            if best is None or score > best_score:
                best = layout
                best_score = score

    if best is not None:
        lines, font, spacing, _, _, _ = best
        return lines, font, spacing

    fallback = _load_font(24)
    return (name or "Unknown",), fallback, 8


def _make_name_image(name: str) -> bytes:
    """Render name as a large PNG that fills the available image area."""
    width, height = 1400, 420
    padding_x, padding_y = 24, 20

    safe_name = " ".join((name or "").split()) or "Unknown"
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    lines, font, spacing = _pick_name_layout(
        draw,
        safe_name,
        max_width=width - (padding_x * 2),
        max_height=height - (padding_y * 2),
    )

    draw.multiline_text(
        (width // 2, height // 2),
        "\n".join(lines),
        fill=(15, 15, 15),
        anchor="mm",
        font=font,
        align="center",
        spacing=spacing,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _release_expired_assignments(cur) -> None:
    """Return abandoned contacts to the available pool (lazy cleanup)."""
    cur.execute(
        """
        UPDATE pb_contacts SET status = 'available'
        WHERE contact_id IN (
            SELECT contact_id FROM pb_assignments
            WHERE active = TRUE AND expires_at < now()
        )
          AND status = 'assigned'
        """
    )
    cur.execute(
        "UPDATE pb_assignments SET active = FALSE "
        "WHERE active = TRUE AND expires_at < now()"
    )


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse("/pb/login")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "caller"}


@app.get("/pb/login", response_class=HTMLResponse)
async def login_page(request: Request):
    resp = templates.TemplateResponse(request, "login.html")
    _security_headers(resp)
    return resp


_OTP_MAX_PER_HOUR = 5
_OTP_MAX_ATTEMPTS = 3


@app.post("/pb/api/login/request")
async def api_login_request(request: Request):
    """Step 1: send OTP to the caller's email."""
    _same_origin(request)

    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email")

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pb_authorized_volunteers "
                    "WHERE lower(email) = lower(%s) "
                    "AND (expires_at IS NULL OR expires_at > now())",
                    (email,),
                )
                authorized = cur.fetchone() is not None

                if authorized:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM pb_otp_challenges
                        WHERE service = 'volunteer' AND lower(email) = %s
                          AND created_at > now() - INTERVAL '1 hour'
                        """,
                        (email,),
                    )
                    if cur.fetchone()[0] < _OTP_MAX_PER_HOUR:
                        code = f"{_secrets.randbelow(1_000_000):06d}"
                        salt = _secrets.token_hex(16)
                        code_hash = hashlib.sha256(
                            f"{code}{salt}".encode()
                        ).hexdigest()
                        ip = (
                            request.headers.get("x-forwarded-for", "")
                            or (request.client.host if request.client else "")
                        )
                        cur.execute(
                            """
                            INSERT INTO pb_otp_challenges
                                (service, email, code_hash, salt, ip_address)
                            VALUES ('volunteer', %s, %s, %s, %s)
                            """,
                            (email, code_hash, salt, ip),
                        )
                        try:
                            from app.common.email import send_otp
                            send_otp(email, code)
                        except Exception:
                            logger.error(
                                "Failed to send OTP to %s", email, exc_info=True
                            )
    finally:
        put_ops(conn)

    # Always return ok; never reveal whether the email is on the list.
    return {"ok": True}


@app.post("/pb/api/login/verify")
async def api_login_verify(request: Request):
    """Step 2: verify OTP and create session."""
    _same_origin(request)

    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    code = (body.get("code") or "").strip()
    if not email or not code:
        raise HTTPException(400, "Missing fields")

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, code_hash, salt, attempts
                    FROM pb_otp_challenges
                    WHERE service = 'volunteer' AND lower(email) = %s
                      AND used = FALSE AND expires_at > now()
                    ORDER BY created_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (email,),
                )
                row = fetchone_dict(cur)
                if not row:
                    raise HTTPException(401, "Code expired — request a new one")

                new_attempts = row["attempts"] + 1
                if new_attempts >= _OTP_MAX_ATTEMPTS:
                    cur.execute(
                        "UPDATE pb_otp_challenges SET used=TRUE, attempts=%s WHERE id=%s",
                        (new_attempts, row["id"]),
                    )
                    raise HTTPException(401, "Too many attempts — request a new code")

                expected = hashlib.sha256(
                    f"{code}{row['salt']}".encode()
                ).hexdigest()
                if expected != row["code_hash"]:
                    cur.execute(
                        "UPDATE pb_otp_challenges SET attempts=%s WHERE id=%s",
                        (new_attempts, row["id"]),
                    )
                    raise HTTPException(401, "Invalid code")

                cur.execute(
                    "UPDATE pb_otp_challenges SET used=TRUE, attempts=%s WHERE id=%s",
                    (new_attempts, row["id"]),
                )

                cur.execute(
                    "SELECT 1 FROM pb_authorized_volunteers "
                    "WHERE lower(email) = lower(%s) "
                    "AND (expires_at IS NULL OR expires_at > now())",
                    (email,),
                )
                if not cur.fetchone():
                    raise HTTPException(403, "Not authorised for calling")

                cur.execute(
                    """
                    INSERT INTO pb_sessions(volunteer_email, display_name)
                    VALUES (%s, %s)
                    RETURNING session_token
                    """,
                    (email, email),
                )
                sess = fetchone_dict(cur)
                if sess is None:
                    raise RuntimeError("INSERT RETURNING returned no row")
                session_token = str(sess["session_token"])
    finally:
        put_ops(conn)

    resp = Response(content='{"ok":true}', media_type="application/json")
    resp.set_cookie(
        PB_SESSION_COOKIE,
        session_token,
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(),
        max_age=12 * 3600,
    )
    _security_headers(resp)
    return resp


@app.post("/pb/api/logout")
async def api_logout(request: Request):
    token = (request.cookies.get(PB_SESSION_COOKIE) or "").strip()
    if token:
        conn = get_ops()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM pb_sessions WHERE session_token = %s",
                        (token,),
                    )
        finally:
            put_ops(conn)
    resp = RedirectResponse("/pb/login", status_code=303)
    resp.delete_cookie(PB_SESSION_COOKIE)
    return resp


# ── Page ──────────────────────────────────────────────────────────────────────

@app.get("/pb/call", response_class=HTMLResponse)
async def call_page(request: Request):
    sess = _require_pb_session(request)
    resp = templates.TemplateResponse(
        request,
        "call.html",
        {"volunteer_name": sess.get("display_name") or sess["volunteer_email"]},
    )
    _security_headers(resp)
    return resp


# ── Assignment API ────────────────────────────────────────────────────────────

@app.get("/pb/api/current")
async def api_current(request: Request):
    """Return the caller's current state without side effects.

    Returns one of:
      {"state": "assigned",  "assignment_id": "…"}
      {"state": "cooldown",  "wait_seconds": N}
      {"state": "idle"}
    """
    sess = _require_pb_session(request)

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                _release_expired_assignments(cur)
                cur.execute(
                    """
                    SELECT assignment_id
                    FROM pb_assignments
                    WHERE session_token = %s
                      AND active = TRUE
                      AND expires_at > now()
                    """,
                    (sess["session_token"],),
                )
                asgn = fetchone_dict(cur)
    finally:
        put_ops(conn)

    if asgn:
        return {"state": "assigned", "assignment_id": str(asgn["assignment_id"])}

    secs = sess.get("secs_since_last")
    if secs is not None and int(secs) < ASSIGNMENT_COOLDOWN_SECONDS:
        return {
            "state": "cooldown",
            "wait_seconds": ASSIGNMENT_COOLDOWN_SECONDS - int(secs),
        }

    return {"state": "idle"}


@app.get("/pb/api/next")
async def api_next(request: Request):
    """Assign the next available contact.

    Enforces a 20-second cooldown and at most one active assignment per session.
    """
    sess = _require_pb_session(request)
    session_token = sess["session_token"]
    volunteer_email = sess["volunteer_email"]

    secs = sess.get("secs_since_last")
    if secs is not None and int(secs) < ASSIGNMENT_COOLDOWN_SECONDS:
        return {
            "ok": False,
            "cooldown": True,
            "wait_seconds": ASSIGNMENT_COOLDOWN_SECONDS - int(secs),
        }

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                _release_expired_assignments(cur)

                cur.execute(
                    "SELECT assignment_id FROM pb_assignments "
                    "WHERE session_token = %s AND active = TRUE",
                    (session_token,),
                )
                existing = fetchone_dict(cur)
                if existing:
                    return {
                        "ok": True,
                        "assignment_id": str(existing["assignment_id"]),
                        "resumed": True,
                    }

                cur.execute(
                    """
                    SELECT contact_id FROM pb_contacts
                    WHERE status = 'available'
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                contact = fetchone_dict(cur)
                if not contact:
                    return {"ok": False, "exhausted": True}

                contact_id = contact["contact_id"]
                cur.execute(
                    "UPDATE pb_contacts SET status = 'assigned' WHERE contact_id = %s",
                    (contact_id,),
                )
                cur.execute(
                    """
                    INSERT INTO pb_assignments
                        (contact_id, session_token, volunteer_email, expires_at)
                    VALUES (%s, %s, %s, now() + interval '30 minutes')
                    RETURNING assignment_id
                    """,
                    (contact_id, session_token, volunteer_email),
                )
                asgn = fetchone_dict(cur)
                if asgn is None:
                    raise RuntimeError("INSERT RETURNING returned no row")

                cur.execute(
                    "UPDATE pb_sessions SET last_assigned_at = now() "
                    "WHERE session_token = %s",
                    (session_token,),
                )

                return {
                    "ok": True,
                    "assignment_id": str(asgn["assignment_id"]),
                    "resumed": False,
                }
    finally:
        put_ops(conn)


# ── Name image ────────────────────────────────────────────────────────────────

@app.get("/pb/api/name-image/{assignment_id}")
async def api_name_image(assignment_id: str, request: Request):
    """Return the contact's name as a PNG."""
    sess = _require_pb_session(request)

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.name_cipher
                    FROM pb_assignments a
                    JOIN pb_contacts c ON c.contact_id = a.contact_id
                    WHERE a.assignment_id = %s
                      AND a.session_token = %s
                      AND a.active = TRUE
                      AND a.expires_at > now()
                    """,
                    (assignment_id, sess["session_token"]),
                )
                row = fetchone_dict(cur)
    finally:
        put_ops(conn)

    if not row:
        raise HTTPException(404, "Not found")

    try:
        name = decrypt_text(row["name_cipher"])
    except Exception:
        logger.error("Decrypt failed for assignment %s", assignment_id, exc_info=True)
        raise HTTPException(500, "Error")

    img_bytes = _make_name_image(name)

    return Response(
        content=img_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
        },
    )


# ── Call redirect ─────────────────────────────────────────────────────────────

@app.get("/pb/api/call/{assignment_id}")
async def api_initiate_call(assignment_id: str, request: Request):
    """Redirect to tel:+… — the phone number never appears in HTML."""
    sess = _require_pb_session(request)

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.phone_cipher
                    FROM pb_assignments a
                    JOIN pb_contacts c ON c.contact_id = a.contact_id
                    WHERE a.assignment_id = %s
                      AND a.session_token = %s
                      AND a.active = TRUE
                      AND a.expires_at > now()
                    """,
                    (assignment_id, sess["session_token"]),
                )
                row = fetchone_dict(cur)
    finally:
        put_ops(conn)

    if not row:
        raise HTTPException(404, "Not found")

    try:
        phone = decrypt_text(row["phone_cipher"])
    except Exception:
        raise HTTPException(500, "Error")

    safe = "".join(c for c in phone if c in "0123456789+- ")
    return RedirectResponse(f"tel:{safe}", status_code=302)


# ── Submit outcome ────────────────────────────────────────────────────────────

@app.post("/pb/api/submit/{assignment_id}")
async def api_submit(assignment_id: str, request: Request):
    """Record the call outcome and close the assignment."""
    sess = _require_pb_session(request)
    _same_origin(request)

    body = await request.json()
    outcome = (body.get("outcome") or "").strip()
    if outcome not in ("answered", "not_answered", "refused"):
        raise HTTPException(400, "Invalid outcome")
    comments = (body.get("comments") or "").strip()[:1000]

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT assignment_id, contact_id
                    FROM pb_assignments
                    WHERE assignment_id = %s
                      AND session_token = %s
                      AND active = TRUE
                      AND expires_at > now()
                    """,
                    (assignment_id, sess["session_token"]),
                )
                asgn = fetchone_dict(cur)
                if not asgn:
                    raise HTTPException(404, "Assignment not found or already submitted")

                contact_id = asgn["contact_id"]

                cur.execute(
                    """
                    INSERT INTO pb_call_results
                        (assignment_id, contact_id, volunteer_email, outcome, comments)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (assignment_id, contact_id, sess["volunteer_email"],
                     outcome, comments or None),
                )
                cur.execute(
                    "UPDATE pb_assignments "
                    "SET active = FALSE, completed_at = now() "
                    "WHERE assignment_id = %s",
                    (assignment_id,),
                )
                cur.execute(
                    """
                    UPDATE pb_contacts
                    SET status = 'done',
                        call_count = call_count + 1,
                        last_outcome = %s,
                        last_called_at = now()
                    WHERE contact_id = %s
                    """,
                    (outcome, contact_id),
                )
    finally:
        put_ops(conn)

    return {"ok": True, "cooldown_seconds": ASSIGNMENT_COOLDOWN_SECONDS}
