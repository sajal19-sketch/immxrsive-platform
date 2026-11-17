"""ImmXrsive Release 4: staff operations, industry partners and collaborations.

Wired into main.py with configure(...) and app.include_router(router).

Decisions (also stated in RELEASE_NOTES_R4.md):
- Staff are a separate kind of account (staff_accounts) with their own sign-in
  and their own sessions. A student GitHub session is never accepted by a staff
  route, and a staff session is never accepted by a student route.
- Website import only produces *suggestions*. It never creates, publishes or
  verifies a company. A person must review and save a draft, then publish it.
- Imported page text is untrusted data (chosen Challenge R4.10). It is parsed
  with a plain HTML parser, never executed, never sent to an AI model, and text
  that looks like instructions to the system is flagged and left out of the
  suggested description. No field of a suggestion can carry a status,
  permission or verification value.
- Collaboration visibility is enforced on the server: private collaborations
  are never in a public response; limited ones are reduced to their public
  summary before they leave the server.
"""
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()
_cfg = {}

ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
HTTPS_RE = re.compile(r'^https://[^\s<>"\'`]+$', re.I)
STAFF_HOURS = 8


def configure(*, db, authenticated, parsed, frontend):
    _cfg.update(db=db, authenticated=authenticated, parsed=parsed, frontend=frontend)


def _db():
    return _cfg['db']()


def _now():
    return datetime.now(timezone.utc)


def _iso(dt=None):
    return (dt or _now()).isoformat()


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _clean(text, limit):
    return re.sub(r'\s+', ' ', str(text or '')).strip()[:limit]


def _check_id(value, what='Record'):
    if not ID_RE.match(value or ''):
        raise HTTPException(404, f'{what} not found')
    return value


# ====================================================================== schema

def setup_schema(conn):
    """Additive only: new tables and new columns, never a drop or rewrite."""
    conn.execute('''CREATE TABLE IF NOT EXISTS staff_accounts(
        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS staff_sessions(
        token_hash TEXT PRIMARY KEY, staff_id TEXT NOT NULL, expires_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS staff_login_failures(
        username TEXT NOT NULL, failed_at TEXT NOT NULL)''')

    # Official verification is kept in its own columns. No student route writes them.
    for key, spec in {'official_verified': 'INTEGER NOT NULL DEFAULT 0',
                      'verified_at': 'TEXT', 'verified_by': 'TEXT'}.items():
        conn.execute(f'ALTER TABLE projects ADD COLUMN IF NOT EXISTS {key} {spec}')
    conn.execute('''CREATE TABLE IF NOT EXISTS project_verification_requests(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, requested_by TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '', evidence_url TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending', staff_note TEXT NOT NULL DEFAULT '',
        decided_by TEXT, decided_at TEXT, created_at TEXT NOT NULL)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS companies(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, website TEXT NOT NULL DEFAULT '',
        domain TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
        sector TEXT NOT NULL DEFAULT '', keywords TEXT NOT NULL DEFAULT '[]',
        location TEXT NOT NULL DEFAULT '', logo_url TEXT NOT NULL DEFAULT '',
        relationship_summary TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft', version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT,
        published_at TEXT)''')
    conn.execute("CREATE INDEX IF NOT EXISTS companies_domain ON companies(domain) WHERE domain <> ''")
    conn.execute('''CREATE TABLE IF NOT EXISTS company_imports(
        id TEXT PRIMARY KEY, company_id TEXT, source_url TEXT NOT NULL, final_url TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL, candidates TEXT NOT NULL DEFAULT '{}', warnings TEXT NOT NULL DEFAULT '[]',
        error TEXT NOT NULL DEFAULT '', imported_by TEXT, imported_at TEXT NOT NULL,
        saved INTEGER NOT NULL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS company_field_history(
        id SERIAL PRIMARY KEY, company_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL,
        origin TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '', import_id TEXT,
        imported_at TEXT, recorded_by TEXT, recorded_at TEXT NOT NULL)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS collaborations(
        id TEXT PRIMARY KEY, company_id TEXT NOT NULL, title TEXT NOT NULL,
        start_year INTEGER, end_year INTEGER, description TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'past',
        visibility TEXT NOT NULL DEFAULT 'private', public_summary TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT, updated_by TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS collaboration_projects(
        collaboration_id TEXT NOT NULL, project_id TEXT NOT NULL, UNIQUE(collaboration_id, project_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS collaboration_students(
        collaboration_id TEXT NOT NULL, student_id TEXT NOT NULL, UNIQUE(collaboration_id, student_id))''')

    conn.execute('''CREATE TABLE IF NOT EXISTS partner_requests(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, company_id TEXT,
        suggested_name TEXT NOT NULL DEFAULT '', suggested_website TEXT NOT NULL DEFAULT '',
        explanation TEXT NOT NULL, requested_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        staff_note TEXT NOT NULL DEFAULT '', decided_by TEXT, decided_at TEXT, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS project_partners(
        project_id TEXT NOT NULL, company_id TEXT NOT NULL, request_id TEXT,
        approved_by TEXT, approved_at TEXT NOT NULL, UNIQUE(project_id, company_id))''')
    bootstrap_staff(conn)


# ====================================================================== staff accounts

def _hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310_000).hex()
    return f'pbkdf2${salt}${digest}'


def _password_ok(password, stored):
    try:
        _, salt, digest = stored.split('$')
    except ValueError:
        return False
    return hmac.compare_digest(_hash_password(password, salt).split('$')[2], digest)


def bootstrap_staff(conn):
    """Create the first staff account from STAFF_BOOTSTRAP_USERNAME / _PASSWORD
    (Render environment variables, never committed). An existing account's
    password is changed only when STAFF_BOOTSTRAP_RESET=1."""
    username = os.environ.get('STAFF_BOOTSTRAP_USERNAME', '').strip().lower()
    password = os.environ.get('STAFF_BOOTSTRAP_PASSWORD', '')
    if not username or len(password) < 12:
        return
    name = os.environ.get('STAFF_BOOTSTRAP_NAME', 'ImmXrsive Staff').strip() or 'ImmXrsive Staff'
    existing = conn.execute('SELECT id FROM staff_accounts WHERE username=%s', (username,)).fetchone()
    if not existing:
        conn.execute('INSERT INTO staff_accounts VALUES (%s,%s,%s,%s,1,%s)',
                     ('st_' + secrets.token_hex(8), username, name, _hash_password(password), _iso()))
    elif os.environ.get('STAFF_BOOTSTRAP_RESET') == '1':
        conn.execute('UPDATE staff_accounts SET password_hash=%s, is_active=1 WHERE id=%s',
                     (_hash_password(password), existing['id']))


class StaffLogin(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


@router.post('/api/staff/login')
def staff_login(payload: StaffLogin):
    username = payload.username.strip().lower()
    with _db() as conn:
        window = _iso(_now() - timedelta(minutes=15))
        fails = conn.execute('SELECT count(*) AS n FROM staff_login_failures WHERE username=%s AND failed_at>%s',
                             (username, window)).fetchone()['n']
        if fails >= 8:
            raise HTTPException(429, 'Too many failed sign-in attempts. Wait 15 minutes and try again.')
        row = conn.execute('SELECT * FROM staff_accounts WHERE username=%s AND is_active=1', (username,)).fetchone()
        if not row or not _password_ok(payload.password, row['password_hash']):
            conn.execute('INSERT INTO staff_login_failures VALUES (%s,%s)', (username, _iso()))
            raise HTTPException(401, 'Staff username or password is incorrect.')
        conn.execute('DELETE FROM staff_login_failures WHERE username=%s', (username,))
        token = 'stf_' + secrets.token_urlsafe(40)
        conn.execute('INSERT INTO staff_sessions VALUES (%s,%s,%s)',
                     (_hash(token), row['id'], _iso(_now() + timedelta(hours=STAFF_HOURS))))
    return {'access_token': token, 'token_type': 'bearer', 'name': row['display_name'],
            'expires_in': STAFF_HOURS * 3600}


def staff_from_request(request: Request):
    header = request.headers.get('authorization', '')
    if not header.startswith('Bearer '):
        raise HTTPException(401, 'Staff sign-in required.')
    token = header[7:].strip()
    with _db() as conn:
        s = conn.execute('SELECT staff_id, expires_at FROM staff_sessions WHERE token_hash=%s',
                         (_hash(token),)).fetchone()
        if not s or datetime.fromisoformat(s['expires_at']) < _now():
            # Ordinary student/public sessions are not in staff_sessions, so they end here.
            raise HTTPException(403, 'This action is only available to ImmXrsive staff.')
        staff = conn.execute('SELECT id, username, display_name FROM staff_accounts WHERE id=%s AND is_active=1',
                             (s['staff_id'],)).fetchone()
    if not staff:
        raise HTTPException(403, 'This action is only available to ImmXrsive staff.')
    return dict(staff)


def require_staff(request: Request):
    return staff_from_request(request)


@router.get('/api/staff/me')
def staff_me(staff=Depends(require_staff)):
    return {'id': staff['id'], 'name': staff['display_name'], 'username': staff['username'], 'role': 'staff'}


@router.post('/api/staff/logout')
def staff_logout(request: Request, staff=Depends(require_staff)):
    with _db() as conn:
        conn.execute('DELETE FROM staff_sessions WHERE token_hash=%s',
                     (_hash(request.headers['authorization'][7:].strip()),))
    return {'message': 'Signed out'}


def require_verified_student(request: Request):
    student = _cfg['authenticated'](request)
    if not student['is_algoma_verified']:
        raise HTTPException(403, 'Verify your Algoma email before managing projects.')
    return student


def _maintained_project(conn, pid, student):
    _check_id(pid, 'Project')
    p = conn.execute('SELECT * FROM projects WHERE id=%s', (pid,)).fetchone()
    if not p:
        raise HTTPException(404, 'Project not found')
    if p.get('maintainer_id') != student['id']:
        raise HTTPException(403, 'Only the project maintainer can do this.')
    return dict(p)


# ====================================================================== website import

class _PageParser(HTMLParser):
    """Collects visible text blocks and links. Script, style and similar content
    is dropped entirely; nothing from the page is ever executed."""
    SKIP = {'script', 'style', 'noscript', 'template', 'iframe', 'object', 'svg', 'head'}
    BLOCK = {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'address', 'td', 'dd', 'div', 'section', 'footer', 'span'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.title, self.h1, self.meta = '', '', {}
        self.blocks, self.links = [], []
        self._buf, self._tag, self._link = [], None, None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs}
        if tag == 'meta':
            key = (a.get('name') or a.get('property') or '').lower()
            if key in ('description', 'og:site_name', 'og:description', 'keywords', 'og:title'):
                self.meta[key] = _clean(a.get('content'), 600)
            return
        if tag == 'title':
            self._in_title = True
        if tag in self.SKIP and tag != 'head':
            self.skip += 1
            return
        if tag == 'a':
            self._link = {'href': a.get('href', ''), 'text': []}
        if tag in self.BLOCK:
            self._flush()
            self._tag = tag

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        if tag in self.SKIP and tag != 'head':
            self.skip = max(0, self.skip - 1)
            return
        if tag == 'a' and self._link is not None:
            self.links.append({'href': self._link['href'], 'text': _clean(' '.join(self._link['text']), 120)})
            self._link = None
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self.skip:
            return
        self._buf.append(data)
        if self._link is not None:
            self._link['text'].append(data)

    def _flush(self):
        text = _clean(''.join(self._buf), 2000)
        if text:
            if self._tag == 'h1' and not self.h1:
                self.h1 = text
            elif self._tag != 'h1':
                self.blocks.append(text)
        self._buf, self._tag = [], None

    def close(self):
        super().close()
        self._flush()


# Text that tries to steer the system (Challenge R4.10). Matching text is only
# *reported*; it never changes what the importer does.
INSTRUCTION_PATTERNS = [
    r'ignore (all )?(previous|prior|above) (instructions|prompts?)',
    r'\b(mark|set|make|flag)\b.{0,40}\b(verified|official|approved|partner)\b',
    r'\b(grant|give)\b.{0,30}\b(admin|administrator|staff|access|permission)',
    r'\bpublish (it |this )?(immediately|now|automatically)\b',
    r'\b(system|assistant|ai|model|extractor) (prompt|instructions?)\b',
    r'\byou are (now )?(an?|the) (ai|assistant|system|admin)',
    r'\bbypass\b.{0,30}\b(review|approval|moderation)\b',
]
BOILERPLATE = re.compile(r'^(contact us( for (more )?information)?\.?|home|menu|copyright.*|all rights reserved\.?|'
                         r'this .{0,40}(sentence|text) is untrusted .*)$', re.I)
KEYWORD_MAP = [
    ('extended reality', 'XR'), (r'\bxr\b', 'XR'), ('virtual reality', 'VR'), (r'\bvr\b', 'VR'),
    ('augmented reality', 'AR'), (r'\bar\b', 'AR'), ('mixed reality', 'MR'),
    ('spatial computing', 'spatial computing'), ('simulation', 'simulation'), ('training', 'training'),
    ('visuali[sz]ation', 'visualization'), ('game', 'games'), ('3d', '3D'), ('digital twin', 'digital twin'),
    ('prototyp', 'prototyping'), ('onboarding', 'onboarding'), ('safety', 'safety'),
    ('architect', 'architecture'), ('software', 'software'), ('machine learning', 'machine learning'),
]
COUNTRIES = {'canada', 'usa', 'united states', 'us', 'united states of america', 'u.s.a.'}


def looks_like_instruction(text):
    return any(re.search(p, text, re.I) for p in INSTRUCTION_PATTERNS)


def _location(blocks):
    for b in blocks:
        m = re.match(r'^(?:location|address|based in|headquarters|hq)\s*[:\-]\s*(.+)$', b, re.I)
        if not m:
            m = re.search(r'\b(?:located|based|headquartered) in ([A-Z][^.;]{2,80})', b)
        if m:
            loc = m.group(1).strip().rstrip('.')
            parts = [x.strip() for x in loc.split(',') if x.strip()]
            if len(parts) >= 3 and parts[-1].lower() in COUNTRIES:
                parts = parts[:-1]
            return ', '.join(parts)[:120]
    return ''


def _keywords(text):
    found = []
    low = text.lower()
    for pattern, label in KEYWORD_MAP:
        if re.search(pattern, low) and label not in found:
            found.append(label)
    return found[:12]


def extract_company(html, page_url):
    """Pure function: HTML text -> suggested company fields + warnings.
    Deterministic; never follows instructions found in the text."""
    p = _PageParser()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    blocks = p.blocks
    flagged = [b for b in blocks if looks_like_instruction(b)]
    usable = [b for b in blocks if b not in flagged and not BOILERPLATE.match(b)]

    name = p.meta.get('og:site_name') or p.h1 or re.split(r'\s+[|\-–—:]\s+', _clean(p.title, 200))[0]
    name = _clean(name, 150)

    label_re = re.compile(r'^(location|address|services|keywords|industries|sectors?|phone|email|tel)\s*[:\-]', re.I)
    desc = p.meta.get('description') or p.meta.get('og:description') or ''
    if desc and looks_like_instruction(desc):
        flagged.append(desc)
        desc = ''
    if not desc:
        prose = [b for b in usable if not label_re.match(b) and len(b) >= 25 and b != name]
        desc = ' '.join(prose[:2])
    desc = _clean(desc, 600)

    services = ' '.join(re.sub(label_re, '', b) for b in usable if re.match(r'^(services|keywords|industries|sectors?)\s*[:\-]', b, re.I))
    keywords = _keywords(' '.join([services, desc, p.meta.get('keywords', '')]))
    immersive = {'XR', 'VR', 'AR', 'MR', 'spatial computing', 'simulation', 'digital twin'}
    sector = 'Immersive technology and simulation' if immersive & set(keywords) else ''
    if not sector and 'visualization' in keywords:
        sector = 'Visualization'

    website = ''
    for link in p.links:
        href = urljoin(page_url, link['href'] or '')
        if re.match(r'^https?://', href) and re.search(r'website|home|visit|official', link['text'], re.I):
            website = href
            break
    if not website:
        # No "website" link on the page: suggest the imported page itself, so a
        # shared host (e.g. github.io) is never mistaken for the company's domain root.
        website = page_url.split('#')[0]
    website = website.rstrip('/')
    # Markup that arrived entity-encoded (e.g. in a meta tag) is still never passed on.
    def strip_markup(text):
        text = re.sub(r'<(script|style|iframe|object|template)\b[^>]*>.*?(</\1\s*>|$)', ' ', text, flags=re.I | re.S)
        return re.sub(r'<[^>]*>', ' ', text)
    name = _clean(strip_markup(name), 150)
    desc = _clean(strip_markup(desc), 600)
    candidates = {
        'name': name, 'description': desc, 'website': website, 'domain': domain_of(website),
        'sector': sector, 'keywords': keywords, 'location': _location(usable),
    }
    warnings = []
    if flagged:
        warnings.append('This page contains text that reads like instructions to the system (for example to verify '
                        'the company, grant access or publish it). It was treated as ordinary page text, ignored, and '
                        'left out of the suggested description. Nothing was verified, published or given access.')
    missing = [k for k in ('name', 'description', 'sector', 'location') if not candidates[k]]
    return candidates, warnings, missing, flagged


SHARED_HOSTS = ('github.io', 'vercel.app', 'netlify.app', 'onrender.com', 'pages.dev', 'web.app')


def domain_of(url):
    """Comparable website identity used for duplicate warnings. On shared hosting
    the full page path identifies the site, so two companies hosted on github.io
    are not treated as the same domain."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
    except ValueError:
        return ''
    host = host[4:] if host.startswith('www.') else host
    if host.endswith(SHARED_HOSTS):
        path = parts.path.rstrip('/')
        path = re.sub(r'/index\.html?$', '', path)
        return (host + path).lower()
    return host


def _allow_local():
    return os.environ.get('ALLOW_LOCAL_IMPORTS') == '1'


def _check_target(url):
    parts = urlsplit(url)
    if parts.scheme not in ('https', 'http') or not parts.hostname:
        raise ValueError('Enter a full website address starting with https://')
    if parts.scheme == 'http' and not _allow_local():
        raise ValueError('Only https:// websites can be imported.')
    if parts.username or parts.password:
        raise ValueError('Website addresses with a user name or password are not accepted.')
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80))
    except socket.gaierror:
        raise ValueError('That website address could not be found.')
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global and not (_allow_local() and ip.is_loopback):
            raise ValueError('That address points to a private network and cannot be imported.')


def fetch_page(url):
    """Fetch at most 1 MB of HTML, following up to 3 redirects, re-checking each hop."""
    import httpx
    current = url
    with httpx.Client(timeout=8, follow_redirects=False,
                      headers={'User-Agent': 'ImmXrsive-partner-import/1.0', 'Accept': 'text/html'}) as client:
        for _ in range(4):
            _check_target(current)
            with client.stream('GET', current) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get('location'):
                    current = urljoin(current, r.headers['location'])
                    continue
                if r.status_code != 200:
                    raise ValueError(f'The website answered with an error ({r.status_code}).')
                ctype = r.headers.get('content-type', '').lower()
                if ctype and 'html' not in ctype and 'text/plain' not in ctype:
                    raise ValueError('That address is not a web page.')
                body = b''
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > 1_000_000:
                        break
                return body.decode(r.encoding or 'utf-8', errors='replace'), str(current)
    raise ValueError('The website redirected too many times.')


class ImportIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)
    company_id: str = ''


@router.post('/api/staff/company-imports')
def import_company(payload: ImportIn, staff=Depends(require_staff)):
    """Returns suggestions only. A failed import is recorded and reported, and the
    caller keeps whatever it had typed (R4.11)."""
    url = payload.url.strip()
    if not re.match(r'^[a-z]+://', url, re.I):
        url = 'https://' + url
    company_id = payload.company_id.strip()
    with _db() as conn:
        if company_id:
            _check_id(company_id, 'Partner')
            if not conn.execute('SELECT 1 FROM companies WHERE id=%s', (company_id,)).fetchone():
                raise HTTPException(404, 'Partner not found')
    iid = 'imp_' + secrets.token_hex(8)
    stamp = _iso()
    try:
        html, final_url = fetch_page(url)
        candidates, warnings, missing, flagged = extract_company(html, final_url)
        status = 'partial' if missing else 'ok'
        error = ''
    except Exception as exc:  # network, DNS, parsing: all become a recoverable failure
        final_url, candidates, warnings, missing, flagged = '', {}, [], [], []
        status, error = 'failed', (str(exc) if isinstance(exc, ValueError) else 'The website could not be reached.')
    with _db() as conn:
        conn.execute('''INSERT INTO company_imports (id,company_id,source_url,final_url,status,candidates,warnings,
                        error,imported_by,imported_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                     (iid, company_id or None, url, final_url, status, json.dumps(candidates), json.dumps(warnings),
                      error, staff['id'], stamp))
        dupes = domain_matches(conn, candidates.get('domain', ''), exclude=company_id) if candidates else []
        similar = similar_names(conn, candidates.get('name', ''), exclude=company_id) if candidates else []
    msg = {'ok': 'Suggestions ready. Review and edit them, then save the partner as a draft.',
           'partial': 'Some details could not be found on the page. Fill in the missing ones yourself, then save.',
           'failed': 'The website could not be imported. Nothing you typed was changed; you can finish the partner by hand.'}[status]
    return {'import_id': iid, 'status': status, 'source_url': url, 'final_url': final_url, 'imported_at': stamp,
            'suggestion': candidates, 'missing': missing, 'warnings': warnings, 'ignored_text': flagged[:5],
            'error': error, 'duplicate_domain': dupes, 'similar_names': similar, 'message': msg}


@router.get('/api/staff/company-imports/{import_id}')
def get_import(import_id: str, staff=Depends(require_staff)):
    _check_id(import_id, 'Import')
    with _db() as conn:
        r = conn.execute('SELECT * FROM company_imports WHERE id=%s', (import_id,)).fetchone()
    if not r:
        raise HTTPException(404, 'Import not found')
    return {'import_id': r['id'], 'status': r['status'], 'source_url': r['source_url'], 'final_url': r['final_url'],
            'imported_at': r['imported_at'], 'company_id': r['company_id'], 'error': r['error'],
            'suggestion': json.loads(r['candidates'] or '{}'), 'warnings': json.loads(r['warnings'] or '[]')}


# ====================================================================== companies (staff)

COMPANY_FIELDS = ['name', 'website', 'description', 'sector', 'keywords', 'location', 'logo_url',
                  'relationship_summary']
FIELD_LABELS = {'name': 'Name', 'website': 'Website', 'description': 'About the company', 'sector': 'Sector',
                'keywords': 'Keywords', 'location': 'Location', 'logo_url': 'Logo image',
                'relationship_summary': 'How ImmXrsive works with them'}


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    website: str = Field(default='', max_length=300)
    description: str = Field(default='', max_length=2000)
    sector: str = Field(default='', max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    location: str = Field(default='', max_length=120)
    logo_url: str = Field(default='', max_length=500)
    relationship_summary: str = Field(default='', max_length=1500)
    import_id: str = ''
    version: int | None = None
    use_existing_ok: bool = False   # staff confirmed a same-domain record is really a different company


def _https(value, label):
    value = (value or '').strip()
    if not value:
        return ''
    local_ok = _allow_local() and re.match(r'^http://(127\.0\.0\.1|localhost)(:\d+)?/', value)
    if not HTTPS_RE.match(value) and not local_ok:
        raise HTTPException(422, f'{label} must be a full link starting with https://')
    return value.rstrip('/') if label == 'Website' else value


def _website(value, label):
    """Accept 'example.com' or a full https link; refuse any other scheme
    (javascript:, data:, ftp:...) instead of prefixing it with https://."""
    value = (value or '').strip()
    if not value:
        return ''
    if re.match(r'^[a-z][a-z0-9+.-]*:', value, re.I) and not re.match(r'^https?://', value, re.I):
        raise HTTPException(422, f'{label} must be a normal website address starting with https://')
    if not re.match(r'^https?://', value, re.I):
        value = 'https://' + value
    return _https(value, label)


def _validated_company(c: CompanyIn):
    name = _clean(c.name, 150)
    if not name:
        raise HTTPException(422, 'Add the company name.')
    website = _website(c.website, 'Website')
    keywords = []
    for k in c.keywords:
        k = _clean(k, 40)
        if k and k.casefold() not in {x.casefold() for x in keywords}:
            keywords.append(k)
    return {'name': name, 'website': website, 'domain': domain_of(website),
            'description': c.description.strip(), 'sector': _clean(c.sector, 100), 'keywords': keywords,
            'location': _clean(c.location, 120), 'logo_url': _https(c.logo_url, 'Logo image'),
            'relationship_summary': c.relationship_summary.strip()}


def domain_matches(conn, domain, exclude=''):
    if not domain:
        return []
    rows = conn.execute('SELECT id, name, status, domain FROM companies WHERE domain=%s AND id<>%s',
                        (domain, exclude or '')).fetchall()
    return [{'id': r['id'], 'name': r['name'], 'status': r['status'], 'domain': r['domain']} for r in rows]


def similar_names(conn, name, exclude=''):
    words = {w for w in re.findall(r'[a-z0-9]+', (name or '').lower()) if len(w) > 2}
    if not words:
        return []
    out = []
    for r in conn.execute('SELECT id, name, domain, status FROM companies WHERE id<>%s', (exclude or '',)).fetchall():
        other = set(re.findall(r'[a-z0-9]+', (r['name'] or '').lower()))
        if other and len(words & other) / len(words) >= 0.5:
            out.append({'id': r['id'], 'name': r['name'], 'domain': r['domain'], 'status': r['status']})
    return out[:5]


def _record_history(conn, cid, before, after, import_row, staff):
    cands = json.loads(import_row['candidates']) if import_row else {}
    for f in COMPANY_FIELDS:
        new, old = after.get(f), (before or {}).get(f)
        if before is not None and new == old:
            continue
        if before is None and new in ('', [], None):
            continue
        from_import = import_row is not None and f in cands and cands.get(f) == new and new not in ('', [])
        conn.execute('''INSERT INTO company_field_history (company_id,field,value,origin,source_url,import_id,
                        imported_at,recorded_by,recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                     (cid, f, json.dumps(new) if isinstance(new, list) else str(new or ''),
                      'website import' if from_import else 'staff edit',
                      (import_row['final_url'] or import_row['source_url']) if from_import else '',
                      import_row['id'] if from_import else None,
                      import_row['imported_at'] if from_import else None, staff['id'], _iso()))


def _import_row(conn, import_id):
    if not import_id:
        return None
    _check_id(import_id, 'Import')
    return conn.execute('SELECT * FROM company_imports WHERE id=%s', (import_id,)).fetchone()


def _company_row(conn, cid):
    _check_id(cid, 'Partner')
    r = conn.execute('SELECT * FROM companies WHERE id=%s', (cid,)).fetchone()
    if not r:
        raise HTTPException(404, 'Partner not found')
    out = dict(r)
    out['keywords'] = _cfg['parsed'](out.get('keywords'))
    return out


@router.post('/api/staff/companies')
def create_company(payload: CompanyIn, staff=Depends(require_staff)):
    data = _validated_company(payload)
    with _db() as conn:
        dupes = domain_matches(conn, data['domain'])
        if dupes and not payload.use_existing_ok:
            raise HTTPException(409, {'code': 'duplicate_domain', 'matches': dupes,
                                      'message': f"A partner with the website {data['domain']} already exists. "
                                                 'Open that partner instead of creating a second copy.'})
        imp = _import_row(conn, payload.import_id)
        cid = 'c_' + secrets.token_hex(6)
        stamp = _iso()
        conn.execute('''INSERT INTO companies (id,name,website,domain,description,sector,keywords,location,logo_url,
                        relationship_summary,status,version,created_at,updated_at,created_by,updated_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',1,%s,%s,%s,%s)''',
                     (cid, data['name'], data['website'], data['domain'], data['description'], data['sector'],
                      json.dumps(data['keywords']), data['location'], data['logo_url'], data['relationship_summary'],
                      stamp, stamp, staff['id'], staff['id']))
        _record_history(conn, cid, None, data, imp, staff)
        if imp:
            conn.execute('UPDATE company_imports SET saved=1, company_id=%s WHERE id=%s', (cid, imp['id']))
    return {'id': cid, 'version': 1, 'status': 'draft',
            'message': 'Saved as a draft. It is not public until you choose Publish.'}


@router.put('/api/staff/companies/{cid}')
def update_company(cid: str, payload: CompanyIn, staff=Depends(require_staff)):
    data = _validated_company(payload)
    with _db() as conn:
        before = _company_row(conn, cid)
        if payload.version is not None and payload.version != before['version']:
            raise HTTPException(409, {'code': 'stale_version',
                                      'message': 'Someone else saved this partner after you opened it. Your changes '
                                                 'were not saved. Reload to see the latest version.'})
        dupes = domain_matches(conn, data['domain'], exclude=cid)
        if dupes and not payload.use_existing_ok:
            raise HTTPException(409, {'code': 'duplicate_domain', 'matches': dupes,
                                      'message': f"Another partner already uses the website {data['domain']}."})
        imp = _import_row(conn, payload.import_id)
        conn.execute('''UPDATE companies SET name=%s,website=%s,domain=%s,description=%s,sector=%s,keywords=%s,
                        location=%s,logo_url=%s,relationship_summary=%s,updated_at=%s,updated_by=%s,version=version+1
                        WHERE id=%s''',
                     (data['name'], data['website'], data['domain'], data['description'], data['sector'],
                      json.dumps(data['keywords']), data['location'], data['logo_url'], data['relationship_summary'],
                      _iso(), staff['id'], cid))
        _record_history(conn, cid, before, data, imp, staff)
        if imp:
            conn.execute('UPDATE company_imports SET saved=1, company_id=%s WHERE id=%s', (cid, imp['id']))
        version = before['version'] + 1
    return {'id': cid, 'version': version, 'message': 'Changes saved.' +
            (' The public page shows them now.' if before['status'] == 'published' else '')}


class Publish(BaseModel):
    reviewed: bool = False


@router.post('/api/staff/companies/{cid}/publish')
def publish_company(cid: str, payload: Publish, staff=Depends(require_staff)):
    if not payload.reviewed:
        raise HTTPException(422, 'Confirm that you reviewed the partner details before publishing.')
    with _db() as conn:
        c = _company_row(conn, cid)
        if not c['description'] and not c['relationship_summary']:
            raise HTTPException(422, 'Add a short description or explain how ImmXrsive works with them before publishing.')
        conn.execute("UPDATE companies SET status='published', published_at=%s, updated_at=%s, updated_by=%s WHERE id=%s",
                     (_iso(), _iso(), staff['id'], cid))
    return {'message': 'Partner published. It now appears on the Industry Partners page.',
            'public_url': f"{_cfg['frontend']}/partner.html?id={cid}"}


@router.post('/api/staff/companies/{cid}/unpublish')
def unpublish_company(cid: str, staff=Depends(require_staff)):
    with _db() as conn:
        _company_row(conn, cid)
        conn.execute("UPDATE companies SET status='draft', updated_at=%s, updated_by=%s WHERE id=%s",
                     (_iso(), staff['id'], cid))
    return {'message': 'Partner hidden from the public site. Nothing was deleted.'}


def _history(conn, cid):
    rows = conn.execute('SELECT * FROM company_field_history WHERE company_id=%s ORDER BY id DESC', (cid,)).fetchall()
    latest = {}
    for r in rows:
        latest.setdefault(r['field'], {'label': FIELD_LABELS.get(r['field'], r['field']), 'origin': r['origin'],
                                       'source_url': r['source_url'], 'imported_at': r['imported_at'],
                                       'recorded_at': r['recorded_at']})
    return latest, [{'field': FIELD_LABELS.get(r['field'], r['field']), 'origin': r['origin'],
                     'source_url': r['source_url'], 'when': r['imported_at'] or r['recorded_at']} for r in rows[:40]]


@router.get('/api/staff/companies')
def list_companies(staff=Depends(require_staff)):
    with _db() as conn:
        rows = conn.execute('''SELECT c.id, c.name, c.domain, c.status, c.updated_at,
                                  (SELECT count(*) FROM collaborations x WHERE x.company_id=c.id) AS collabs
                               FROM companies c ORDER BY lower(c.name)''').fetchall()
    return [dict(r) for r in rows]


@router.get('/api/staff/companies/{cid}')
def staff_company(cid: str, staff=Depends(require_staff)):
    with _db() as conn:
        c = _company_row(conn, cid)
        latest, log = _history(conn, cid)
        collabs = [_staff_collab(conn, r) for r in conn.execute(
            'SELECT * FROM collaborations WHERE company_id=%s ORDER BY coalesce(start_year,0) DESC, title', (cid,)).fetchall()]
        imports = [dict(r) for r in conn.execute(
            '''SELECT id, source_url, final_url, status, imported_at FROM company_imports WHERE company_id=%s
               ORDER BY imported_at DESC LIMIT 10''', (cid,)).fetchall()]
        projects = [dict(r) for r in conn.execute(
            '''SELECT p.id, p.title, p.is_published FROM project_partners pp JOIN projects p ON p.id=pp.project_id
               WHERE pp.company_id=%s ORDER BY p.title''', (cid,)).fetchall()]
    c['field_sources'] = latest
    c['history'] = log
    c['collaborations'] = collabs
    c['imports'] = imports
    c['approved_projects'] = projects
    return c


# ====================================================================== collaborations (staff)

VISIBILITY = {'public', 'limited', 'private'}
COLLAB_STATUS = {'current', 'past'}


class CollabIn(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    start_year: int | None = Field(default=None, ge=1990, le=2100)
    end_year: int | None = Field(default=None, ge=1990, le=2100)
    description: str = Field(default='', max_length=2000)
    outcome: str = Field(default='', max_length=1000)
    status: str = 'current'
    visibility: str = 'private'
    public_summary: str = Field(default='', max_length=400)
    project_ids: list[str] = Field(default_factory=list, max_length=20)
    student_ids: list[str] = Field(default_factory=list, max_length=40)


def _validated_collab(conn, c: CollabIn):
    if c.status not in COLLAB_STATUS:
        raise HTTPException(422, 'Choose Current or Past.')
    if c.visibility not in VISIBILITY:
        raise HTTPException(422, 'Choose Public, Limited or Private.')
    if c.start_year and c.end_year and c.end_year < c.start_year:
        raise HTTPException(422, 'The end year cannot be before the start year.')
    if c.visibility == 'limited' and not c.public_summary.strip():
        raise HTTPException(422, 'Limited collaborations need a short public summary that shows no confidential details.')
    pids = list(dict.fromkeys(_check_id(x, 'Project') for x in c.project_ids))
    sids = list(dict.fromkeys(_check_id(x, 'Student') for x in c.student_ids))
    if pids:
        found = {r['id'] for r in conn.execute('SELECT id FROM projects WHERE id = ANY(%s)', (pids,)).fetchall()}
        if set(pids) - found:
            raise HTTPException(422, 'One of the chosen projects no longer exists.')
    if sids:
        found = {r['id'] for r in conn.execute('SELECT id FROM students WHERE id = ANY(%s)', (sids,)).fetchall()}
        if set(sids) - found:
            raise HTTPException(422, 'One of the chosen students no longer exists.')
    return pids, sids


def _save_links(conn, xid, pids, sids):
    conn.execute('DELETE FROM collaboration_projects WHERE collaboration_id=%s', (xid,))
    conn.execute('DELETE FROM collaboration_students WHERE collaboration_id=%s', (xid,))
    for pid in pids:
        conn.execute('INSERT INTO collaboration_projects VALUES (%s,%s) ON CONFLICT DO NOTHING', (xid, pid))
    for sid in sids:
        conn.execute('INSERT INTO collaboration_students VALUES (%s,%s) ON CONFLICT DO NOTHING', (xid, sid))


def _staff_collab(conn, r):
    x = dict(r)
    x['projects'] = [dict(p) for p in conn.execute(
        '''SELECT p.id, p.title, p.is_published FROM collaboration_projects cp JOIN projects p ON p.id=cp.project_id
           WHERE cp.collaboration_id=%s ORDER BY p.title''', (x['id'],)).fetchall()]
    x['students'] = [dict(s) for s in conn.execute(
        '''SELECT s.id, s.name, s.is_published FROM collaboration_students cs JOIN students s ON s.id=cs.student_id
           WHERE cs.collaboration_id=%s ORDER BY s.name''', (x['id'],)).fetchall()]
    return x


@router.post('/api/staff/companies/{cid}/collaborations')
def add_collaboration(cid: str, payload: CollabIn, staff=Depends(require_staff)):
    with _db() as conn:
        _company_row(conn, cid)
        pids, sids = _validated_collab(conn, payload)
        xid = 'col_' + secrets.token_hex(6)
        stamp = _iso()
        conn.execute('''INSERT INTO collaborations (id,company_id,title,start_year,end_year,description,outcome,status,
                        visibility,public_summary,created_at,updated_at,created_by,updated_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                     (xid, cid, _clean(payload.title, 150), payload.start_year, payload.end_year,
                      payload.description.strip(), payload.outcome.strip(), payload.status, payload.visibility,
                      _clean(payload.public_summary, 400), stamp, stamp, staff['id'], staff['id']))
        _save_links(conn, xid, pids, sids)
    return {'id': xid, 'message': 'Collaboration added.'}


@router.put('/api/staff/collaborations/{xid}')
def update_collaboration(xid: str, payload: CollabIn, staff=Depends(require_staff)):
    _check_id(xid, 'Collaboration')
    with _db() as conn:
        if not conn.execute('SELECT 1 FROM collaborations WHERE id=%s', (xid,)).fetchone():
            raise HTTPException(404, 'Collaboration not found')
        pids, sids = _validated_collab(conn, payload)
        conn.execute('''UPDATE collaborations SET title=%s,start_year=%s,end_year=%s,description=%s,outcome=%s,
                        status=%s,visibility=%s,public_summary=%s,updated_at=%s,updated_by=%s WHERE id=%s''',
                     (_clean(payload.title, 150), payload.start_year, payload.end_year, payload.description.strip(),
                      payload.outcome.strip(), payload.status, payload.visibility,
                      _clean(payload.public_summary, 400), _iso(), staff['id'], xid))
        _save_links(conn, xid, pids, sids)
    return {'id': xid, 'message': 'Collaboration saved.'}


@router.get('/api/staff/lookup')
def lookup(q: str = '', staff=Depends(require_staff)):
    """Projects and students staff can attach to a collaboration."""
    like = '%' + q.strip().lower()[:60] + '%'
    with _db() as conn:
        projects = [dict(r) for r in conn.execute(
            'SELECT id, title, is_published FROM projects WHERE lower(title) LIKE %s OR lower(id) LIKE %s '
            'ORDER BY title LIMIT 50', (like, like)).fetchall()]
        students = [dict(r) for r in conn.execute(
            'SELECT id, name, is_published FROM students WHERE lower(coalesce(name,\'\')) LIKE %s OR lower(id) LIKE %s '
            'ORDER BY name LIMIT 50', (like, like)).fetchall()]
    return {'projects': projects, 'students': students}


# ====================================================================== project verification

class VerificationIn(BaseModel):
    note: str = Field(min_length=1, max_length=1500)
    evidence_url: str = Field(default='', max_length=500)


@router.post('/api/projects/{pid}/verification-request')
def request_verification(pid: str, payload: VerificationIn, student=Depends(require_verified_student)):
    note = payload.note.strip()
    if not note:
        raise HTTPException(422, 'Explain briefly why this project should be officially verified.')
    evidence = _https(payload.evidence_url, 'Evidence link')
    with _db() as conn:
        p = _maintained_project(conn, pid, student)
        if p.get('official_verified'):
            raise HTTPException(409, 'This project is already officially verified.')
        if conn.execute("SELECT 1 FROM project_verification_requests WHERE project_id=%s AND status='pending'",
                        (pid,)).fetchone():
            raise HTTPException(409, 'A verification request for this project is already waiting for staff review.')
        rid = 'vr_' + secrets.token_hex(6)
        conn.execute('''INSERT INTO project_verification_requests (id,project_id,requested_by,note,evidence_url,status,created_at)
                        VALUES (%s,%s,%s,%s,%s,'pending',%s)''', (rid, pid, student['id'], note, evidence, _iso()))
    return {'id': rid, 'message': 'Verification requested. ImmXrsive staff will review it; the project is not verified until they approve.'}


class PartnerRequestIn(BaseModel):
    company_id: str = ''
    suggested_name: str = Field(default='', max_length=150)
    suggested_website: str = Field(default='', max_length=300)
    explanation: str = Field(min_length=1, max_length=1500)


@router.post('/api/projects/{pid}/partner-requests')
def request_partner(pid: str, payload: PartnerRequestIn, student=Depends(require_verified_student)):
    explanation = payload.explanation.strip()
    if not explanation:
        raise HTTPException(422, 'Explain how this company was involved in the project.')
    company_id = payload.company_id.strip()
    name = _clean(payload.suggested_name, 150)
    website = _website(payload.suggested_website, 'Company website')
    if not company_id and not name:
        raise HTTPException(422, 'Choose a company from the list or type the name of a new one.')
    with _db() as conn:
        _maintained_project(conn, pid, student)
        if company_id:
            _check_id(company_id, 'Company')
            if not conn.execute("SELECT 1 FROM companies WHERE id=%s AND status='published'", (company_id,)).fetchone():
                raise HTTPException(404, 'That company is not on the partner list. Suggest it as a new company instead.')
            if conn.execute('SELECT 1 FROM project_partners WHERE project_id=%s AND company_id=%s',
                            (pid, company_id)).fetchone():
                raise HTTPException(409, 'This company is already an approved partner on this project.')
            dup = conn.execute("SELECT 1 FROM partner_requests WHERE project_id=%s AND company_id=%s AND status='pending'",
                               (pid, company_id)).fetchone()
            name, website = '', ''
        else:
            dup = conn.execute("""SELECT 1 FROM partner_requests WHERE project_id=%s AND company_id IS NULL
                                  AND lower(suggested_name)=lower(%s) AND status='pending'""", (pid, name)).fetchone()
        if dup:
            raise HTTPException(409, 'You already asked to add this company. It is waiting for staff review.')
        rid = 'pr_' + secrets.token_hex(6)
        conn.execute('''INSERT INTO partner_requests (id,project_id,company_id,suggested_name,suggested_website,
                        explanation,requested_by,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s)''',
                     (rid, pid, company_id or None, name, website, explanation, student['id'], _iso()))
    return {'id': rid, 'message': 'Request sent. The company will appear on your project only after ImmXrsive staff approve it.'}


@router.post('/api/projects/{pid}/partner-requests/{rid}/withdraw')
def withdraw_partner_request(pid: str, rid: str, student=Depends(require_verified_student)):
    with _db() as conn:
        _maintained_project(conn, pid, student)
        _check_id(rid, 'Request')
        r = conn.execute("UPDATE partner_requests SET status='withdrawn', decided_at=%s WHERE id=%s AND project_id=%s "
                         "AND status='pending' RETURNING id", (_iso(), rid, pid)).fetchone()
    if not r:
        raise HTTPException(404, 'No pending request to withdraw.')
    return {'message': 'Request withdrawn.'}


@router.get('/api/my/projects/{pid}/industry')
def my_project_industry(pid: str, student=Depends(require_verified_student)):
    """What the project team sees about verification and partner requests."""
    _check_id(pid, 'Project')
    with _db() as conn:
        p = conn.execute('SELECT * FROM projects WHERE id=%s', (pid,)).fetchone()
        if not p:
            raise HTTPException(404, 'Project not found')
        member = conn.execute("SELECT 1 FROM project_contributors WHERE project_id=%s AND student_id=%s AND status='accepted'",
                              (pid, student['id'])).fetchone()
        if not member and p.get('maintainer_id') != student['id']:
            raise HTTPException(403, 'You are not part of this project.')
        vreq = conn.execute('''SELECT id, status, note, staff_note, created_at, decided_at FROM project_verification_requests
                               WHERE project_id=%s ORDER BY created_at DESC LIMIT 1''', (pid,)).fetchone()
        reqs = [dict(r) for r in conn.execute(
            '''SELECT r.id, r.status, r.explanation, r.staff_note, r.created_at, r.decided_at,
                      coalesce(c.name, r.suggested_name) AS company_name, r.company_id
               FROM partner_requests r LEFT JOIN companies c ON c.id=r.company_id
               WHERE r.project_id=%s ORDER BY r.created_at DESC''', (pid,)).fetchall()]
        partners = [dict(r) for r in conn.execute(
            '''SELECT c.id, c.name, c.status FROM project_partners pp JOIN companies c ON c.id=pp.company_id
               WHERE pp.project_id=%s ORDER BY c.name''', (pid,)).fetchall()]
    return {'is_maintainer': p.get('maintainer_id') == student['id'],
            'official_verified': bool(p.get('official_verified')), 'verified_at': p.get('verified_at'),
            'verification_request': dict(vreq) if vreq else None,
            'partner_requests': reqs, 'partners': partners}


# ====================================================================== staff review

class DecisionIn(BaseModel):
    approve: bool
    staff_note: str = Field(default='', max_length=1000)
    company_id: str = ''          # partner request: link to this existing company instead


def _people(conn, pid):
    return [dict(r) for r in conn.execute(
        '''SELECT c.student_id, s.name, c.role, c.status, c.statement FROM project_contributors c
           LEFT JOIN students s ON s.id=c.student_id WHERE c.project_id=%s ORDER BY c.status, s.name''', (pid,)).fetchall()]


def _project_summary(conn, pid):
    p = conn.execute('''SELECT id, title, description, domain, status, project_date, is_published, maintainer_id,
                               official_verified, playable_url, fallback_url FROM projects WHERE id=%s''', (pid,)).fetchone()
    if not p:
        return None
    out = dict(p)
    out['contributors'] = _people(conn, pid)
    out['repo_urls'] = [r['url'] for r in conn.execute('SELECT url FROM project_repos WHERE project_id=%s', (pid,)).fetchall()]
    return out


@router.get('/api/staff/verification-requests/{rid}')
def staff_verification_detail(rid: str, staff=Depends(require_staff)):
    _check_id(rid, 'Request')
    with _db() as conn:
        r = conn.execute('''SELECT v.*, s.name AS requester FROM project_verification_requests v
                            LEFT JOIN students s ON s.id=v.requested_by WHERE v.id=%s''', (rid,)).fetchone()
        if not r:
            raise HTTPException(404, 'Request not found')
        out = dict(r)
        out['project'] = _project_summary(conn, r['project_id'])
    return out


@router.post('/api/staff/verification-requests/{rid}/decision')
def staff_verification_decision(rid: str, payload: DecisionIn, staff=Depends(require_staff)):
    _check_id(rid, 'Request')
    note = payload.staff_note.strip()
    if not payload.approve and not note:
        raise HTTPException(422, 'Tell the students why the request was not approved.')
    with _db() as conn:
        r = conn.execute("SELECT * FROM project_verification_requests WHERE id=%s", (rid,)).fetchone()
        if not r:
            raise HTTPException(404, 'Request not found')
        if r['status'] != 'pending':
            raise HTTPException(409, f"This request was already {r['status']}. Refresh the list.")
        status = 'approved' if payload.approve else 'rejected'
        conn.execute('''UPDATE project_verification_requests SET status=%s, staff_note=%s, decided_by=%s, decided_at=%s
                        WHERE id=%s''', (status, note, staff['id'], _iso(), rid))
        if payload.approve:
            conn.execute('UPDATE projects SET official_verified=1, verified_at=%s, verified_by=%s WHERE id=%s',
                         (_iso(), staff['id'], r['project_id']))
    return {'message': 'Project officially verified.' if payload.approve else 'Request rejected. The students can see your note.'}


@router.post('/api/staff/projects/{pid}/verification/revoke')
def staff_revoke_verification(pid: str, staff=Depends(require_staff)):
    _check_id(pid, 'Project')
    with _db() as conn:
        r = conn.execute('UPDATE projects SET official_verified=0, verified_at=NULL, verified_by=%s WHERE id=%s RETURNING id',
                         (staff['id'], pid)).fetchone()
    if not r:
        raise HTTPException(404, 'Project not found')
    return {'message': 'Official verification removed.'}


@router.get('/api/staff/partner-requests/{rid}')
def staff_partner_request(rid: str, staff=Depends(require_staff)):
    _check_id(rid, 'Request')
    with _db() as conn:
        r = conn.execute('''SELECT r.*, s.name AS requester, c.name AS company_name, c.status AS company_status
                            FROM partner_requests r LEFT JOIN students s ON s.id=r.requested_by
                            LEFT JOIN companies c ON c.id=r.company_id WHERE r.id=%s''', (rid,)).fetchone()
        if not r:
            raise HTTPException(404, 'Request not found')
        out = dict(r)
        out['project'] = _project_summary(conn, r['project_id'])
        dom = domain_of(r['suggested_website']) if r['suggested_website'] else ''
        out['possible_matches'] = (domain_matches(conn, dom) + similar_names(conn, r['suggested_name'])) if not r['company_id'] else []
    return out


@router.post('/api/staff/partner-requests/{rid}/decision')
def staff_partner_decision(rid: str, payload: DecisionIn, staff=Depends(require_staff)):
    _check_id(rid, 'Request')
    note = payload.staff_note.strip()
    if not payload.approve and not note:
        raise HTTPException(422, 'Tell the students why the request was not approved.')
    with _db() as conn:
        r = conn.execute('SELECT * FROM partner_requests WHERE id=%s', (rid,)).fetchone()
        if not r:
            raise HTTPException(404, 'Request not found')
        if r['status'] != 'pending':
            raise HTTPException(409, f"This request was already {r['status']}. Refresh the list.")
        created_draft = None
        if payload.approve:
            cid = payload.company_id.strip() or r['company_id']
            if cid:
                _company_row(conn, cid)
            else:
                # Suggested company: create an unpublished draft staff must still review and publish.
                website = r['suggested_website'] or ''
                dupes = domain_matches(conn, domain_of(website))
                if dupes:
                    raise HTTPException(409, {'code': 'duplicate_domain', 'matches': dupes,
                                              'message': 'A partner with this website already exists. Choose it below and approve again.'})
                cid = 'c_' + secrets.token_hex(6)
                stamp = _iso()
                conn.execute('''INSERT INTO companies (id,name,website,domain,status,version,created_at,updated_at,
                                created_by,updated_by) VALUES (%s,%s,%s,%s,'draft',1,%s,%s,%s,%s)''',
                             (cid, r['suggested_name'], website, domain_of(website), stamp, stamp, staff['id'], staff['id']))
                conn.execute('''INSERT INTO company_field_history (company_id,field,value,origin,recorded_by,recorded_at)
                                VALUES (%s,'name',%s,'student suggestion',%s,%s)''', (cid, r['suggested_name'], staff['id'], stamp))
                created_draft = cid
            conn.execute('''INSERT INTO project_partners (project_id,company_id,request_id,approved_by,approved_at)
                            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (project_id,company_id) DO NOTHING''',
                         (r['project_id'], cid, rid, staff['id'], _iso()))
            conn.execute("UPDATE partner_requests SET company_id=%s WHERE id=%s", (cid, rid))
        conn.execute('UPDATE partner_requests SET status=%s, staff_note=%s, decided_by=%s, decided_at=%s WHERE id=%s',
                     ('approved' if payload.approve else 'rejected', note, staff['id'], _iso(), rid))
    if not payload.approve:
        return {'message': 'Request rejected. The students can see your note.'}
    if created_draft:
        return {'message': 'Approved. A draft partner was created from the suggestion; review and publish it so the '
                           'relationship appears publicly.', 'company_id': created_draft}
    return {'message': 'Approved. The company now shows as an official partner on the project.'}


@router.get('/api/staff/queue')
def staff_queue(staff=Depends(require_staff)):
    """Admin home: work grouped by task, in plain language."""
    with _db() as conn:
        verify = [dict(r) for r in conn.execute(
            '''SELECT v.id, v.created_at, p.id AS project_id, p.title AS project_title, s.name AS requester
               FROM project_verification_requests v JOIN projects p ON p.id=v.project_id
               LEFT JOIN students s ON s.id=v.requested_by WHERE v.status='pending' ORDER BY v.created_at''').fetchall()]
        partner = [dict(r) for r in conn.execute(
            '''SELECT r.id, r.created_at, p.title AS project_title, coalesce(c.name, r.suggested_name) AS company_name,
                      (r.company_id IS NULL) AS is_new_company, s.name AS requester
               FROM partner_requests r JOIN projects p ON p.id=r.project_id LEFT JOIN companies c ON c.id=r.company_id
               LEFT JOIN students s ON s.id=r.requested_by WHERE r.status='pending' ORDER BY r.created_at''').fetchall()]
        drafts = [dict(r) for r in conn.execute(
            "SELECT id, name, domain, updated_at FROM companies WHERE status='draft' ORDER BY updated_at DESC").fetchall()]
        unsaved = [dict(r) for r in conn.execute(
            '''SELECT id, source_url, status, imported_at, candidates FROM company_imports
               WHERE saved=0 AND company_id IS NULL AND imported_at > %s ORDER BY imported_at DESC LIMIT 20''',
            (_iso(_now() - timedelta(days=14)),)).fetchall()]
        known = {r['domain'] for r in conn.execute("SELECT domain FROM companies WHERE domain<>''").fetchall()}
        open_imports = []
        for u in unsaved:
            cand = json.loads(u.pop('candidates') or '{}') or {}
            if cand.get('domain') and cand['domain'] in known:
                continue          # re-import of a partner that already exists: nothing left to review
            u['name'] = cand.get('name') or ''
            open_imports.append(u)
        unsaved = open_imports
        inquiries = conn.execute("SELECT count(*) AS n FROM inquiries WHERE status='new'").fetchone()['n']
    return {'verification_requests': verify, 'partner_requests': partner, 'draft_partners': drafts,
            'unsaved_imports': unsaved, 'new_inquiries': inquiries}


@router.get('/api/staff/inbox')
def staff_inbox(staff=Depends(require_staff)):
    with _db() as conn:
        rows = conn.execute('''SELECT id,created_at,source_type,source_id,source_name,source_url,name,company,email,
                               role_type,message,status FROM inquiries ORDER BY id DESC LIMIT 200''').fetchall()
    return [dict(r) for r in rows]


class InquiryStatus(BaseModel):
    status: str


@router.post('/api/staff/inbox/{iid}')
def staff_inbox_status(iid: int, payload: InquiryStatus, staff=Depends(require_staff)):
    if payload.status not in ('new', 'handled'):
        raise HTTPException(422, 'Status must be new or handled.')
    with _db() as conn:
        conn.execute('UPDATE inquiries SET status=%s WHERE id=%s', (payload.status, iid))
    return {'message': 'Updated.'}


# ====================================================================== public read

def _years(x):
    a, b = x.get('start_year'), x.get('end_year')
    if a and b and a != b:
        return f'{a}–{b}'
    if a and x.get('status') == 'current' and not b:
        return f'{a}–present'
    return str(a or b or '')


def public_collaboration(conn, x):
    """The single place that decides what a collaboration looks like in public.
    Private -> None. Limited -> summary, years and current/past only."""
    if x['visibility'] == 'private':
        return None
    base = {'id': x['id'], 'status': x['status'], 'years': _years(x), 'start_year': x['start_year']}
    if x['visibility'] == 'limited':
        base.update({'kind': 'limited', 'title': 'Confidential collaboration', 'summary': x['public_summary']})
        return base
    projects = [dict(p) for p in conn.execute(
        '''SELECT p.id, p.title FROM collaboration_projects cp JOIN projects p ON p.id=cp.project_id
           WHERE cp.collaboration_id=%s AND p.is_published=1 ORDER BY p.title''', (x['id'],)).fetchall()]
    students = [dict(s) for s in conn.execute(
        '''SELECT s.id, s.name FROM collaboration_students cs JOIN students s ON s.id=cs.student_id
           WHERE cs.collaboration_id=%s AND s.is_published=1 ORDER BY s.name''', (x['id'],)).fetchall()]
    base.update({'kind': 'public', 'title': x['title'], 'description': x['description'], 'outcome': x['outcome'],
                 'projects': projects, 'students': students})
    return base


def _public_company_core(c):
    return {'id': c['id'], 'name': c['name'], 'website': c['website'], 'description': c['description'],
            'sector': c['sector'], 'keywords': _cfg['parsed'](c['keywords']), 'location': c['location'],
            'logo_url': c['logo_url'], 'relationship_summary': c['relationship_summary']}


@router.get('/api/partners')
def public_partners():
    with _db() as conn:
        rows = conn.execute("SELECT * FROM companies WHERE status='published' ORDER BY lower(name)").fetchall()
        out = []
        for c in rows:
            shown = [x for x in conn.execute(
                "SELECT status, start_year, end_year FROM collaborations WHERE company_id=%s AND visibility<>'private'",
                (c['id'],)).fetchall()]
            item = _public_company_core(c)
            item['relationship'] = 'current' if any(x['status'] == 'current' for x in shown) else ('past' if shown else '')
            item['collaboration_count'] = len(shown)
            years = [y for x in shown for y in (x['start_year'], x['end_year']) if y]
            item['since'] = min(years) if years else None
            item['description'] = (item['description'] or '')[:280]
            out.append(item)
    return out


@router.get('/api/partners/{cid}')
def public_partner(cid: str):
    _check_id(cid, 'Partner')
    with _db() as conn:
        c = conn.execute("SELECT * FROM companies WHERE id=%s AND status='published'", (cid,)).fetchone()
        if not c:
            raise HTTPException(404, 'Partner not found')
        collabs = [public_collaboration(conn, x) for x in conn.execute(
            'SELECT * FROM collaborations WHERE company_id=%s ORDER BY coalesce(start_year,0) DESC, title', (cid,)).fetchall()]
        collabs = [x for x in collabs if x]
        approved = [dict(r) for r in conn.execute(
            '''SELECT p.id, p.title FROM project_partners pp JOIN projects p ON p.id=pp.project_id
               WHERE pp.company_id=%s AND p.is_published=1 ORDER BY p.title''', (cid,)).fetchall()]
    out = _public_company_core(c)
    out['current'] = [x for x in collabs if x['status'] == 'current']
    out['past'] = [x for x in collabs if x['status'] == 'past']
    out['relationship'] = 'current' if out['current'] else ('past' if out['past'] else '')
    seen, projects, students = set(), [], []
    for x in collabs:
        for p in x.get('projects', []):
            if p['id'] not in seen:
                seen.add(p['id'])
                projects.append(p)
        for s in x.get('students', []):
            if s['id'] not in {y['id'] for y in students}:
                students.append(s)
    for p in approved:
        if p['id'] not in seen:
            seen.add(p['id'])
            projects.append(p)
    out['related_projects'] = projects
    out['related_students'] = students
    return out


@router.get('/api/projects/{pid}/industry')
def public_project_industry(pid: str):
    """Official verification and approved partners for a public project page."""
    _check_id(pid, 'Project')
    with _db() as conn:
        p = conn.execute('SELECT id, official_verified, verified_at, is_published FROM projects WHERE id=%s', (pid,)).fetchone()
        if not p or not p['is_published']:
            raise HTTPException(404, 'Project not found')
        partners = [dict(r) for r in conn.execute(
            '''SELECT DISTINCT c.id, c.name FROM companies c WHERE c.status='published' AND (
                 c.id IN (SELECT company_id FROM project_partners WHERE project_id=%s) OR
                 c.id IN (SELECT x.company_id FROM collaborations x JOIN collaboration_projects cp ON cp.collaboration_id=x.id
                          WHERE cp.project_id=%s AND x.visibility='public'))
               ORDER BY c.name''', (pid, pid)).fetchall()]
    return {'official_verified': bool(p['official_verified']), 'verified_at': p['verified_at'], 'partners': partners}
