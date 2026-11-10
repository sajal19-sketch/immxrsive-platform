"""Employer inquiries (R1.18/R1.19), fix for issue #11.

Inquiries used to be saved only in the employer's own browser. They are now
stored on the server, and the page reports success only after the server
confirms it saved the inquiry.

Staff read them with GET /api/staff/inquiries and the header
    Authorization: Bearer <INQUIRY_ADMIN_TOKEN>
INQUIRY_ADMIN_TOKEN is a Render environment variable; it is never committed.
"""
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()
_cfg = {}

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
ROLE_TYPES = {'', 'Internship', 'Contract', 'Full-time'}
RATE_LIMIT = 5            # inquiries per window per sender
RATE_WINDOW = timedelta(minutes=10)


def configure(*, db, frontend):
    _cfg.update(db=db, frontend=frontend)


def setup_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS inquiries(
        id SERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT '',
        source_id TEXT NOT NULL DEFAULT '',
        source_name TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL,
        company TEXT NOT NULL,
        email TEXT NOT NULL,
        role_type TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL,
        sender_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new')''')
    conn.execute('CREATE INDEX IF NOT EXISTS inquiries_sender ON inquiries(sender_hash, created_at)')


class InquiryIn(BaseModel):
    source_type: str = Field(default='', max_length=10)
    source_id: str = Field(default='', max_length=64)
    name: str = Field(max_length=80)
    company: str = Field(max_length=100)
    email: str = Field(max_length=120)
    role_type: str = Field(default='', max_length=20)
    message: str = Field(max_length=1000)
    website: str = Field(default='', max_length=200)   # honeypot: people never fill this


def _sender(request: Request):
    forwarded = request.headers.get('x-forwarded-for', '')
    ip = forwarded.split(',')[0].strip() if forwarded else (request.client.host if request.client else '')
    return hashlib.sha256(('imx-inquiry:' + ip).encode()).hexdigest()


def _resolve_source(conn, source_type, source_id):
    """Only public students/projects can be the subject of an inquiry. The name and
    link are looked up on the server, so a hand-edited request cannot mislabel them."""
    if not source_id:
        return '', '', '', ''
    if not ID_RE.match(source_id) or source_type not in ('student', 'project'):
        raise HTTPException(422, 'This inquiry link is not valid. Open the profile or project again and retry.')
    base = _cfg['frontend']
    if source_type == 'project':
        row = conn.execute('SELECT id, title FROM projects WHERE id=%s AND is_published=1', (source_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'That project is not public, so we cannot route this inquiry.')
        return 'project', row['id'], row['title'] or '', f'{base}/project.html?id={row["id"]}'
    row = conn.execute('SELECT id, name FROM students WHERE id=%s AND is_published=1', (source_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'That profile is not public, so we cannot route this inquiry.')
    return 'student', row['id'], row['name'] or '', f'{base}/student.html?id={row["id"]}'


@router.post('/api/inquiries', status_code=201)
def create_inquiry(payload: InquiryIn, request: Request):
    if payload.website.strip():
        # Bot filled the hidden field: accept quietly, store nothing.
        return {'message': 'Inquiry received.'}
    name, company = payload.name.strip(), payload.company.strip()
    email, message = payload.email.strip(), payload.message.strip()
    if not name:
        raise HTTPException(422, 'Add your name.')
    if not company:
        raise HTTPException(422, 'Add your company.')
    if not EMAIL_RE.match(email):
        raise HTTPException(422, 'Enter a valid email address.')
    if not message:
        raise HTTPException(422, 'Add a short message.')
    if payload.role_type not in ROLE_TYPES:
        raise HTTPException(422, 'Choose Internship, Contract or Full-time.')
    sender = _sender(request)
    now = datetime.now(timezone.utc)
    with _cfg['db']() as conn:
        recent = conn.execute('SELECT count(*) AS n FROM inquiries WHERE sender_hash=%s AND created_at > %s',
                              (sender, (now - RATE_WINDOW).isoformat())).fetchone()
        if recent and recent['n'] >= RATE_LIMIT:
            raise HTTPException(429, 'Too many inquiries in a short time. Please wait a few minutes and try again.')
        stype, sid, sname, surl = _resolve_source(conn, payload.source_type, payload.source_id.strip())
        row = conn.execute(
            '''INSERT INTO inquiries (created_at,source_type,source_id,source_name,source_url,
               name,company,email,role_type,message,sender_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
            (now.isoformat(), stype, sid, sname, surl, name, company, email,
             payload.role_type, message, sender)).fetchone()
    return {'id': row['id'], 'message': 'Inquiry sent to ImmXrsive staff.'}


@router.get('/api/staff/inquiries')
def list_inquiries(request: Request, limit: int = 100):
    token = os.environ.get('INQUIRY_ADMIN_TOKEN', '')
    if not token:
        raise HTTPException(503, 'Staff inbox is not configured on this server.')
    given = request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    if not hmac.compare_digest(given, token):
        raise HTTPException(401, 'Staff token required.')
    limit = max(1, min(limit, 500))
    with _cfg['db']() as conn:
        rows = conn.execute(
            '''SELECT id,created_at,source_type,source_id,source_name,source_url,name,company,
                      email,role_type,message,status FROM inquiries ORDER BY id DESC LIMIT %s''',
            (limit,)).fetchall()
    return [dict(r) for r in rows]
