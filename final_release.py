"""ImmXrsive Final Release: production readiness.

Wired into main.py with configure(...) and app.include_router(router).

What lives here (decisions are repeated in RELEASE_NOTES_FINAL.md):

- Legacy migration (F.01-F.06). One importer, `run_import`, is used by the staff
  screen, the command-line tool (scripts/migrate_legacy.py) and the scale fixture.
  Every record keeps its legacy id in a separate `legacy_id` column; the internal
  id is generated once and never derived from a name, email, GitHub handle,
  repository URL or domain. Re-running the same export matches on legacy_id and
  reports created / updated / skipped / conflict counts instead of copying rows.
- Profile claims (F.07-F.10). Imported profiles have no GitHub identity. A
  verified user can ask to own one. Only an exact match between the address the
  user verified (R2.04) and the address the legacy record carried is approved
  automatically; everything else waits for staff. Names, GitHub handles and
  "has some Algoma address" are never used to decide.
- Lifecycle (F.11-F.16). Current/Alumni status, publication
  (published / unpublished / retired) and talent mode (Active Talent / Showcase
  Only) are three separate columns. Availability has a last-confirmed date and
  is treated as stale after 365 days. Nothing here deletes a row.
- Duplicates and recovery (F.17-F.19). Staff merge duplicate students or
  partners; relationships move to the survivor and the old id is kept in
  `record_redirects`, so an old public URL leads to the surviving record. Staff
  can assign a new project maintainer without touching contributor history.
- Diagnostics (F.32). Integration failures and unexpected errors are stored in
  `diagnostic_events` (timestamp, request id, route, status, short detail; never
  tokens, passwords, codes or request bodies) and shown to staff only.
"""
import hashlib
import json
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()
_cfg = {}
log = logging.getLogger('immxrsive')

ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
HTTPS_RE = re.compile(r'^https://[^\s<>"\'`]+$', re.I)
STALE_DAYS = 365
AVAILABILITY = ('internship', 'contract', 'full-time')
PUBLICATION = ('published', 'unpublished', 'retired')
TALENT_MODES = ('active', 'showcase')
DEMO_TYPES = ('link', 'embed', 'webxr')
DEMO_STATES = ('available', 'unavailable', 'archived', 'replaced')


def configure(*, db, require_staff, authenticated, parsed, frontend):
    _cfg.update(db=db, require_staff=require_staff, authenticated=authenticated,
                parsed=parsed, frontend=frontend)


def _db():
    return _cfg['db']()


def _now():
    return datetime.now(timezone.utc)


def _iso(dt=None):
    return (dt or _now()).isoformat()


def _staff(request: Request):
    return _cfg['require_staff'](request)


def _verified_student(request: Request):
    student = _cfg['authenticated'](request)
    if not student['is_algoma_verified']:
        raise HTTPException(403, 'Verify your Algoma email first.')
    return student


def _check_id(value, what='Record'):
    if not ID_RE.match(value or ''):
        raise HTTPException(404, f'{what} not found')
    return value


def _jl(value):
    return _cfg['parsed'](value) if 'parsed' in _cfg else json.loads(value or '[]')


# ====================================================================== schema

def setup_schema(conn):
    """Additive only. Runs after the R1-R4 schema. Backfills are guarded by
    IS NULL so they run once and never overwrite a value someone set."""
    student_cols = {
        'legacy_id': 'TEXT', 'legacy_email': 'TEXT',
        'claim_state': 'TEXT',                 # owned | unclaimed | legacy_claimed | merged
        'publication': 'TEXT',                 # published | unpublished | retired | merged
        'talent_mode': 'TEXT',                 # active | showcase
        'availability_confirmed_at': 'TEXT', 'availability_confirmed_source': "TEXT NOT NULL DEFAULT ''",
        'affiliation_verified_at': 'TEXT', 'merged_into': 'TEXT', 'status_changed_at': 'TEXT',
        'created_source': "TEXT NOT NULL DEFAULT ''",
    }
    for key, spec in student_cols.items():
        conn.execute(f'ALTER TABLE students ADD COLUMN IF NOT EXISTS {key} {spec}')
    for key, spec in {'legacy_id': 'TEXT', 'demo_type': "TEXT NOT NULL DEFAULT 'link'",
                      'demo_state': "TEXT NOT NULL DEFAULT 'available'", 'demo_note': "TEXT NOT NULL DEFAULT ''",
                      'demo_replacement_url': "TEXT NOT NULL DEFAULT ''"}.items():
        conn.execute(f'ALTER TABLE projects ADD COLUMN IF NOT EXISTS {key} {spec}')
    for key in ('legacy_id', 'merged_into'):
        conn.execute(f'ALTER TABLE companies ADD COLUMN IF NOT EXISTS {key} TEXT')
    conn.execute('ALTER TABLE collaborations ADD COLUMN IF NOT EXISTS legacy_id TEXT')
    for table in ('students', 'projects', 'companies', 'collaborations'):
        conn.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS {table}_legacy_unique ON {table}(legacy_id) WHERE legacy_id IS NOT NULL')

    conn.execute('''CREATE TABLE IF NOT EXISTS migration_runs(
        id TEXT PRIMARY KEY, started_at TEXT NOT NULL, run_by TEXT, source_name TEXT NOT NULL DEFAULT '',
        source_sha256 TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL, counts TEXT NOT NULL DEFAULT '{}',
        report TEXT NOT NULL DEFAULT '{}')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS duplicate_candidates(
        id SERIAL PRIMARY KEY, entity TEXT NOT NULL, record_id TEXT NOT NULL, other_id TEXT NOT NULL,
        reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL,
        resolved_by TEXT, resolved_at TEXT, UNIQUE(entity, record_id, other_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS profile_claims(
        id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, claimant_id TEXT NOT NULL, status TEXT NOT NULL,
        match_reason TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', staff_note TEXT NOT NULL DEFAULT '',
        decided_by TEXT, decided_at TEXT, created_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS record_redirects(
        entity TEXT NOT NULL, old_id TEXT NOT NULL, new_id TEXT NOT NULL, reason TEXT NOT NULL,
        created_by TEXT, created_at TEXT NOT NULL, PRIMARY KEY(entity, old_id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS profile_events(
        id SERIAL PRIMARY KEY, profile_id TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
        actor TEXT, at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS maintainer_history(
        id SERIAL PRIMARY KEY, project_id TEXT NOT NULL, from_id TEXT, to_id TEXT NOT NULL,
        actor TEXT, note TEXT NOT NULL DEFAULT '', at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS diagnostic_events(
        id SERIAL PRIMARY KEY, at TEXT NOT NULL, level TEXT NOT NULL, kind TEXT NOT NULL,
        request_id TEXT NOT NULL DEFAULT '', route TEXT NOT NULL DEFAULT '', status INTEGER,
        detail TEXT NOT NULL DEFAULT '')''')
    conn.execute('CREATE INDEX IF NOT EXISTS diagnostic_events_at ON diagnostic_events(at)')

    # ---- one-time backfills for rows that existed before the Final release
    conn.execute('''UPDATE students SET publication = CASE WHEN is_published=1 THEN 'published' ELSE 'unpublished' END
                    WHERE publication IS NULL''')
    conn.execute("UPDATE students SET claim_state = CASE WHEN github_id IS NOT NULL THEN 'owned' ELSE 'unclaimed' END "
                 "WHERE claim_state IS NULL")
    conn.execute('''UPDATE students SET talent_mode = CASE WHEN coalesce(availability,'[]') IN ('[]','') THEN 'showcase'
                    ELSE 'active' END WHERE talent_mode IS NULL''')
    # Availability that R1-R4 profiles set during this term (Sept-Nov 2026) is
    # recorded as confirmed when this release went live; stated in the launch notes.
    conn.execute('''UPDATE students SET availability_confirmed_at=%s,
                    availability_confirmed_source='existing profile at Final release'
                    WHERE availability_confirmed_at IS NULL AND legacy_id IS NULL
                      AND coalesce(availability,'[]') NOT IN ('[]','')''', (date.today().isoformat(),))
    conn.execute('UPDATE students SET affiliation_verified_at=%s WHERE is_algoma_verified=1 AND affiliation_verified_at IS NULL',
                 (_iso(),))


# ====================================================================== diagnostics (F.32)

SECRETISH = re.compile(r'(bearer\s+\S+|token=\S+|code=\S+|password\S*|stf_\S+|postgres(ql)?://\S+)', re.I)


def record_event(kind, detail='', *, level='error', request_id='', route='', status=None):
    """Store a short, non-sensitive diagnostic record. Never raises."""
    text = SECRETISH.sub('[redacted]', str(detail or ''))[:500]
    log.log(logging.ERROR if level == 'error' else logging.WARNING,
            'event kind=%s status=%s route=%s request_id=%s detail=%s', kind, status, route, request_id, text)
    try:
        with _db() as conn:
            conn.execute('''INSERT INTO diagnostic_events(at,level,kind,request_id,route,status,detail)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)''', (_iso(), level, kind, request_id, route, status, text))
    except Exception:  # diagnostics must never break the request that failed
        log.exception('could not store diagnostic event')


INTEGRATION_ROUTES = [
    ('/api/github/repo', 'github_import'),
    ('/api/request-verification', 'email_delivery'),
    ('/api/verify-code', 'email_verification'),
    ('/api/staff/company-imports', 'company_import'),
    ('/api/auth/callback', 'github_sign_in'),
    ('/api/staff/migrations', 'legacy_migration'),
]


def integration_kind(path):
    for prefix, kind in INTEGRATION_ROUTES:
        if path.startswith(prefix):
            return kind
    return ''


@router.get('/api/staff/diagnostics')
def diagnostics(limit: int = 100, kind: str = '', staff=Depends(_staff)):
    import os
    limit = max(1, min(limit, 300))
    with _db() as conn:
        rows = conn.execute('''SELECT id, at, level, kind, request_id, route, status, detail FROM diagnostic_events
                               WHERE (%s = '' OR kind = %s) ORDER BY id DESC LIMIT %s''', (kind, kind, limit)).fetchall()
        since = _iso(_now() - timedelta(days=7))
        counts = conn.execute('''SELECT kind, count(*) AS n, max(at) AS last FROM diagnostic_events WHERE at > %s
                                 GROUP BY kind ORDER BY n DESC''', (since,)).fetchall()
        runs = conn.execute('SELECT id, started_at, mode, source_name, counts FROM migration_runs ORDER BY started_at DESC LIMIT 5').fetchall()
    configured = {  # presence only, never values
        'database': True,
        'github_oauth': bool(os.environ.get('GITHUB_CLIENT_ID') and os.environ.get('GITHUB_CLIENT_SECRET')),
        'verification_email': all(os.environ.get(k) for k in ('GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN', 'GMAIL_SENDER_EMAIL')),
        'github_api_token': bool(os.environ.get('GITHUB_API_TOKEN')),
    }
    return {'events': [dict(r) for r in rows], 'last_7_days': [dict(r) for r in counts],
            'configured': configured,
            'recent_migrations': [{**dict(r), 'counts': json.loads(r['counts'] or '{}')} for r in runs]}


# ====================================================================== availability / lifecycle view

def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def talent_view(row, today=None):
    """The one place that decides how availability is presented (F.13, F.14).

    talent_state:
      active      Active Talent, availability confirmed in the last 365 days
      stale       Active Talent, but confirmation is older than 365 days
      unconfirmed Active Talent with no confirmation date
      showcase    Showcase Only (portfolio visible, not seeking opportunities)
    Only `active` profiles present availability as current."""
    today = today or date.today()
    avail = [a for a in _jl(row.get('availability')) if isinstance(a, str)]
    mode = row.get('talent_mode') or ('active' if avail else 'showcase')
    confirmed = _date(row.get('availability_confirmed_at'))
    if mode == 'showcase' or not avail:
        state = 'showcase'
    elif not confirmed:
        state = 'unconfirmed'
    elif (today - confirmed).days > STALE_DAYS:
        state = 'stale'
    else:
        state = 'active'
    return {'talent_mode': mode, 'talent_state': state,
            'availability_confirmed_at': confirmed.isoformat() if confirmed else None,
            'current_availability': avail if state == 'active' else [],
            'stated_availability': avail}


def _event(conn, profile_id, action, detail='', actor=None):
    conn.execute('INSERT INTO profile_events(profile_id,action,detail,actor,at) VALUES (%s,%s,%s,%s,%s)',
                 (profile_id, action, str(detail)[:500], actor, _iso()))


def set_publication(conn, sid, publication, actor):
    if publication not in PUBLICATION:
        raise HTTPException(422, 'Choose published, unpublished or retired.')
    conn.execute('UPDATE students SET publication=%s, is_published=%s WHERE id=%s AND merged_into IS NULL',
                 (publication, 1 if publication == 'published' else 0, sid))
    _event(conn, sid, 'publication', publication, actor)


# ---- student self-service

class TalentIn(BaseModel):
    mode: str


@router.put('/api/profile/talent')
def set_talent_mode(payload: TalentIn, student=Depends(_verified_student)):
    if payload.mode not in TALENT_MODES:
        raise HTTPException(422, 'Choose Active Talent or Showcase Only.')
    with _db() as conn:
        conn.execute('UPDATE students SET talent_mode=%s WHERE id=%s', (payload.mode, student['id']))
        if payload.mode == 'active':
            conn.execute("UPDATE students SET availability_confirmed_at=%s, availability_confirmed_source='student' WHERE id=%s",
                         (date.today().isoformat(), student['id']))
        _event(conn, student['id'], 'talent_mode', payload.mode, student['id'])
    return {'message': 'Active Talent: employers see you as open to opportunities.' if payload.mode == 'active'
            else 'Showcase Only: your portfolio stays public but you are not shown as job-seeking.'}


@router.post('/api/profile/availability/confirm')
def confirm_availability(student=Depends(_verified_student)):
    with _db() as conn:
        conn.execute("UPDATE students SET availability_confirmed_at=%s, availability_confirmed_source='student' WHERE id=%s",
                     (date.today().isoformat(), student['id']))
        _event(conn, student['id'], 'availability_confirmed', '', student['id'])
    return {'message': 'Availability confirmed today.', 'confirmed_at': date.today().isoformat()}


@router.post('/api/profile/retire')
def retire_own_profile(student=Depends(_verified_student)):
    with _db() as conn:
        set_publication(conn, student['id'], 'retired', student['id'])
    return {'message': 'Portfolio retired. It is no longer listed. Shared projects and collaborations keep your '
                       'contribution. Publish again at any time; nothing was deleted.'}


@router.get('/api/profile/lifecycle')
def own_lifecycle(student=Depends(_verified_student)):
    return {**talent_view(student), 'publication': student.get('publication'), 'status': student.get('status'),
            'affiliation_verified': bool(student['is_algoma_verified']),
            'affiliation_verified_at': student.get('affiliation_verified_at'),
            'claim_state': student.get('claim_state')}


# ---- staff lifecycle tools (Scenario B)

class LifecycleIn(BaseModel):
    status: str | None = None                      # Current | Alumni
    publication: str | None = None
    talent_mode: str | None = None
    availability_confirmed_at: str | None = None   # YYYY-MM-DD, staff test/data-correction tool
    availability: list[str] | None = None
    note: str = Field(default='', max_length=500)


@router.post('/api/staff/students/{sid}/lifecycle')
def staff_lifecycle(sid: str, payload: LifecycleIn, staff=Depends(_staff)):
    _check_id(sid, 'Student')
    with _db() as conn:
        row = conn.execute('SELECT * FROM students WHERE id=%s', (sid,)).fetchone()
        if not row:
            raise HTTPException(404, 'Student not found')
        if row['merged_into']:
            raise HTTPException(409, 'This record was merged. Change the surviving record instead.')
        changes = []
        if payload.status is not None:
            status = payload.status.strip().capitalize()
            if status not in ('Current', 'Alumni'):
                raise HTTPException(422, 'Status must be Current or Alumni.')
            # Affiliation verification is deliberately untouched (F.12).
            conn.execute('UPDATE students SET status=%s, status_changed_at=%s WHERE id=%s', (status, _iso(), sid))
            changes.append('status=' + status)
        if payload.publication is not None:
            set_publication(conn, sid, payload.publication, staff['id'])
            changes.append('publication=' + payload.publication)
        if payload.talent_mode is not None:
            if payload.talent_mode not in TALENT_MODES:
                raise HTTPException(422, 'Talent mode must be active or showcase.')
            conn.execute('UPDATE students SET talent_mode=%s WHERE id=%s', (payload.talent_mode, sid))
            changes.append('talent_mode=' + payload.talent_mode)
        if payload.availability is not None:
            bad = [a for a in payload.availability if a not in AVAILABILITY]
            if bad:
                raise HTTPException(422, 'Availability must be internship, contract or full-time.')
            conn.execute('UPDATE students SET availability=%s WHERE id=%s', (json.dumps(payload.availability), sid))
            changes.append('availability=' + ','.join(payload.availability))
        if payload.availability_confirmed_at is not None:
            d = _date(payload.availability_confirmed_at)
            if payload.availability_confirmed_at and not d:
                raise HTTPException(422, 'Use a date like 2025-06-01.')
            conn.execute("UPDATE students SET availability_confirmed_at=%s, availability_confirmed_source='staff' WHERE id=%s",
                         (d.isoformat() if d else None, sid))
            changes.append('availability_confirmed_at=' + (d.isoformat() if d else 'cleared'))
        if not changes:
            raise HTTPException(422, 'Nothing to change.')
        _event(conn, sid, 'staff_lifecycle', '; '.join(changes) + (f' ({payload.note})' if payload.note else ''), staff['id'])
    return {'message': 'Saved: ' + ', '.join(changes) + '.'}


# ====================================================================== redirects / public continuity (F.18)

def resolve_redirect(conn, entity, old_id, depth=0):
    row = conn.execute('SELECT new_id, reason FROM record_redirects WHERE entity=%s AND old_id=%s',
                       (entity, old_id)).fetchone()
    if not row or depth > 5:
        return None
    nxt = resolve_redirect(conn, entity, row['new_id'], depth + 1)
    return nxt or {'to': row['new_id'], 'reason': row['reason']}


def _add_redirect(conn, entity, old_id, new_id, reason, actor):
    conn.execute('''INSERT INTO record_redirects(entity,old_id,new_id,reason,created_by,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (entity, old_id) DO UPDATE SET new_id=excluded.new_id,
                    reason=excluded.reason''', (entity, old_id, new_id, reason, actor, _iso()))
    conn.execute('UPDATE record_redirects SET new_id=%s WHERE entity=%s AND new_id=%s', (new_id, entity, old_id))


def moved_student(conn, sid):
    """Public answer for a student id that is not a published profile, or None."""
    r = resolve_redirect(conn, 'student', sid)
    if r:
        target = conn.execute('SELECT id, name, is_published FROM students WHERE id=%s', (r['to'],)).fetchone()
        if target and target['is_published']:
            return {'id': sid, 'moved': True, 'moved_to': target['id'], 'name': target['name'],
                    'reason': r['reason'],
                    'message': f"This profile was combined with {target['name']}'s profile. You are being taken there."}
    return None


def retired_student(conn, row):
    projects = [dict(p) for p in conn.execute(
        '''SELECT p.id, p.title, c.role FROM project_contributors c JOIN projects p ON p.id=c.project_id
           WHERE c.student_id=%s AND c.status='accepted' AND p.is_published=1 ORDER BY p.title''', (row['id'],)).fetchall()]
    return {'id': row['id'], 'name': row['name'], 'retired': True, 'publication': 'retired', 'status': row['status'],
            'projects': projects,
            'message': 'This portfolio has been retired by its owner or ImmXrsive staff. Shared project history is kept.'}


def moved_partner(conn, cid):
    r = resolve_redirect(conn, 'partner', cid)
    if r:
        target = conn.execute("SELECT id, name FROM companies WHERE id=%s AND status='published'", (r['to'],)).fetchone()
        if target:
            return {'id': cid, 'moved': True, 'moved_to': target['id'], 'name': target['name'], 'reason': r['reason'],
                    'message': f"This partner record was combined with {target['name']}. You are being taken there."}
    return None


# ====================================================================== legacy migration (F.01-F.06, F.27)

class MigrationIn(BaseModel):
    source_name: str = Field(default='legacy_export.json', max_length=200)
    data: dict
    dry_run: bool = False
    expected: dict | None = None


def _norm_domain(domain):
    d = (domain or '').strip().lower()
    d = re.sub(r'^https?://', '', d).split('/')[0]
    return d[4:] if d.startswith('www.') else d


def _norm_status(v):
    v = str(v or '').strip().lower()
    return {'current': 'Current', 'alumni': 'Alumni'}.get(v)


def _detect_format(data):
    students = data.get('students') or []
    if students and isinstance(students[0], dict) and 'legacy_id' in students[0]:
        return 'legacy'
    return 'records'          # scale_fixture.json shape: id / skills / technologies / demo_url


def _normalized(data):
    """Map both supplied shapes onto one record form. Returns (records, malformed)."""
    fmt = _detect_format(data)
    out = {'students': [], 'projects': [], 'companies': [], 'collaborations': []}
    malformed = []
    key = 'legacy_id' if fmt == 'legacy' else 'id'

    def bad(entity, item, reason):
        malformed.append({'entity': entity, 'legacy_id': str((item or {}).get(key) or (item or {}).get('legacy_id') or '?'),
                          'reason': reason})

    for s in data.get('students') or []:
        if not isinstance(s, dict) or not ID_RE.match(str(s.get(key) or '')):
            bad('student', s if isinstance(s, dict) else {}, 'missing or invalid id'); continue
        name = re.sub(r'\s+', ' ', str(s.get('name') or '')).strip()[:120]
        status = _norm_status(s.get('status'))
        pub = str(s.get('publication') or 'published').strip().lower()
        raw_av = s.get('availability')
        avail = raw_av if isinstance(raw_av, list) else ([raw_av] if raw_av else [])
        avail = [str(a).strip().lower() for a in avail]
        if not name:
            bad('student', s, 'missing name'); continue
        if not status:
            bad('student', s, f"unknown status {s.get('status')!r}"); continue
        if pub not in PUBLICATION:
            bad('student', s, f'unknown publication {pub!r}'); continue
        if any(a not in AVAILABILITY for a in avail):
            bad('student', s, f'unknown availability {avail!r}'); continue
        confirmed = s.get('availability_confirmed')
        if confirmed and not _date(confirmed):
            bad('student', s, f'invalid availability_confirmed {confirmed!r}'); continue
        email = str(s.get('email') or '').strip().lower() or None
        out['students'].append({
            'legacy_id': str(s[key]), 'name': name, 'email': email, 'status': status, 'publication': pub,
            'availability': avail, 'confirmed': _date(confirmed).isoformat() if confirmed else None,
            'claimed': bool(s.get('claimed')), 'possible_duplicate_of': s.get('possible_duplicate_of'),
            'skills': [str(x)[:40] for x in (s.get('skills') or []) if str(x).strip()][:30],
        })
    for p in data.get('projects') or []:
        if not isinstance(p, dict) or not ID_RE.match(str(p.get(key) or '')) or not str(p.get('title') or '').strip():
            bad('project', p if isinstance(p, dict) else {}, 'missing id or title'); continue
        repo = p.get('repository') or ''
        demo = p.get('demo_url') or ''
        out['projects'].append({
            'legacy_id': str(p[key]), 'title': str(p['title']).strip()[:150],
            'contributors': [{'student': str(c.get('student_legacy_id') or c.get('student_id') or ''),
                              'role': str(c.get('role') or 'Contributor').strip()[:80]}
                             for c in (p.get('contributors') or []) if isinstance(c, dict)],
            'repository': repo if HTTPS_RE.match(repo) else '',
            'bad_repository': bool(repo) and not HTTPS_RE.match(repo),
            'technologies': [str(t)[:40] for t in (p.get('technologies') or [])][:30],
            'demo_url': demo if HTTPS_RE.match(demo) else '',
        })
    for c in data.get('companies') or []:
        if not isinstance(c, dict) or not ID_RE.match(str(c.get(key) or '')) or not str(c.get('name') or '').strip():
            bad('company', c if isinstance(c, dict) else {}, 'missing id or name'); continue
        out['companies'].append({'legacy_id': str(c[key]), 'name': str(c['name']).strip()[:150],
                                 'domain': _norm_domain(c.get('domain')),
                                 'possible_duplicate_of': c.get('possible_duplicate_of')})
    for x in data.get('collaborations') or []:
        if not isinstance(x, dict) or not ID_RE.match(str(x.get(key) or '')) or not str(x.get('title') or '').strip():
            bad('collaboration', x if isinstance(x, dict) else {}, 'missing id or title'); continue
        status = str(x.get('status') or '').lower()
        vis = str(x.get('visibility') or 'private').lower()
        if status not in ('current', 'past') or vis not in ('public', 'limited', 'private'):
            bad('collaboration', x, f'unknown status/visibility {status!r}/{vis!r}'); continue
        out['collaborations'].append({'legacy_id': str(x[key]), 'company': str(x.get('company_legacy_id') or x.get('company_id') or ''),
                                      'title': str(x['title']).strip()[:150], 'status': status, 'visibility': vis,
                                      'projects': [str(i) for i in (x.get('project_legacy_ids') or x.get('project_ids') or [])]})
    return fmt, out, malformed


def _counter():
    return {'created': 0, 'updated': 0, 'skipped': 0, 'conflict': 0}


def _flag_duplicate(conn, entity, record_id, other_id, reason):
    conn.execute('''INSERT INTO duplicate_candidates(entity,record_id,other_id,reason,created_at)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT (entity,record_id,other_id) DO NOTHING''',
                 (entity, record_id, other_id, reason, _iso()))


def _final_student(conn, internal_id):
    """Follow merges so relationships land on the surviving record."""
    seen = 0
    while internal_id and seen < 6:
        row = conn.execute('SELECT merged_into FROM students WHERE id=%s', (internal_id,)).fetchone()
        if not row or not row['merged_into']:
            return internal_id
        internal_id, seen = row['merged_into'], seen + 1
    return internal_id


def _final_company(conn, internal_id):
    seen = 0
    while internal_id and seen < 6:
        row = conn.execute('SELECT merged_into FROM companies WHERE id=%s', (internal_id,)).fetchone()
        if not row or not row['merged_into']:
            return internal_id
        internal_id, seen = row['merged_into'], seen + 1
    return internal_id


def run_import(conn, data, *, source_name='legacy_export.json', run_by='cli', dry_run=False, expected=None):
    """The repeatable migration. Same code for staff screen, CLI and scale fixture."""
    raw = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
    fmt, rec, malformed = _normalized(data)
    counts = {k: _counter() for k in ('students', 'projects', 'companies', 'collaborations', 'contributors')}
    details, duplicates, broken, notes = [], [], [], []
    source_counts = {k: len(data.get(k) or []) for k in ('students', 'projects', 'companies', 'collaborations')}
    for m in malformed:
        counts[{'student': 'students', 'project': 'projects', 'company': 'companies',
                'collaboration': 'collaborations'}[m['entity']]]['conflict'] += 1
    stamp = _iso()
    source_label = 'legacy migration' if fmt == 'legacy' else 'scale fixture import'

    def note(entity, legacy_id, internal_id, action, text=''):
        details.append({'entity': entity, 'legacy_id': legacy_id, 'internal_id': internal_id, 'action': action, 'note': text})

    # ------------------------------------------------ students
    smap = {}
    by_email = {}
    for s in rec['students']:
        if s['email']:
            by_email.setdefault(s['email'], []).append(s['legacy_id'])
    for s in rec['students']:
        row = conn.execute('SELECT * FROM students WHERE legacy_id=%s', (s['legacy_id'],)).fetchone()
        dup_of, reason = None, ''
        if s['email'] and len(by_email.get(s['email'], [])) > 1 and by_email[s['email']][0] != s['legacy_id']:
            dup_of, reason = by_email[s['email']][0], 'same email'
        elif s['possible_duplicate_of']:
            dup_of, reason = str(s['possible_duplicate_of']), 'flagged in legacy export'
        if dup_of:
            duplicates.append({'entity': 'student', 'legacy_id': s['legacy_id'], 'possible_duplicate_of': dup_of, 'reason': reason})
        avail_json = json.dumps(s['availability'])
        mode = 'active' if s['availability'] else 'showcase'
        claim_state = 'legacy_claimed' if s['claimed'] else 'unclaimed'
        if row:
            if row['merged_into']:
                counts['students']['skipped'] += 1
                smap[s['legacy_id']] = _final_student(conn, row['id'])
                note('student', s['legacy_id'], row['id'], 'skipped', f"already merged into {row['merged_into']}; not recreated")
                continue
            smap[s['legacy_id']] = row['id']
            if row['github_id']:
                counts['students']['skipped'] += 1
                note('student', s['legacy_id'], row['id'], 'skipped', 'profile is now owned by its student; legacy values are not re-applied')
                continue
            want = {'name': s['name'], 'status': s['status'], 'legacy_email': s['email'], 'availability': avail_json,
                    'availability_confirmed_at': s['confirmed']}
            have = {k: row[k] for k in want}
            if have == want:
                counts['students']['skipped'] += 1
                note('student', s['legacy_id'], row['id'], 'skipped', 'unchanged')
            else:
                conn.execute('''UPDATE students SET name=%s,status=%s,legacy_email=%s,availability=%s,
                                availability_confirmed_at=%s WHERE id=%s''',
                             (s['name'], s['status'], s['email'], avail_json, s['confirmed'], row['id']))
                counts['students']['updated'] += 1
                note('student', s['legacy_id'], row['id'], 'updated', ', '.join(k for k in want if have[k] != want[k]))
            continue
        sid = 's_' + secrets.token_hex(6)
        conn.execute('''INSERT INTO students (id,name,headline,program,status,availability,skills,github_link,project_ids,
                        is_published,is_algoma_verified,legacy_id,legacy_email,claim_state,publication,talent_mode,
                        availability_confirmed_at,availability_confirmed_source,created_source,show_availability,show_links)
                        VALUES (%s,%s,'','',%s,%s,%s,'','[]',%s,0,%s,%s,%s,%s,%s,%s,%s,%s,1,1)''',
                     (sid, s['name'], s['status'], avail_json, json.dumps(s['skills']),
                      1 if s['publication'] == 'published' else 0, s['legacy_id'], s['email'], claim_state,
                      s['publication'], mode, s['confirmed'], 'legacy export' if s['confirmed'] else '', source_label))
        smap[s['legacy_id']] = sid
        counts['students']['created'] += 1
        note('student', s['legacy_id'], sid, 'created', claim_state)
    for d in duplicates:
        a, b = smap.get(d['legacy_id']), smap.get(d['possible_duplicate_of'])
        if a and b and a != b:
            _flag_duplicate(conn, 'student', a, b, d['reason'])
    # Same display name as a profile that was already on the platform (not from this
    # export): reported for staff review only. A name is never an identity key (F.06).
    existing_matches = []
    for s in rec['students']:
        mine = smap.get(s['legacy_id'])
        for other in conn.execute('''SELECT id, name FROM students WHERE lower(name)=lower(%s) AND id<>%s
                                     AND legacy_id IS NULL AND merged_into IS NULL''', (s['name'], mine or '')).fetchall():
            existing_matches.append({'entity': 'student', 'legacy_id': s['legacy_id'], 'existing_id': other['id'],
                                     'reason': 'same name as an existing profile; not merged automatically'})
            if mine:
                _flag_duplicate(conn, 'student', mine, other['id'], 'same name as an existing profile')
    dup_ids = {d['legacy_id'] for d in duplicates}
    unclaimed = [s['legacy_id'] for s in rec['students'] if not s['claimed'] and s['legacy_id'] not in dup_ids]

    # ------------------------------------------------ projects + contributors
    pmap = {}
    for p in rec['projects']:
        row = conn.execute('SELECT * FROM projects WHERE legacy_id=%s', (p['legacy_id'],)).fetchone()
        if p['bad_repository']:
            malformed.append({'entity': 'project', 'legacy_id': p['legacy_id'], 'reason': 'repository is not an https:// link; left blank'})
        if not row and p['repository']:
            from projects_r3 import normalize_repo
            hit = conn.execute('''SELECT p.* FROM project_repos r JOIN projects p ON p.id=r.project_id
                                  WHERE r.norm=%s AND p.legacy_id IS NULL LIMIT 1''', (normalize_repo(p['repository']),)).fetchone()
            if hit:
                conn.execute('UPDATE projects SET legacy_id=%s WHERE id=%s', (p['legacy_id'], hit['id']))
                row = hit
                counts['projects']['updated'] += 1
                note('project', p['legacy_id'], hit['id'], 'updated', 'matched an existing project by repository; legacy id linked')
                pmap[p['legacy_id']] = hit['id']
        if row and p['legacy_id'] not in pmap:
            pmap[p['legacy_id']] = row['id']
            if row['title'] != p['title']:
                conn.execute('UPDATE projects SET title=%s, updated_at=%s, version=version+1 WHERE id=%s',
                             (p['title'], stamp, row['id']))
                counts['projects']['updated'] += 1
                note('project', p['legacy_id'], row['id'], 'updated', 'title')
            else:
                counts['projects']['skipped'] += 1
                note('project', p['legacy_id'], row['id'], 'skipped', 'unchanged')
        elif not row:
            pid = 'p_' + secrets.token_hex(8)
            conn.execute('''INSERT INTO projects (id,title,description,domain,technologies,status,project_date,maintainer_id,
                            version,is_published,playable_url,video_url,fallback_url,fallback_text,created_at,updated_at,
                            updated_by,legacy_id,demo_type) VALUES (%s,%s,'','',%s,'','',NULL,1,1,%s,'','','',%s,%s,%s,%s,'link')''',
                         (pid, p['title'], json.dumps(p['technologies']), p['demo_url'], stamp, stamp, 'migration', p['legacy_id']))
            if p['repository']:
                from projects_r3 import normalize_repo
                conn.execute('INSERT INTO project_repos(project_id,url,norm) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                             (pid, p['repository'], normalize_repo(p['repository'])))
            pmap[p['legacy_id']] = pid
            counts['projects']['created'] += 1
            note('project', p['legacy_id'], pid, 'created', f"{len(p['contributors'])} legacy contributor(s)")
        pid = pmap[p['legacy_id']]
        for c in p['contributors']:
            sid = smap.get(c['student'])
            if not sid:
                found = conn.execute('SELECT id FROM students WHERE legacy_id=%s', (c['student'],)).fetchone()
                sid = _final_student(conn, found['id']) if found else None
            if not sid:
                broken.append({'project_legacy_id': p['legacy_id'], 'student_legacy_id': c['student'],
                               'reason': 'contributor does not exist in the export or the platform; relationship not created'})
                counts['contributors']['conflict'] += 1
                continue
            sid = _final_student(conn, sid)
            exists = conn.execute('SELECT 1 FROM project_contributors WHERE project_id=%s AND student_id=%s', (pid, sid)).fetchone()
            if exists:
                counts['contributors']['skipped'] += 1
                continue
            conn.execute('''INSERT INTO project_contributors (project_id,student_id,role,status,statement,featured,updated_at)
                            VALUES (%s,%s,%s,'accepted','',1,%s)''', (pid, sid, c['role'], stamp))
            counts['contributors']['created'] += 1

    for p in rec['projects']:
        mine = pmap.get(p['legacy_id'])
        for other in conn.execute('''SELECT id FROM projects WHERE lower(title)=lower(%s) AND id<>%s AND legacy_id IS NULL''',
                                  (p['title'], mine or '')).fetchall():
            existing_matches.append({'entity': 'project', 'legacy_id': p['legacy_id'], 'existing_id': other['id'],
                                     'reason': 'same title as an existing project; review, not merged automatically'})

    # ------------------------------------------------ companies
    cmap = {}
    from industry_r4 import domain_of
    for c in rec['companies']:
        row = conn.execute('SELECT * FROM companies WHERE legacy_id=%s', (c['legacy_id'],)).fetchone()
        website = ('https://' + c['domain']) if c['domain'] else ''
        dom = domain_of(website) if website else ''
        if row:
            cmap[c['legacy_id']] = _final_company(conn, row['id'])
            counts['companies']['skipped'] += 1
            note('company', c['legacy_id'], row['id'], 'skipped', 'already migrated' + (' (merged)' if row['merged_into'] else ''))
            continue
        same = conn.execute("SELECT * FROM companies WHERE domain=%s AND domain<>'' AND merged_into IS NULL ORDER BY created_at",
                            (dom,)).fetchall() if dom else []
        unlinked = [r for r in same if not r['legacy_id']]
        if unlinked:
            target = unlinked[0]
            conn.execute('UPDATE companies SET legacy_id=%s WHERE id=%s', (c['legacy_id'], target['id']))
            cmap[c['legacy_id']] = target['id']
            counts['companies']['updated'] += 1
            note('company', c['legacy_id'], target['id'], 'updated', f'matched existing partner by website domain {dom}; legacy id linked, staff fields kept')
            continue
        cid = 'c_' + secrets.token_hex(6)
        is_dup = bool(same) or bool(c['possible_duplicate_of'])
        publish = fmt == 'legacy' and not is_dup   # legacy partners were public on the old site
        conn.execute('''INSERT INTO companies (id,name,website,domain,description,sector,keywords,location,logo_url,
                        relationship_summary,status,version,created_at,updated_at,created_by,updated_by,legacy_id,published_at)
                        VALUES (%s,%s,%s,%s,'','','[]','','','',%s,1,%s,%s,'migration','migration',%s,%s)''',
                     (cid, c['name'], website, dom, 'published' if publish else 'draft', stamp, stamp, c['legacy_id'],
                      stamp if publish else None))
        for field, value in (('name', c['name']), ('website', website)):
            if value:
                conn.execute('''INSERT INTO company_field_history (company_id,field,value,origin,source_url,recorded_by,recorded_at)
                                VALUES (%s,%s,%s,'legacy migration','',%s,%s)''', (cid, field, value, run_by, stamp))
        cmap[c['legacy_id']] = cid
        counts['companies']['created'] += 1
        note('company', c['legacy_id'], cid, 'created', 'held as draft: possible duplicate' if is_dup else
             ('published (was on the legacy public site)' if publish else 'draft (scale data; staff publish after review)'))
        if is_dup:
            other = (same[0]['id'] if same else None) or cmap.get(str(c['possible_duplicate_of']))
            reason = 'same website domain' if same else 'flagged in legacy export'
            duplicates.append({'entity': 'company', 'legacy_id': c['legacy_id'],
                               'possible_duplicate_of': str(c['possible_duplicate_of'] or (same[0]['legacy_id'] if same else '')),
                               'reason': reason})
            if other:
                _flag_duplicate(conn, 'company', cid, other, reason)

    # ------------------------------------------------ collaborations
    for x in rec['collaborations']:
        cid = cmap.get(x['company'])
        if not cid:
            found = conn.execute('SELECT id FROM companies WHERE legacy_id=%s', (x['company'],)).fetchone()
            cid = _final_company(conn, found['id']) if found else None
        if not cid:
            broken.append({'collaboration_legacy_id': x['legacy_id'], 'company_legacy_id': x['company'],
                           'reason': 'company does not exist; collaboration not created'})
            counts['collaborations']['conflict'] += 1
            continue
        row = conn.execute('SELECT * FROM collaborations WHERE legacy_id=%s', (x['legacy_id'],)).fetchone()
        if row:
            xid = row['id']
            if (row['status'], row['visibility'], row['title']) != (x['status'], x['visibility'], x['title']):
                conn.execute('UPDATE collaborations SET status=%s, visibility=%s, title=%s, updated_at=%s WHERE id=%s',
                             (x['status'], x['visibility'], x['title'], stamp, xid))
                counts['collaborations']['updated'] += 1
                note('collaboration', x['legacy_id'], xid, 'updated', 'status/visibility/title')
            else:
                counts['collaborations']['skipped'] += 1
                note('collaboration', x['legacy_id'], xid, 'skipped', 'unchanged')
        else:
            xid = 'col_' + secrets.token_hex(6)
            summary = 'A confidential collaboration with an industry partner.' if x['visibility'] == 'limited' else ''
            conn.execute('''INSERT INTO collaborations (id,company_id,title,start_year,end_year,description,outcome,status,
                            visibility,public_summary,created_at,updated_at,created_by,updated_by,legacy_id)
                            VALUES (%s,%s,%s,NULL,NULL,'','',%s,%s,%s,%s,%s,'migration','migration',%s)''',
                         (xid, cid, x['title'], x['status'], x['visibility'], summary, stamp, stamp, x['legacy_id']))
            counts['collaborations']['created'] += 1
            note('collaboration', x['legacy_id'], xid, 'created', f"{x['status']}, {x['visibility']}")
        for lp in x['projects']:
            pid = pmap.get(lp)
            if not pid:
                found = conn.execute('SELECT id FROM projects WHERE legacy_id=%s', (lp,)).fetchone()
                pid = found['id'] if found else None
            if not pid:
                broken.append({'collaboration_legacy_id': x['legacy_id'], 'project_legacy_id': lp,
                               'reason': 'project does not exist; link not created'})
                continue
            conn.execute('INSERT INTO collaboration_projects VALUES (%s,%s) ON CONFLICT DO NOTHING', (xid, pid))

    if fmt == 'legacy':
        notes.append('Imported profiles have no account. Their owners can claim them after verifying their email.')
    totals = {k: v for k, v in counts.items()}
    report = {'format': fmt, 'mode': 'dry_run' if dry_run else 'apply', 'source_name': source_name,
              'source_sha256': hashlib.sha256(raw).hexdigest(), 'source_counts': source_counts, 'results': totals,
              'duplicate_candidates': duplicates, 'existing_platform_matches': existing_matches,
              'broken_references': broken, 'malformed_records': malformed,
              'unclaimed_profiles': unclaimed if fmt == 'legacy' else [],
              'unclaimed_profile_count': len(unclaimed), 'notes': notes, 'records': details[:600]}
    if expected:
        report['acceptance'] = compare_expected(report, expected)
    if dry_run:
        conn.rollback()
    run_id = 'mig_' + secrets.token_hex(6)
    report['run_id'] = run_id
    conn.execute('''INSERT INTO migration_runs(id,started_at,run_by,source_name,source_sha256,mode,counts,report)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                 (run_id, stamp, run_by, source_name, report['source_sha256'], report['mode'], json.dumps(totals),
                  json.dumps(report)))
    log.info('migration run=%s mode=%s source=%s results=%s', run_id, report['mode'], source_name, json.dumps(totals))
    return report


def compare_expected(report, expected):
    """Check a run against legacy_expected_results.json-style criteria."""
    checks = []
    if 'source_counts' in expected:
        checks.append({'check': 'source record counts', 'expected': expected['source_counts'],
                       'found': report['source_counts'], 'pass': report['source_counts'] == expected['source_counts']})
    if 'duplicate_student_candidates' in expected:
        want = sorted((d['legacy_id'], d['possible_duplicate_of']) for d in expected['duplicate_student_candidates'])
        got = sorted((d['legacy_id'], d['possible_duplicate_of']) for d in report['duplicate_candidates'] if d['entity'] == 'student')
        checks.append({'check': 'duplicate student detected', 'expected': want, 'found': got, 'pass': set(want) <= set(got)})
    if 'broken_references' in expected:
        want = sorted((b['project_legacy_id'], b['student_legacy_id']) for b in expected['broken_references'])
        got = sorted((b.get('project_legacy_id'), b.get('student_legacy_id')) for b in report['broken_references'] if b.get('student_legacy_id'))
        checks.append({'check': 'broken contributor reference reported', 'expected': want, 'found': got, 'pass': set(want) <= set(got)})
    if 'unclaimed_profiles' in expected:
        want, got = sorted(expected['unclaimed_profiles']), sorted(report['unclaimed_profiles'])
        checks.append({'check': 'profiles left unclaimed', 'expected': want, 'found': got, 'pass': want == got})
    return {'all_pass': all(c['pass'] for c in checks), 'checks': checks}


@router.post('/api/staff/migrations')
def staff_migrate(payload: MigrationIn, staff=Depends(_staff)):
    if len(json.dumps(payload.data)) > 5_000_000:
        raise HTTPException(413, 'The export is larger than 5 MB. Use the command-line tool instead.')
    if not any(isinstance(payload.data.get(k), list) for k in ('students', 'projects', 'companies', 'collaborations')):
        raise HTTPException(422, 'This file has no students, projects, companies or collaborations lists. '
                                 'Choose the legacy export (legacy_export.json) or the scale fixture.')
    with _db() as conn:
        return run_import(conn, payload.data, source_name=payload.source_name, run_by=staff['id'],
                          dry_run=payload.dry_run, expected=payload.expected)


@router.get('/api/staff/migrations')
def staff_migration_runs(staff=Depends(_staff)):
    with _db() as conn:
        rows = conn.execute('SELECT id, started_at, run_by, source_name, source_sha256, mode, counts FROM migration_runs '
                            'ORDER BY started_at DESC LIMIT 50').fetchall()
    return [{**dict(r), 'counts': json.loads(r['counts'] or '{}')} for r in rows]


@router.get('/api/staff/migrations/{run_id}')
def staff_migration_run(run_id: str, staff=Depends(_staff)):
    _check_id(run_id, 'Migration run')
    with _db() as conn:
        r = conn.execute('SELECT report FROM migration_runs WHERE id=%s', (run_id,)).fetchone()
    if not r:
        raise HTTPException(404, 'Migration run not found')
    return json.loads(r['report'])


# ====================================================================== ownership: claims (F.07-F.10)

def _link_owner(conn, profile_id, account_id, actor, reason):
    """Move a verified sign-in identity onto an imported profile. The claimant's
    own empty draft row is kept (merged_into) so nothing is deleted."""
    profile = conn.execute('SELECT * FROM students WHERE id=%s', (profile_id,)).fetchone()
    account = conn.execute('SELECT * FROM students WHERE id=%s', (account_id,)).fetchone()
    if not profile or not account:
        raise HTTPException(404, 'Profile or account not found')
    if profile['github_id']:
        raise HTTPException(409, 'This profile already has an owner. Release it first.')
    if not account['github_id'] or not account['is_algoma_verified']:
        raise HTTPException(422, 'Only a signed-in account with a verified email can own a profile.')
    if account['id'] == profile['id']:
        raise HTTPException(422, 'That account already is this profile.')
    gh, email, gh_link = account['github_id'], account['email'], account['github_link']
    conn.execute('''UPDATE students SET github_id=NULL, is_algoma_verified=0, is_published=0, publication='merged',
                    claim_state='merged', merged_into=%s WHERE id=%s''', (profile_id, account_id))
    conn.execute('''UPDATE students SET github_id=%s, email=%s, is_algoma_verified=1, claim_state='owned',
                    affiliation_verified_at=coalesce(%s, affiliation_verified_at, %s),
                    github_link=CASE WHEN coalesce(github_link,'')='' THEN %s ELSE github_link END WHERE id=%s''',
                 (gh, email, account.get('affiliation_verified_at'), _iso(), gh_link, profile_id))
    _move_student_links(conn, account_id, profile_id)
    conn.execute('UPDATE auth_sessions SET student_id=%s WHERE student_id=%s', (profile_id, account_id))
    conn.execute('DELETE FROM otp_challenges WHERE student_id=%s', (account_id,))
    _add_redirect(conn, 'student', account_id, profile_id, 'account linked to claimed profile', actor)
    _event(conn, profile_id, 'owner_linked', f'account {account_id} ({reason})', actor)


def _move_student_links(conn, old, new):
    conn.execute('''UPDATE project_contributors SET student_id=%s WHERE student_id=%s
                    AND project_id NOT IN (SELECT project_id FROM project_contributors WHERE student_id=%s)''', (new, old, new))
    conn.execute("UPDATE project_contributors SET status='merged' WHERE student_id=%s", (old,))
    conn.execute('UPDATE projects SET maintainer_id=%s WHERE maintainer_id=%s', (new, old))
    conn.execute('INSERT INTO collaboration_students SELECT collaboration_id, %s FROM collaboration_students WHERE student_id=%s '
                 'ON CONFLICT DO NOTHING', (new, old))
    conn.execute('DELETE FROM collaboration_students WHERE student_id=%s', (old,))
    conn.execute('UPDATE partner_requests SET requested_by=%s WHERE requested_by=%s', (new, old))
    conn.execute('UPDATE project_verification_requests SET requested_by=%s WHERE requested_by=%s', (new, old))
    conn.execute("UPDATE inquiries SET source_id=%s WHERE source_type='student' AND source_id=%s", (new, old))
    conn.execute('UPDATE profile_claims SET claimant_id=%s WHERE claimant_id=%s', (new, old))


def _public_claimable(row):
    return {'id': row['id'], 'name': row['name'], 'status': row['status'], 'publication': row['publication']}


@router.get('/api/claimable')
def claimable(q: str = '', student=Depends(_verified_student)):
    """Imported profiles that have no owner yet. Public fields only."""
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(422, 'Type at least two letters of the name on your old profile.')
    with _db() as conn:
        rows = conn.execute('''SELECT id, name, status, publication FROM students
                               WHERE github_id IS NULL AND merged_into IS NULL AND claim_state IN ('unclaimed','legacy_claimed')
                                 AND publication IN ('published','retired') AND lower(name) LIKE %s
                               ORDER BY name LIMIT 20''', ('%' + q.lower()[:60] + '%',)).fetchall()
    return [_public_claimable(r) for r in rows]


class ClaimIn(BaseModel):
    profile_id: str
    note: str = Field(default='', max_length=1000)


@router.post('/api/claims', status_code=201)
def create_claim(payload: ClaimIn, student=Depends(_verified_student)):
    pid = _check_id(payload.profile_id, 'Profile')
    with _db() as conn:
        profile = conn.execute('SELECT * FROM students WHERE id=%s', (pid,)).fetchone()
        if not profile or profile['merged_into'] or profile['claim_state'] not in ('unclaimed', 'legacy_claimed') \
                or profile['github_id']:
            raise HTTPException(404, 'That profile cannot be claimed. It may already have an owner.')
        if student.get('legacy_id'):
            raise HTTPException(409, 'Your account is already linked to an imported profile. Contact staff to combine profiles.')
        open_claim = conn.execute("SELECT id FROM profile_claims WHERE profile_id=%s AND claimant_id=%s AND status='pending'",
                                  (pid, student['id'])).fetchone()
        if open_claim:
            raise HTTPException(409, 'You already asked to claim this profile. Staff will review it.')
        cid = 'clm_' + secrets.token_hex(6)
        verified_email = (student.get('email') or '').strip().lower()
        legacy_email = (profile['legacy_email'] or '').strip().lower()
        exact = bool(student['is_algoma_verified'] and verified_email and legacy_email and verified_email == legacy_email)
        status = 'auto_approved' if exact else 'pending'
        reason = 'verified email matches the address on the legacy record' if exact else 'needs staff review'
        conn.execute('''INSERT INTO profile_claims(id,profile_id,claimant_id,status,match_reason,note,created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)''', (cid, pid, student['id'], status, reason, payload.note.strip(), _iso()))
        _event(conn, pid, 'claim_requested', f'{cid} by {student["id"]}: {reason}', student['id'])
        if exact:
            _link_owner(conn, pid, student['id'], student['id'], 'automatic: verified email matched legacy record')
            conn.execute("UPDATE profile_claims SET decided_at=%s, decided_by='automatic' WHERE id=%s", (_iso(), cid))
    if exact:
        return {'id': cid, 'status': status, 'profile_id': pid,
                'message': 'Your verified email matches this profile, so it is now yours. Your sign-in now opens it.'}
    return {'id': cid, 'status': status, 'profile_id': pid,
            'message': 'Claim sent to ImmXrsive staff. Nothing changes on the profile until staff approve it.'}


@router.get('/api/claims/mine')
def my_claims(student=Depends(_verified_student)):
    with _db() as conn:
        rows = conn.execute('''SELECT c.id, c.profile_id, s.name AS profile_name, c.status, c.staff_note, c.created_at, c.decided_at
                               FROM profile_claims c JOIN students s ON s.id=c.profile_id WHERE c.claimant_id=%s
                               ORDER BY c.created_at DESC''', (student['id'],)).fetchall()
    return [dict(r) for r in rows]


@router.post('/api/claims/{cid}/withdraw')
def withdraw_claim(cid: str, student=Depends(_verified_student)):
    _check_id(cid, 'Claim')
    with _db() as conn:
        n = conn.execute("UPDATE profile_claims SET status='withdrawn', decided_at=%s WHERE id=%s AND claimant_id=%s AND status='pending'",
                         (_iso(), cid, student['id'])).rowcount
    if not n:
        raise HTTPException(404, 'No open claim to withdraw.')
    return {'message': 'Claim withdrawn.'}


@router.get('/api/staff/claims')
def staff_claims(status: str = 'pending', staff=Depends(_staff)):
    with _db() as conn:
        rows = conn.execute('''SELECT c.*, p.name AS profile_name, p.legacy_id, p.legacy_email, p.status AS profile_status,
                                      a.name AS claimant_name, a.email AS claimant_email, a.github_link AS claimant_github
                               FROM profile_claims c JOIN students p ON p.id=c.profile_id
                               LEFT JOIN students a ON a.id=c.claimant_id
                               WHERE (%s='all' OR c.status=%s) ORDER BY c.created_at DESC LIMIT 200''', (status, status)).fetchall()
    out = []
    for r in rows:
        x = dict(r)
        le, ce = (x.get('legacy_email') or '').lower(), (x.get('claimant_email') or '').lower()
        x['signals'] = {
            'email_exact_match': bool(le and ce and le == ce),
            'same_email_domain': bool(le and ce and le.split('@')[-1] == ce.split('@')[-1]),
            'legacy_record_has_email': bool(le),
            'note': 'Names, GitHub handles and email domains are shown for context only. They never decide a claim.',
        }
        out.append(x)
    return out


class ClaimDecision(BaseModel):
    approve: bool
    note: str = Field(default='', max_length=1000)


@router.post('/api/staff/claims/{cid}/decision')
def staff_claim_decision(cid: str, payload: ClaimDecision, staff=Depends(_staff)):
    _check_id(cid, 'Claim')
    if not payload.approve and not payload.note.strip():
        raise HTTPException(422, 'Add a short note for the student explaining why the claim was rejected.')
    with _db() as conn:
        c = conn.execute('SELECT * FROM profile_claims WHERE id=%s', (cid,)).fetchone()
        if not c or c['status'] != 'pending':
            raise HTTPException(404, 'This claim is not waiting for a decision.')
        if payload.approve:
            _link_owner(conn, c['profile_id'], c['claimant_id'], staff['id'], f'staff approved claim {cid}')
            conn.execute("""UPDATE profile_claims SET status='rejected', staff_note='Another claim for this profile was approved.',
                            decided_by=%s, decided_at=%s WHERE profile_id=%s AND status='pending' AND id<>%s""",
                         (staff['id'], _iso(), c['profile_id'], cid))
        conn.execute('UPDATE profile_claims SET status=%s, staff_note=%s, decided_by=%s, decided_at=%s WHERE id=%s',
                     ('approved' if payload.approve else 'rejected', payload.note.strip(), staff['id'], _iso(), cid))
        _event(conn, c['profile_id'], 'claim_' + ('approved' if payload.approve else 'rejected'), cid, staff['id'])
    return {'message': 'Claim approved. The student now owns the profile.' if payload.approve else 'Claim rejected. The profile is unchanged.'}


class OwnerIn(BaseModel):
    action: str                     # release | assign
    account_id: str = ''
    note: str = Field(min_length=3, max_length=1000)


@router.post('/api/staff/students/{sid}/owner')
def staff_owner(sid: str, payload: OwnerIn, staff=Depends(_staff)):
    """Recovery: release a profile from a wrong owner, or assign it to the right
    verified account. Always needs a written justification (logged)."""
    _check_id(sid, 'Student')
    with _db() as conn:
        p = conn.execute('SELECT * FROM students WHERE id=%s', (sid,)).fetchone()
        if not p or p['merged_into']:
            raise HTTPException(404, 'Student not found')
        if payload.action == 'release':
            if not p['github_id']:
                raise HTTPException(409, 'This profile has no owner to release.')
            # The released sign-in gets a fresh empty draft the next time it signs in.
            conn.execute("UPDATE students SET github_id=NULL, is_algoma_verified=0, claim_state='unclaimed', "
                         "legacy_email=coalesce(legacy_email, email), email=NULL WHERE id=%s", (sid,))
            conn.execute('DELETE FROM auth_sessions WHERE student_id=%s', (sid,))
            _event(conn, sid, 'owner_released', payload.note, staff['id'])
            return {'message': 'Owner removed. The profile is unclaimed and can be claimed or assigned again.'}
        if payload.action == 'assign':
            acct = _check_id(payload.account_id.strip(), 'Account')
            if p['github_id']:
                raise HTTPException(409, 'Release the current owner first.')
            _link_owner(conn, sid, acct, staff['id'], 'staff assignment: ' + payload.note)
            return {'message': 'Profile assigned to the chosen account.'}
    raise HTTPException(422, 'Action must be release or assign.')


# ====================================================================== staff: students, duplicates, merges

@router.get('/api/staff/students')
def staff_students(q: str = '', state: str = '', page: int = 1, staff=Depends(_staff)):
    page = max(1, page)
    like = '%' + q.strip().lower()[:60] + '%'
    with _db() as conn:
        where = '''merged_into IS NULL AND (lower(coalesce(name,'')) LIKE %s OR lower(id) LIKE %s OR lower(coalesce(legacy_id,'')) LIKE %s)'''
        params = [like, like, like]
        if state in ('unclaimed', 'legacy_claimed', 'owned'):
            where += ' AND claim_state=%s'; params.append(state)
        if state in PUBLICATION:
            where += ' AND publication=%s'; params.append(state)
        total = conn.execute(f'SELECT count(*) AS n FROM students WHERE {where}', params).fetchone()['n']
        rows = conn.execute(f'''SELECT id, name, status, publication, claim_state, legacy_id, talent_mode, availability,
                                availability_confirmed_at, (github_id IS NOT NULL) AS has_owner FROM students WHERE {where}
                                ORDER BY lower(coalesce(name,'')), id LIMIT 50 OFFSET %s''', params + [(page - 1) * 50]).fetchall()
    return {'total': total, 'page': page, 'items': [{**dict(r), **{k: talent_view(r)[k] for k in ('talent_state',)}} for r in rows]}


@router.get('/api/staff/students/{sid}')
def staff_student(sid: str, staff=Depends(_staff)):
    _check_id(sid, 'Student')
    with _db() as conn:
        r = conn.execute('SELECT * FROM students WHERE id=%s', (sid,)).fetchone()
        if not r:
            raise HTTPException(404, 'Student not found')
        events = [dict(e) for e in conn.execute('SELECT action, detail, actor, at FROM profile_events WHERE profile_id=%s ORDER BY id DESC LIMIT 50', (sid,)).fetchall()]
        projects = [dict(p) for p in conn.execute('''SELECT p.id, p.title, c.role, c.status, p.maintainer_id=%s AS is_maintainer
                     FROM project_contributors c JOIN projects p ON p.id=c.project_id WHERE c.student_id=%s ORDER BY p.title''', (sid, sid)).fetchall()]
        claims = [dict(c) for c in conn.execute('SELECT id, claimant_id, status, match_reason, created_at FROM profile_claims WHERE profile_id=%s ORDER BY created_at DESC', (sid,)).fetchall()]
        dupes = [dict(d) for d in conn.execute('''SELECT d.id, d.record_id, d.other_id, d.reason, d.status, s.name AS other_name
                    FROM duplicate_candidates d LEFT JOIN students s ON s.id = CASE WHEN d.record_id=%s THEN d.other_id ELSE d.record_id END
                    WHERE d.entity='student' AND (d.record_id=%s OR d.other_id=%s)''', (sid, sid, sid)).fetchall()]
    out = {k: r[k] for k in ('id', 'name', 'status', 'publication', 'claim_state', 'legacy_id', 'legacy_email', 'email',
                             'is_algoma_verified', 'affiliation_verified_at', 'merged_into', 'program', 'headline')}
    out.update(talent_view(r))
    out['has_owner'] = bool(r['github_id'])
    out['events'], out['projects'], out['claims'], out['duplicates'] = events, projects, claims, dupes
    out['public_url'] = f"{_cfg['frontend']}/student.html?id={r['id']}"
    return out


@router.get('/api/staff/duplicates')
def staff_duplicates(staff=Depends(_staff)):
    with _db() as conn:
        rows = conn.execute('''SELECT d.*, coalesce(s1.name, c1.name) AS record_name, coalesce(s2.name, c2.name) AS other_name
                FROM duplicate_candidates d
                LEFT JOIN students s1 ON d.entity='student' AND s1.id=d.record_id
                LEFT JOIN students s2 ON d.entity='student' AND s2.id=d.other_id
                LEFT JOIN companies c1 ON d.entity='company' AND c1.id=d.record_id
                LEFT JOIN companies c2 ON d.entity='company' AND c2.id=d.other_id
                WHERE d.status='open' ORDER BY d.created_at''').fetchall()
    return [dict(r) for r in rows]


@router.post('/api/staff/duplicates/{did}/dismiss')
def dismiss_duplicate(did: int, staff=Depends(_staff)):
    with _db() as conn:
        n = conn.execute("UPDATE duplicate_candidates SET status='dismissed', resolved_by=%s, resolved_at=%s WHERE id=%s AND status='open'",
                         (staff['id'], _iso(), did)).rowcount
    if not n:
        raise HTTPException(404, 'Nothing to dismiss.')
    return {'message': 'Marked as not a duplicate. Both records stay as they are.'}


class MergeIn(BaseModel):
    survivor_id: str
    duplicate_id: str
    note: str = Field(default='', max_length=1000)


@router.post('/api/staff/students/merge')
def merge_students(payload: MergeIn, staff=Depends(_staff)):
    keep, drop = _check_id(payload.survivor_id, 'Student'), _check_id(payload.duplicate_id, 'Student')
    if keep == drop:
        raise HTTPException(422, 'Choose two different records.')
    with _db() as conn:
        a = conn.execute('SELECT * FROM students WHERE id=%s', (keep,)).fetchone()
        b = conn.execute('SELECT * FROM students WHERE id=%s', (drop,)).fetchone()
        if not a or not b or a['merged_into'] or b['merged_into']:
            raise HTTPException(404, 'One of the records no longer exists or was already merged.')
        if b['github_id']:
            raise HTTPException(409, 'The duplicate has its own sign-in. Keep the signed-in record as the survivor, '
                                     'or release its owner first.')
        skills = list(dict.fromkeys(_jl(a['skills']) + _jl(b['skills'])))
        moved = conn.execute('SELECT count(*) AS n FROM project_contributors WHERE student_id=%s', (drop,)).fetchone()['n']
        _move_student_links(conn, drop, keep)
        conn.execute('''UPDATE students SET skills=%s, legacy_email=coalesce(legacy_email,%s),
                        headline=CASE WHEN coalesce(headline,'')='' THEN %s ELSE headline END WHERE id=%s''',
                     (json.dumps(skills), b['legacy_email'], b['headline'] or '', keep))
        conn.execute('''UPDATE students SET merged_into=%s, is_published=0, publication='merged', claim_state='merged'
                        WHERE id=%s''', (keep, drop))
        conn.execute("""UPDATE profile_claims SET status='rejected', staff_note='Profile was merged into another record.',
                        decided_by=%s, decided_at=%s WHERE profile_id=%s AND status='pending'""", (staff['id'], _iso(), drop))
        conn.execute("""UPDATE duplicate_candidates SET status='merged', resolved_by=%s, resolved_at=%s
                        WHERE entity='student' AND (record_id=%s OR other_id=%s) AND status='open'""", (staff['id'], _iso(), drop, drop))
        _add_redirect(conn, 'student', drop, keep, 'duplicate merged', staff['id'])
        _event(conn, keep, 'merged_in', f'{drop} ({payload.note})', staff['id'])
        _event(conn, drop, 'merged_into', keep, staff['id'])
    return {'message': f"Merged. {moved} project relationship(s) now point to {a['name']}. The old profile link redirects there.",
            'survivor_id': keep, 'redirect_from': drop}


@router.post('/api/staff/companies/merge')
def merge_companies(payload: MergeIn, staff=Depends(_staff)):
    keep, drop = _check_id(payload.survivor_id, 'Partner'), _check_id(payload.duplicate_id, 'Partner')
    if keep == drop:
        raise HTTPException(422, 'Choose two different partners.')
    with _db() as conn:
        a = conn.execute('SELECT * FROM companies WHERE id=%s', (keep,)).fetchone()
        b = conn.execute('SELECT * FROM companies WHERE id=%s', (drop,)).fetchone()
        if not a or not b or a['merged_into'] or b['merged_into']:
            raise HTTPException(404, 'One of the partners no longer exists or was already merged.')
        n = conn.execute('UPDATE collaborations SET company_id=%s WHERE company_id=%s', (keep, drop)).rowcount
        conn.execute('INSERT INTO project_partners SELECT project_id, %s, request_id, approved_by, approved_at FROM project_partners '
                     'WHERE company_id=%s ON CONFLICT DO NOTHING', (keep, drop))
        conn.execute('DELETE FROM project_partners WHERE company_id=%s', (drop,))
        conn.execute('UPDATE partner_requests SET company_id=%s WHERE company_id=%s', (keep, drop))
        conn.execute("UPDATE inquiries SET source_id=%s WHERE source_type='partner' AND source_id=%s", (keep, drop))
        conn.execute("UPDATE companies SET merged_into=%s, status='merged', updated_at=%s, updated_by=%s WHERE id=%s",
                     (keep, _iso(), staff['id'], drop))
        conn.execute("""UPDATE duplicate_candidates SET status='merged', resolved_by=%s, resolved_at=%s
                        WHERE entity='company' AND (record_id=%s OR other_id=%s) AND status='open'""", (staff['id'], _iso(), drop, drop))
        _add_redirect(conn, 'partner', drop, keep, 'duplicate merged', staff['id'])
    return {'message': f"Merged. {n} collaboration(s) moved to {a['name']}. The old partner link redirects there.",
            'survivor_id': keep, 'redirect_from': drop}


# ====================================================================== staff: projects, maintainer recovery, demo state

@router.get('/api/staff/projects')
def staff_projects(q: str = '', staff=Depends(_staff)):
    like = '%' + q.strip().lower()[:60] + '%'
    with _db() as conn:
        rows = conn.execute('''SELECT p.id, p.title, p.is_published, p.maintainer_id, m.name AS maintainer_name, p.legacy_id,
                                      p.demo_state, (SELECT count(*) FROM project_contributors c WHERE c.project_id=p.id AND c.status='accepted') AS contributors
                               FROM projects p LEFT JOIN students m ON m.id=p.maintainer_id
                               WHERE lower(p.title) LIKE %s OR lower(p.id) LIKE %s ORDER BY lower(p.title) LIMIT 50''', (like, like)).fetchall()
    return [dict(r) for r in rows]


@router.get('/api/staff/projects/{pid}')
def staff_project(pid: str, staff=Depends(_staff)):
    _check_id(pid, 'Project')
    with _db() as conn:
        p = conn.execute('SELECT * FROM projects WHERE id=%s', (pid,)).fetchone()
        if not p:
            raise HTTPException(404, 'Project not found')
        contributors = [dict(c) for c in conn.execute(
            '''SELECT c.student_id, s.name, c.role, c.status, c.statement, s.github_id IS NOT NULL AS has_account,
                      s.is_algoma_verified FROM project_contributors c LEFT JOIN students s ON s.id=c.student_id
               WHERE c.project_id=%s ORDER BY s.name''', (pid,)).fetchall()]
        history = [dict(h) for h in conn.execute('SELECT * FROM maintainer_history WHERE project_id=%s ORDER BY id DESC', (pid,)).fetchall()]
    keys = ('id', 'title', 'is_published', 'maintainer_id', 'legacy_id', 'demo_state', 'demo_type', 'demo_note',
            'playable_url', 'video_url', 'fallback_url', 'fallback_text', 'demo_replacement_url', 'version')
    return {**{k: p[k] for k in keys}, 'contributors': contributors, 'maintainer_history': history,
            'public_url': f"{_cfg['frontend']}/project.html?id={pid}"}


class MaintainerIn(BaseModel):
    student_id: str
    role: str = ''
    note: str = Field(min_length=3, max_length=1000)


@router.post('/api/staff/projects/{pid}/maintainer')
def staff_set_maintainer(pid: str, payload: MaintainerIn, staff=Depends(_staff)):
    """F.19: same project, same URL, contributor rows untouched."""
    _check_id(pid, 'Project')
    sid = _check_id(payload.student_id, 'Student')
    with _db() as conn:
        p = conn.execute('SELECT * FROM projects WHERE id=%s', (pid,)).fetchone()
        s = conn.execute('SELECT * FROM students WHERE id=%s', (sid,)).fetchone()
        if not p:
            raise HTTPException(404, 'Project not found')
        if not s or s['merged_into'] or not s['github_id'] or not s['is_algoma_verified']:
            raise HTTPException(422, 'The new maintainer must be a signed-in student with a verified email.')
        if p['maintainer_id'] == sid:
            raise HTTPException(409, 'That student already maintains this project.')
        m = conn.execute('SELECT status FROM project_contributors WHERE project_id=%s AND student_id=%s', (pid, sid)).fetchone()
        if not m or m['status'] != 'accepted':
            from projects_r3 import canonical_role
            role = canonical_role(payload.role)
            if m:
                conn.execute("UPDATE project_contributors SET status='accepted', role=%s, updated_at=%s WHERE project_id=%s AND student_id=%s",
                             (role, _iso(), pid, sid))
            else:
                conn.execute('''INSERT INTO project_contributors (project_id,student_id,role,status,statement,featured,updated_at)
                                VALUES (%s,%s,%s,'accepted','',1,%s)''', (pid, sid, role, _iso()))
        conn.execute('UPDATE projects SET maintainer_id=%s, version=version+1, updated_at=%s, updated_by=%s WHERE id=%s',
                     (sid, _iso(), staff['id'], pid))
        conn.execute('INSERT INTO maintainer_history(project_id,from_id,to_id,actor,note,at) VALUES (%s,%s,%s,%s,%s,%s)',
                     (pid, p['maintainer_id'], sid, staff['id'], payload.note.strip(), _iso()))
    return {'message': f"{s['name']} now maintains this project. The project page, URL and every contributor's role and statement are unchanged."}


class DemoStateIn(BaseModel):
    demo_state: str
    demo_note: str = Field(default='', max_length=300)
    demo_replacement_url: str = Field(default='', max_length=500)


def validate_demo_state(payload: DemoStateIn):
    if payload.demo_state not in DEMO_STATES:
        raise HTTPException(422, 'Demo state must be available, unavailable, archived or replaced.')
    url = payload.demo_replacement_url.strip()
    if url and not HTTPS_RE.match(url):
        raise HTTPException(422, 'Replacement link must start with https://')
    if payload.demo_state == 'replaced' and not url:
        raise HTTPException(422, 'Add the https:// link of the replacement build.')
    return payload.demo_state, payload.demo_note.strip(), url


@router.post('/api/staff/projects/{pid}/demo-state')
def staff_demo_state(pid: str, payload: DemoStateIn, staff=Depends(_staff)):
    _check_id(pid, 'Project')
    state, note, url = validate_demo_state(payload)
    with _db() as conn:
        n = conn.execute('UPDATE projects SET demo_state=%s, demo_note=%s, demo_replacement_url=%s, updated_at=%s WHERE id=%s',
                         (state, note, url, _iso(), pid)).rowcount
    if not n:
        raise HTTPException(404, 'Project not found')
    return {'message': f'Demo marked {state}. The project page and its history are unchanged.'}


@router.post('/api/projects/{pid}/demo-state')
def maintainer_demo_state(pid: str, payload: DemoStateIn, student=Depends(_verified_student)):
    _check_id(pid, 'Project')
    state, note, url = validate_demo_state(payload)
    with _db() as conn:
        p = conn.execute('SELECT maintainer_id FROM projects WHERE id=%s', (pid,)).fetchone()
        if not p:
            raise HTTPException(404, 'Project not found')
        if p['maintainer_id'] != student['id']:
            raise HTTPException(403, 'Only the project maintainer can change the demo state.')
        conn.execute('UPDATE projects SET demo_state=%s, demo_note=%s, demo_replacement_url=%s, updated_at=%s WHERE id=%s',
                     (state, note, url, _iso(), pid))
    return {'message': f'Demo marked {state}.'}


# ====================================================================== staff summary for the home screen

@router.get('/api/staff/final-queue')
def final_queue(staff=Depends(_staff)):
    with _db() as conn:
        claims = conn.execute("SELECT count(*) AS n FROM profile_claims WHERE status='pending'").fetchone()['n']
        dupes = conn.execute("SELECT count(*) AS n FROM duplicate_candidates WHERE status='open'").fetchone()['n']
        orphan = conn.execute('''SELECT count(*) AS n FROM projects p WHERE p.is_published=1 AND (p.maintainer_id IS NULL OR
                                 NOT EXISTS (SELECT 1 FROM students s WHERE s.id=p.maintainer_id AND s.github_id IS NOT NULL))''').fetchone()['n']
        errors = conn.execute('SELECT count(*) AS n FROM diagnostic_events WHERE at > %s', (_iso(_now() - timedelta(days=1)),)).fetchone()['n']
    return {'pending_claims': claims, 'open_duplicates': dupes, 'projects_without_active_maintainer': orphan,
            'diagnostic_events_24h': errors}
