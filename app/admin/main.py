"""
SecureCallOps admin application.

Completely separate from the caller app - different service, different port,
different session cookie.

Admins are managed via the pb_admin_users table.  The first admin must be
seeded directly in the database:
    INSERT INTO pb_admin_users(email) VALUES ('you@example.com');

Run with:
    uvicorn app.admin.main:app --port 8002
"""

import csv
import hashlib
import io
import logging
import os
import re
import secrets as _secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.common.crypto import decrypt_text, encrypt_text
from app.common.db import get_ops, init_pools, purge_expired_rows, put_ops
from app.common.util import fetchall_dict, fetchone_dict

logger = logging.getLogger(__name__)

ADMIN_SESSION_COOKIE = "pb_admin_session"
UPLOAD_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_UPLOAD_ROWS = 10_000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── Startup ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pools()
    purge_expired_rows()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory="app/admin/static"), name="admin-static")
templates = Jinja2Templates(directory="app/admin/templates")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _security_headers(resp: Response) -> None:
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self'; "
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


def _require_admin(req: Request) -> dict:
    token = (req.cookies.get(ADMIN_SESSION_COOKIE) or "").strip()
    if not token:
        raise HTTPException(401, "Not authenticated")

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_token, admin_email
                    FROM pb_admin_sessions
                    WHERE session_token = %s
                      AND expires_at > now()
                    """,
                    (token,),
                )
                sess = fetchone_dict(cur)
                if not sess:
                    raise HTTPException(401, "Session expired")
                return sess
    finally:
        put_ops(conn)


def _safe_csv(v: object) -> str:
    """Prefix cells that could be formula-injected."""
    s = str(v) if v is not None else ""
    return ("'" + s) if s and s[0] in "=+@-\t" else s


def _parse_volunteer_expiry(raw: object) -> datetime | None:
    """Parse optional caller expiry input into an aware UTC datetime."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise HTTPException(400, "Invalid expiry date")

    value = raw.strip()
    if not value:
        return None

    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            expires_on = date.fromisoformat(value)
            return datetime.combine(expires_on, time.max, timezone.utc)

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid expiry date")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ── Auth pages ────────────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse("/login")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "admin"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    try:
        _require_admin(request)
        return RedirectResponse("/dashboard")
    except HTTPException:
        pass
    resp = templates.TemplateResponse(request, "login.html")
    _security_headers(resp)
    return resp


_OTP_MAX_PER_HOUR = 5
_OTP_MAX_ATTEMPTS = 3


@app.post("/api/login/request")
async def api_login_request(request: Request):
    """Step 1: send OTP to the admin's email."""
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
                    "SELECT 1 FROM pb_admin_users WHERE lower(email) = lower(%s)",
                    (email,),
                )
                authorized = cur.fetchone() is not None

                if authorized:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM pb_otp_challenges
                        WHERE service = 'admin' AND lower(email) = %s
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
                            VALUES ('admin', %s, %s, %s, %s)
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

    return {"ok": True}


@app.post("/api/login/verify")
async def api_login_verify(request: Request):
    """Step 2: verify OTP and create admin session."""
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
                    WHERE service = 'admin' AND lower(email) = %s
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
                    "SELECT 1 FROM pb_admin_users WHERE lower(email) = lower(%s)",
                    (email,),
                )
                if not cur.fetchone():
                    raise HTTPException(403, "Not an authorised admin")

                cur.execute(
                    """
                    INSERT INTO pb_admin_sessions(admin_email)
                    VALUES (%s)
                    RETURNING session_token
                    """,
                    (email,),
                )
                sess = fetchone_dict(cur)
                if sess is None:
                    raise RuntimeError("INSERT RETURNING returned no row")
                session_token = str(sess["session_token"])
    finally:
        put_ops(conn)

    resp = Response(content='{"ok":true}', media_type="application/json")
    resp.set_cookie(
        ADMIN_SESSION_COOKIE,
        session_token,
        httponly=True,
        samesite="strict",
        secure=_cookie_secure(),
        max_age=12 * 3600,
    )
    _security_headers(resp)
    return resp


@app.post("/api/logout")
async def api_logout(request: Request):
    token = (request.cookies.get(ADMIN_SESSION_COOKIE) or "").strip()
    if token:
        conn = get_ops()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM pb_admin_sessions WHERE session_token = %s",
                        (token,),
                    )
        finally:
            put_ops(conn)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(ADMIN_SESSION_COOKIE)
    return resp


# ── Dashboard page ────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    try:
        admin = _require_admin(request)
    except HTTPException:
        return RedirectResponse("/login")
    resp = templates.TemplateResponse(request, "admin.html", {"admin_email": admin["admin_email"]})
    _security_headers(resp)
    return resp


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats(request: Request):
    _require_admin(request)

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'available') AS available,
                        COUNT(*) FILTER (WHERE status = 'assigned')  AS assigned,
                        COUNT(*) FILTER (WHERE status = 'done')      AS done,
                        COUNT(*)                                      AS total
                    FROM pb_contacts
                    """
                )
                contacts = fetchone_dict(cur)

                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE outcome = 'answered')     AS answered,
                        COUNT(*) FILTER (WHERE outcome = 'not_answered') AS not_answered,
                        COUNT(*) FILTER (WHERE outcome = 'refused')      AS refused,
                        COUNT(*)                                          AS total_calls
                    FROM pb_call_results
                    """
                )
                outcomes = fetchone_dict(cur)
    finally:
        put_ops(conn)

    return {**(contacts or {}), **(outcomes or {})}


# ── Results (paginated) ───────────────────────────────────────────────────────

@app.get("/api/results")
async def api_results(request: Request, offset: int = 0, limit: int = 50):
    _require_admin(request)
    limit = min(limit, 200)

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.volunteer_email, r.outcome, r.comments, r.submitted_at,
                           c.name_cipher, c.phone_cipher
                    FROM pb_call_results r
                    JOIN pb_contacts c ON c.contact_id = r.contact_id
                    ORDER BY r.submitted_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
                rows = fetchall_dict(cur)

                cur.execute("SELECT COUNT(*) AS n FROM pb_call_results")
                total = (fetchone_dict(cur) or {}).get("n", 0)
    finally:
        put_ops(conn)

    result_rows = []
    for r in rows:
        try:
            name = decrypt_text(r["name_cipher"])
        except Exception:
            name = "—"
        try:
            phone = decrypt_text(r["phone_cipher"])
        except Exception:
            phone = "—"
        result_rows.append({
            "volunteer_email": r["volunteer_email"],
            "outcome": r["outcome"],
            "comments": r["comments"],
            "submitted_at": r["submitted_at"].isoformat() if r.get("submitted_at") else None,
            "name": name,
            "phone": phone,
        })

    return {"total": total, "offset": offset, "rows": result_rows}


# ── Contacts list ─────────────────────────────────────────────────────────────

@app.get("/api/contacts")
async def api_contacts(request: Request, offset: int = 0, limit: int = 100):
    _require_admin(request)
    limit = min(limit, 500)

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT contact_id, name_cipher, phone_cipher, status,
                           call_count, last_outcome, last_called_at
                    FROM pb_contacts
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
                rows = fetchall_dict(cur)
                cur.execute("SELECT COUNT(*) AS n FROM pb_contacts")
                total = (fetchone_dict(cur) or {}).get("n", 0)
    finally:
        put_ops(conn)

    result = []
    for r in rows:
        try:
            name = decrypt_text(r["name_cipher"])
        except Exception:
            name = "—"
        try:
            phone = decrypt_text(r["phone_cipher"])
        except Exception:
            phone = "—"
        result.append({
            "contact_id": str(r["contact_id"]),
            "name": name,
            "phone": phone,
            "status": r["status"],
            "call_count": r["call_count"],
            "last_outcome": r["last_outcome"],
            "last_called_at": r["last_called_at"].isoformat() if r.get("last_called_at") else None,
        })

    return {"total": total, "offset": offset, "contacts": result}


# ── Export CSV ────────────────────────────────────────────────────────────────

_EXPORT_CHUNK = 200
_EXPORT_QUERY_COLUMNS = [
    "volunteer_email",
    "outcome",
    "comments",
    "submitted_at",
    "name_cipher",
    "phone_cipher",
]


@app.get("/api/results/export.csv")
async def export_results(request: Request):
    _require_admin(request)

    def generate():
        conn = get_ops()
        try:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["name", "phone", "caller_email", "outcome", "comments", "submitted_at"])
            yield buf.getvalue().encode("utf-8-sig")

            # Named cursor = server-side cursor; rows are fetched in _EXPORT_CHUNK batches
            # rather than all at once, keeping memory flat regardless of result set size.
            with conn.cursor("pb_export") as cur:
                cur.itersize = _EXPORT_CHUNK
                cur.execute(
                    """
                    SELECT r.volunteer_email, r.outcome, r.comments, r.submitted_at,
                           c.name_cipher, c.phone_cipher
                    FROM pb_call_results r
                    JOIN pb_contacts c ON c.contact_id = r.contact_id
                    ORDER BY r.submitted_at DESC
                    LIMIT 100000
                    """
                )
                buf = io.StringIO()
                w = csv.writer(buf)
                for i, raw_row in enumerate(cur):
                    r = dict(zip(_EXPORT_QUERY_COLUMNS, raw_row))
                    try:
                        name = decrypt_text(r["name_cipher"])
                    except Exception:
                        name = "—"
                    try:
                        phone = decrypt_text(r["phone_cipher"])
                    except Exception:
                        phone = "—"
                    w.writerow([
                        _safe_csv(name),
                        _safe_csv(phone),
                        _safe_csv(r.get("volunteer_email")),
                        _safe_csv(r.get("outcome")),
                        _safe_csv(r.get("comments")),
                        _safe_csv(r.get("submitted_at")),
                    ])
                    if (i + 1) % _EXPORT_CHUNK == 0:
                        yield buf.getvalue().encode("utf-8")
                        buf = io.StringIO()
                        w = csv.writer(buf)
                tail = buf.getvalue()
                if tail:
                    yield tail.encode("utf-8")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            put_ops(conn)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pb_results.csv"},
    )


# ── Upload contacts ───────────────────────────────────────────────────────────

@app.post("/api/upload")
async def api_upload(request: Request):
    """Upload a CSV with columns 'name' and 'phone'.  Both are encrypted immediately."""
    _require_admin(request)
    _same_origin(request)

    form = await request.form()
    upload = form.get("file")
    if not upload:
        raise HTTPException(400, "No file uploaded")

    raw = await upload.read(UPLOAD_MAX_BYTES + 1)
    if len(raw) > UPLOAD_MAX_BYTES:
        raise HTTPException(413, "File too large (max 5 MB)")

    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(text.splitlines())

    inserted = 0
    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                for row in reader:
                    name = (row.get("name") or "").strip()
                    phone = (row.get("phone") or "").strip()
                    if not name or not phone:
                        continue
                    if inserted >= MAX_UPLOAD_ROWS:
                        raise HTTPException(
                            400,
                            f"CSV exceeds the {MAX_UPLOAD_ROWS:,}-row limit — split it into smaller files",
                        )
                    cur.execute(
                        "INSERT INTO pb_contacts(name_cipher, phone_cipher) "
                        "VALUES (%s, %s)",
                        (encrypt_text(name), encrypt_text(phone)),
                    )
                    inserted += 1
    finally:
        put_ops(conn)

    return {"ok": True, "inserted": inserted}


# ── Caller management ─────────────────────────────────────────────────────────

@app.get("/api/volunteers")
async def api_list_volunteers(request: Request):
    _require_admin(request)

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT email, added_at, added_by, expires_at "
                    "FROM pb_authorized_volunteers ORDER BY added_at DESC"
                )
                rows = fetchall_dict(cur)
    finally:
        put_ops(conn)

    return {
        "volunteers": [
            {
                **r,
                "added_at": r["added_at"].isoformat() if r.get("added_at") else None,
                "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
            }
            for r in rows
        ]
    }


@app.post("/api/volunteers")
async def api_add_volunteer(request: Request):
    admin = _require_admin(request)
    _same_origin(request)

    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")
    expires_at = _parse_volunteer_expiry(body.get("expires_at"))

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pb_authorized_volunteers(email, added_by, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO UPDATE
                        SET added_by = EXCLUDED.added_by,
                            expires_at = EXCLUDED.expires_at
                    """,
                    (email, admin["admin_email"], expires_at),
                )
    finally:
        put_ops(conn)

    return {"ok": True}


@app.delete("/api/volunteers/{email}")
async def api_remove_volunteer(email: str, request: Request):
    _require_admin(request)
    _same_origin(request)

    conn = get_ops()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM pb_authorized_volunteers "
                    "WHERE lower(email) = lower(%s)",
                    (email,),
                )
    finally:
        put_ops(conn)

    return {"ok": True}


