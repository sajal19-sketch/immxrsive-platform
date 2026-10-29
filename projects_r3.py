"""ImmXrsive Release 3: shared projects, contributor evidence, playable demos.

Wired into main.py with configure(...) and app.include_router(router).

Decisions (also stated in RELEASE_NOTES_R3.md):
- Only the project maintainer edits shared project fields (title, description,
  technologies, links, demo, publish state, invitations). Accepted contributors
  edit only their own role, contribution statement and featured flag.
- Removing an accepted contributor is a soft delete (status 'removed'). The
  relationship row is kept and the maintainer can restore it.
- Every shared-field save carries the version the editor loaded. A stale
  version is refused with 409 instead of overwriting newer work.
"""
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()
_cfg = {}


def configure(*, db, authenticated, parsed, skill_catalog, frontend):
    _cfg.update(db=db, authenticated=authenticated, parsed=parsed,
                skill_catalog=skill_catalog, frontend=frontend)


def _db():
    return _cfg['db']()


def _now():
    return datetime.now(timezone.utc).isoformat()


def require_verified(request: Request):
    student = _cfg['authenticated'](request)
    if not student['is_algoma_verified']:
        raise HTTPException(403, 'Verify your Algoma email before managing projects.')
    return student


# ---------------------------------------------------------------- schema

def setup_schema(conn):
    """Additive only: never drops or rewrites existing rows."""
    project_cols = {
        'status': "TEXT NOT NULL DEFAULT ''",
        'project_date': "TEXT NOT NULL DEFAULT ''",
        'maintainer_id': 'TEXT',
        'version': 'INTEGER NOT NULL DEFAULT 1',
        'is_published': 'INTEGER NOT NULL DEFAULT 1',  # existing fixture projects stay public
        'playable_url': "TEXT NOT NULL DEFAULT ''",
        'video_url': "TEXT NOT NULL DEFAULT ''",
        'fallback_url': "TEXT NOT NULL DEFAULT ''",
        'fallback_text': "TEXT NOT NULL DEFAULT ''",
        'created_at': 'TEXT',
        'updated_at': 'TEXT',
        'updated_by': 'TEXT',
    }
    for key, spec in project_cols.items():
        conn.execute(f'ALTER TABLE projects ADD COLUMN IF NOT EXISTS {key} {spec}')
    contrib_cols = {
        'status': "TEXT NOT NULL DEFAULT 'accepted'",  # fixture rows are accepted
        'statement': "TEXT NOT NULL DEFAULT ''",
        'featured': 'INTEGER NOT NULL DEFAULT 1',
        'invited_by': 'TEXT',
        'updated_at': 'TEXT',
        'removed_by': 'TEXT',
    }
    for key, spec in contrib_cols.items():
        conn.execute(f'ALTER TABLE project_contributors ADD COLUMN IF NOT EXISTS {key} {spec}')
    conn.execute('''CREATE TABLE IF NOT EXISTS project_repos(
        project_id TEXT NOT NULL, url TEXT NOT NULL, norm TEXT NOT NULL,
        UNIQUE(project_id, norm))''')
    conn.execute('CREATE INDEX IF NOT EXISTS project_repos_norm ON project_repos(norm)')


# ---------------------------------------------------------------- reference data

FALLBACK_ROLES = ['XR Developer', 'Software Developer', 'Game Developer', '3D Artist',
                  'UX Researcher', 'UI/UX Designer', 'Project Manager', 'QA Tester',
                  'Technical Writer', 'Data Analyst']


def standard_roles():
    """Roles from data/standard_roles.json (Release 3 fixture). Accepts a list of
    strings, a list of objects with name/label/role, or {"roles": [...]}."""
    path = Path(__file__).resolve().parent / 'data' / 'standard_roles.json'
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return FALLBACK_ROLES, 'fallback'
    if isinstance(raw, dict):
        raw = raw.get('roles', raw.get('items', raw.get('data', [])))
    roles = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            item = item.get('name') or item.get('label') or item.get('role') or item.get('title') or ''
        label = str(item).strip()
        if label and label.casefold() not in {r.casefold() for r in roles}:
            roles.append(label)
    return (roles, 'fixture') if roles else (FALLBACK_ROLES, 'fallback')


def canonical_role(value):
    roles, _ = standard_roles()
    found = {r.casefold(): r for r in roles}.get(str(value or '').strip().casefold())
    if not found:
        raise HTTPException(422, 'Choose a role from the standard role list.')
    return found


@router.get('/api/roles')
def roles_endpoint():
    roles, source = standard_roles()
    return {'roles': roles, 'source': source}


# ---------------------------------------------------------------- validation helpers

URL_RE = re.compile(r'^https://[^\s<>"\'`]+$', re.I)
STATUSES = ['Planning', 'In progress', 'Completed', 'Archived']
ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def clean_url(value, label):
    value = (value or '').strip()
    if not value:
        return ''
    if len(value) > 500 or not URL_RE.match(value):
        raise HTTPException(422, f'{label} must be a full https:// link.')
    return value


def normalize_repo(url):
    """Comparable form of a repository URL for duplicate detection."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix('www.')
    path = parts.path.rstrip('/')
    if path.endswith('.git'):
        path = path[:-4]
    if host == 'github.com':
        path = path.lower()
        segs = [s for s in path.split('/') if s]
        path = '/' + '/'.join(segs[:2])
    return host + path


def clean_technologies(items):
    catalog = {s.casefold(): s for s in _cfg['skill_catalog']()}
    out = []
    for t in items:
        t = re.sub(r'\s+', ' ', str(t)).strip()
        if not t:
            continue
        if len(t) > 40:
            raise HTTPException(422, 'Each technology must be 40 characters or fewer.')
        t = catalog.get(t.casefold(), t)
        if t.casefold() not in {x.casefold() for x in out}:
            out.append(t)
    return out


class ProjectFields(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default='', max_length=2000)
    domain: str = Field(default='', max_length=80)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    status: str = ''
    project_date: str = ''
    repo_urls: list[str] = Field(default_factory=list, max_length=5)
    playable_url: str = ''
    video_url: str = ''
    fallback_url: str = ''
    fallback_text: str = Field(default='', max_length=300)


class ProjectCreate(ProjectFields):
    my_role: str
    acknowledge_duplicates: bool = False


class ProjectUpdate(ProjectFields):
    version: int


def validated(fields: ProjectFields):
    title = fields.title.strip()
    if not title:
        raise HTTPException(422, 'Project title is required.')
    if fields.status and fields.status not in STATUSES:
        raise HTTPException(422, 'Status must be Planning, In progress, Completed or Archived.')
    if fields.project_date and not re.fullmatch(r'\d{4}(-\d{2}(-\d{2})?)?', fields.project_date):
        raise HTTPException(422, 'Date must look like 2026, 2026-10 or 2026-10-29.')
    repos, norms = [], set()
    for u in fields.repo_urls:
        u = clean_url(u, 'Repository link')
        if u and normalize_repo(u) not in norms:
            norms.add(normalize_repo(u))
            repos.append(u)
    return {
        'title': title,
        'description': fields.description.strip(),
        'domain': fields.domain.strip(),
        'technologies': clean_technologies(fields.technologies),
        'status': fields.status,
        'project_date': fields.project_date,
        'repos': repos,
        'playable_url': clean_url(fields.playable_url, 'Playable demo link'),
        'video_url': clean_url(fields.video_url, 'Video link'),
        'fallback_url': clean_url(fields.fallback_url, 'Fallback image/link'),
        'fallback_text': fields.fallback_text.strip(),
    }


# ---------------------------------------------------------------- data access

def load_project(conn, pid):
    if not ID_RE.match(pid or ''):
        raise HTTPException(404, 'Project not found')
    row = conn.execute('SELECT * FROM projects WHERE id=%s', (pid,)).fetchone()
    if not row:
        raise HTTPException(404, 'Project not found')
    return dict(row)


def require_maintainer(project, student):
    if project.get('maintainer_id') != student['id']:
        raise HTTPException(403, 'Only the project maintainer can change shared project details.')


def membership(conn, pid, sid):
    row = conn.execute('SELECT * FROM project_contributors WHERE project_id=%s AND student_id=%s',
                       (pid, sid)).fetchone()
    return dict(row) if row else None


def repos_for(conn, pid):
    return [r['url'] for r in conn.execute(
        'SELECT url FROM project_repos WHERE project_id=%s ORDER BY url', (pid,)).fetchall()]


def save_repos(conn, pid, repos):
    conn.execute('DELETE FROM project_repos WHERE project_id=%s', (pid,))
    for u in repos:
        conn.execute('INSERT INTO project_repos(project_id,url,norm) VALUES (%s,%s,%s) '
                     'ON CONFLICT (project_id,norm) DO NOTHING', (pid, u, normalize_repo(u)))


def repo_matches(conn, repos, exclude=None):
    norms = [normalize_repo(u) for u in repos if u]
    if not norms:
        return []
    rows = conn.execute(
        '''SELECT DISTINCT p.id, p.title, p.is_published, r.url FROM project_repos r
           JOIN projects p ON p.id=r.project_id WHERE r.norm = ANY(%s) AND p.id <> %s''',
        (norms, exclude or '')).fetchall()
    return [{'id': r['id'], 'title': r['title'], 'repo_url': r['url'],
             'published': bool(r['is_published'])} for r in rows]


def similar_titles(conn, title, exclude=None):
    words = [w for w in re.findall(r'[a-z0-9]+', (title or '').lower()) if len(w) > 2]
    if not words:
        return []
    rows = conn.execute('SELECT id, title FROM projects WHERE id <> %s AND is_published=1',
                        (exclude or '',)).fetchall()
    out = []
    for r in rows:
        other = set(re.findall(r'[a-z0-9]+', (r['title'] or '').lower()))
        if other and len(set(words) & other) / max(len(set(words)), 1) >= 0.6:
            out.append({'id': r['id'], 'title': r['title']})
    return out[:5]


def contributor_rows(conn, pid):
    return [dict(r) for r in conn.execute(
        '''SELECT c.student_id, c.role, c.status, c.statement, c.featured,
                  s.name, s.is_published AS student_published, s.github_link
           FROM project_contributors c LEFT JOIN students s ON s.id=c.student_id
           WHERE c.project_id=%s ORDER BY c.student_id''', (pid,)).fetchall()]


def project_core(project, repos):
    p = project
    return {
        'id': p['id'], 'title': p['title'], 'description': p.get('description') or '',
        'domain': p.get('domain') or '', 'technologies': _cfg['parsed'](p.get('technologies')),
        'status': p.get('status') or '', 'project_date': p.get('project_date') or '',
        'repo_urls': repos, 'playable_url': p.get('playable_url') or '',
        'video_url': p.get('video_url') or '', 'fallback_url': p.get('fallback_url') or '',
        'fallback_text': p.get('fallback_text') or '',
        'is_published': bool(p.get('is_published')),
    }


def public_contributor(c, maintainer_id):
    visible = bool(c.get('student_published'))
    return {
        'student_id': c['student_id'] if visible else None,
        'name': (c.get('name') or 'Student') if visible else 'Contributor (profile not public)',
        'role': c['role'], 'statement': c['statement'] or '',
        'is_maintainer': c['student_id'] == maintainer_id,
    }


# ---------------------------------------------------------------- public read

@router.get('/api/projects/{project_id}')
def public_project(project_id: str):
    with _db() as conn:
        project = load_project(conn, project_id)
        if not project.get('is_published'):
            raise HTTPException(404, 'Project not found')
        out = project_core(project, repos_for(conn, project_id))
        rows = contributor_rows(conn, project_id)
    # Only accepted contributors are public (invited/declined/removed never are).
    out['contributors'] = [public_contributor(c, project.get('maintainer_id'))
                           for c in rows if c['status'] == 'accepted']
    out.pop('is_published')
    return out


def public_projects_for(conn, student_ids):
    """Accepted, featured, published projects for each student (profile evidence)."""
    if not student_ids:
        return {}
    rows = conn.execute(
        '''SELECT c.student_id, p.id, p.title, c.role FROM project_contributors c
           JOIN projects p ON p.id=c.project_id
           WHERE c.student_id = ANY(%s) AND c.status='accepted' AND c.featured=1
                 AND p.is_published=1 ORDER BY p.title, p.id''', (list(student_ids),)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r['student_id'], []).append({'id': r['id'], 'title': r['title'], 'role': r['role']})
    return out


# ---------------------------------------------------------------- GitHub import

GITHUB_REPO_RE = re.compile(r'^(?:https://(?:www\.)?github\.com/)?([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$')


def fetch_github(owner, repo):
    import httpx
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'ImmXrsive'}
    token = os.environ.get('GITHUB_API_TOKEN', '')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    with httpx.Client(timeout=10, headers=headers) as client:
        r = client.get(f'https://api.github.com/repos/{owner}/{repo}')
        if r.status_code == 404:
            raise HTTPException(404, 'Repository not found or not public. You can still fill in the project manually.')
        if r.status_code in (403, 429):
            raise HTTPException(503, 'GitHub is limiting requests right now. Try again later or fill in the project manually.')
        if r.status_code != 200:
            raise HTTPException(502, 'GitHub could not be reached. Fill in the project manually.')
        meta = r.json()
        langs = client.get(f'https://api.github.com/repos/{owner}/{repo}/languages')
        languages = list(langs.json().keys()) if langs.status_code == 200 else []
    return meta, languages


@router.get('/api/github/repo')
def github_import(url: str, student=Depends(require_verified)):
    m = GITHUB_REPO_RE.match((url or '').strip())
    if not m:
        raise HTTPException(422, 'Enter a public GitHub repository link like https://github.com/owner/repo')
    meta, languages = fetch_github(m.group(1), m.group(2))
    if meta.get('private'):
        raise HTTPException(404, 'Only public repositories can be imported.')
    html_url = str(meta.get('html_url') or '')
    pushed = str(meta.get('pushed_at') or '')
    suggestion = {
        'title': str(meta.get('name') or '').replace('-', ' ').replace('_', ' ').strip(),
        'description': str(meta.get('description') or '')[:2000],
        'repo_url': html_url if URL_RE.match(html_url) else '',
        'technologies': [str(x) for x in languages][:15],
        'topics': [str(x) for x in (meta.get('topics') or [])][:15],
        'project_date': pushed[:7] if re.match(r'\d{4}-\d{2}', pushed) else '',
        'homepage': str(meta.get('homepage') or '') if URL_RE.match(str(meta.get('homepage') or '')) else '',
    }
    with _db() as conn:
        dupes = repo_matches(conn, [suggestion['repo_url']]) if suggestion['repo_url'] else []
    return {'suggestion': suggestion, 'duplicates': dupes,
            'message': 'Suggestions only. Review and edit before saving.'}


class DuplicateCheck(BaseModel):
    repo_urls: list[str] = Field(default_factory=list, max_length=5)
    title: str = Field(default='', max_length=150)
    exclude_project_id: str = ''


@router.post('/api/projects/duplicates')
def duplicate_check(payload: DuplicateCheck, student=Depends(require_verified)):
    repos = [clean_url(u, 'Repository link') for u in payload.repo_urls]
    with _db() as conn:
        return {'repo_matches': repo_matches(conn, repos, payload.exclude_project_id),
                'similar_titles': similar_titles(conn, payload.title, payload.exclude_project_id)}


# ---------------------------------------------------------------- create / edit (maintainer)

@router.post('/api/projects')
def create_project(payload: ProjectCreate, student=Depends(require_verified)):
    data = validated(payload)
    role = canonical_role(payload.my_role)
    with _db() as conn:
        dupes = repo_matches(conn, data['repos'])
        if dupes and not payload.acknowledge_duplicates:
            raise HTTPException(409, {'code': 'duplicate_repository',
                                      'message': 'This repository is already connected to a project. View or ask to join it instead of creating a duplicate.',
                                      'matches': dupes})
        pid = 'p_' + secrets.token_hex(8)
        stamp = _now()
        conn.execute(
            '''INSERT INTO projects (id,title,description,domain,technologies,status,project_date,
               maintainer_id,version,is_published,playable_url,video_url,fallback_url,fallback_text,
               created_at,updated_at,updated_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,0,%s,%s,%s,%s,%s,%s,%s)''',
            (pid, data['title'], data['description'], data['domain'], json.dumps(data['technologies']),
             data['status'], data['project_date'], student['id'], data['playable_url'], data['video_url'],
             data['fallback_url'], data['fallback_text'], stamp, stamp, student['id']))
        save_repos(conn, pid, data['repos'])
        conn.execute(
            '''INSERT INTO project_contributors (project_id,student_id,role,status,statement,featured,updated_at)
               VALUES (%s,%s,%s,'accepted','',1,%s)''', (pid, student['id'], role, stamp))
    return {'id': pid, 'version': 1, 'message': 'Project saved as a private draft. Invite teammates, then publish.'}


@router.put('/api/projects/{project_id}')
def update_project(project_id: str, payload: ProjectUpdate, student=Depends(require_verified)):
    data = validated(payload)
    with _db() as conn:
        project = load_project(conn, project_id)
        require_maintainer(project, student)
        row = conn.execute(
            '''UPDATE projects SET title=%s,description=%s,domain=%s,technologies=%s,status=%s,
               project_date=%s,playable_url=%s,video_url=%s,fallback_url=%s,fallback_text=%s,
               updated_at=%s,updated_by=%s,version=version+1
               WHERE id=%s AND version=%s RETURNING version''',
            (data['title'], data['description'], data['domain'], json.dumps(data['technologies']),
             data['status'], data['project_date'], data['playable_url'], data['video_url'],
             data['fallback_url'], data['fallback_text'], _now(), student['id'],
             project_id, payload.version)).fetchone()
        if not row:
            current = load_project(conn, project_id)
            raise HTTPException(409, {'code': 'stale_version',
                                      'message': 'This project was changed in another session after you opened it. Your save was not applied. Reload to see the newer version, then re-apply your edits.',
                                      'current_version': current['version']})
        save_repos(conn, project_id, data['repos'])
    return {'id': project_id, 'version': row['version'], 'message': 'Project saved.'}


def _set_published(project_id, student, value):
    with _db() as conn:
        project = load_project(conn, project_id)
        require_maintainer(project, student)
        conn.execute('UPDATE projects SET is_published=%s, updated_at=%s WHERE id=%s',
                     (value, _now(), project_id))
    return {'message': 'Project published.' if value else 'Project is now private. Nothing was deleted.',
            'public_url': f"{_cfg['frontend']}/project.html?id={project_id}"}


@router.post('/api/projects/{project_id}/publish')
def publish_project(project_id: str, student=Depends(require_verified)):
    return _set_published(project_id, student, 1)


@router.post('/api/projects/{project_id}/unpublish')
def unpublish_project(project_id: str, student=Depends(require_verified)):
    return _set_published(project_id, student, 0)


# ---------------------------------------------------------------- invitations

class Invite(BaseModel):
    github_username: str = Field(min_length=1, max_length=39)
    role: str


@router.post('/api/projects/{project_id}/invitations')
def invite(project_id: str, payload: Invite, student=Depends(require_verified)):
    role = canonical_role(payload.role)
    username = payload.github_username.strip().lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}', username):
        raise HTTPException(422, 'Enter a GitHub username, for example octocat.')
    with _db() as conn:
        project = load_project(conn, project_id)
        require_maintainer(project, student)
        target = conn.execute(
            '''SELECT id, name FROM students WHERE github_id IS NOT NULL AND is_algoma_verified=1
               AND lower(github_link)=lower(%s)''', ('https://github.com/' + username,)).fetchone()
        if not target:
            raise HTTPException(404, 'No verified ImmXrsive student uses that GitHub username. Ask them to sign in and verify first.')
        if target['id'] == student['id']:
            raise HTTPException(422, 'You are already on this project.')
        existing = membership(conn, project_id, target['id'])
        if existing and existing['status'] in ('accepted', 'invited'):
            raise HTTPException(409, f"{target['name']} is already {existing['status']} on this project.")
        if existing and existing['status'] == 'removed':
            raise HTTPException(409, 'This contributor was removed. Use Restore instead of a new invitation.')
        if existing:
            conn.execute('''UPDATE project_contributors SET status='invited', role=%s, invited_by=%s, updated_at=%s
                            WHERE project_id=%s AND student_id=%s''',
                         (role, student['id'], _now(), project_id, target['id']))
        else:
            conn.execute('''INSERT INTO project_contributors (project_id,student_id,role,status,statement,featured,invited_by,updated_at)
                            VALUES (%s,%s,%s,'invited','',1,%s,%s)''',
                         (project_id, target['id'], role, student['id'], _now()))
    return {'message': f"Invitation sent to {target['name']}. They appear publicly only after accepting."}


class InviteResponse(BaseModel):
    accept: bool


@router.post('/api/projects/{project_id}/respond')
def respond(project_id: str, payload: InviteResponse, student=Depends(require_verified)):
    with _db() as conn:
        load_project(conn, project_id)
        m = membership(conn, project_id, student['id'])
        if not m or m['status'] != 'invited':
            raise HTTPException(404, 'There is no open invitation for you on this project.')
        conn.execute('UPDATE project_contributors SET status=%s, updated_at=%s WHERE project_id=%s AND student_id=%s',
                     ('accepted' if payload.accept else 'declined', _now(), project_id, student['id']))
    return {'message': 'Invitation accepted. Add your contribution statement.' if payload.accept else 'Invitation declined.'}


class JoinRequest(BaseModel):
    role: str


@router.post('/api/projects/{project_id}/join')
def request_join(project_id: str, payload: JoinRequest, student=Depends(require_verified)):
    role = canonical_role(payload.role)
    with _db() as conn:
        project = load_project(conn, project_id)
        if not project.get('maintainer_id'):
            raise HTTPException(409, 'This project has no maintainer on the platform yet, so join requests cannot be reviewed.')
        m = membership(conn, project_id, student['id'])
        if m and m['status'] in ('accepted', 'invited', 'requested', 'removed'):
            raise HTTPException(409, f"You are already {m['status']} on this project.")
        if m:
            conn.execute('''UPDATE project_contributors SET status='requested', role=%s, updated_at=%s
                            WHERE project_id=%s AND student_id=%s''', (role, _now(), project_id, student['id']))
        else:
            conn.execute('''INSERT INTO project_contributors (project_id,student_id,role,status,statement,featured,updated_at)
                            VALUES (%s,%s,%s,'requested','',1,%s)''', (project_id, student['id'], role, _now()))
    return {'message': 'Join request sent to the project maintainer.'}


class Decision(BaseModel):
    approve: bool


@router.post('/api/projects/{project_id}/requests/{student_id}')
def decide_request(project_id: str, student_id: str, payload: Decision, student=Depends(require_verified)):
    with _db() as conn:
        project = load_project(conn, project_id)
        require_maintainer(project, student)
        m = membership(conn, project_id, student_id)
        if not m or m['status'] != 'requested':
            raise HTTPException(404, 'No pending join request from that student.')
        conn.execute('UPDATE project_contributors SET status=%s, updated_at=%s WHERE project_id=%s AND student_id=%s',
                     ('accepted' if payload.approve else 'declined', _now(), project_id, student_id))
    return {'message': 'Request approved.' if payload.approve else 'Request declined.'}


# ---------------------------------------------------------------- contributor self-control

class MyContribution(BaseModel):
    role: str
    statement: str = Field(default='', max_length=1000)
    featured: bool = True


@router.put('/api/projects/{project_id}/my-contribution')
def update_my_contribution(project_id: str, payload: MyContribution, student=Depends(require_verified)):
    """Each contributor controls only their own row; there is no route that lets
    anyone else write another person's statement."""
    role = canonical_role(payload.role)
    with _db() as conn:
        load_project(conn, project_id)
        m = membership(conn, project_id, student['id'])
        if not m or m['status'] != 'accepted':
            raise HTTPException(403, 'Only accepted contributors can edit their contribution.')
        conn.execute('''UPDATE project_contributors SET role=%s, statement=%s, featured=%s, updated_at=%s
                        WHERE project_id=%s AND student_id=%s''',
                     (role, payload.statement.strip(), int(payload.featured), _now(), project_id, student['id']))
    return {'message': 'Your contribution was saved.' + ('' if payload.featured else ' The project is hidden from your portfolio but you remain a contributor.')}


# ---------------------------------------------------------------- maintainer: remove / restore / transfer

@router.post('/api/projects/{project_id}/contributors/{student_id}/remove')
def remove_contributor(project_id: str, student_id: str, student=Depends(require_verified)):
    with _db() as conn:
        project = load_project(conn, project_id)
        require_maintainer(project, student)
        if student_id == student['id']:
            raise HTTPException(422, 'Transfer maintenance to another contributor before leaving.')
        m = membership(conn, project_id, student_id)
        if not m or m['status'] not in ('accepted', 'invited'):
            raise HTTPException(404, 'That student is not an active contributor or invitee.')
        new_status = 'removed' if m['status'] == 'accepted' else 'cancelled'
        conn.execute('''UPDATE project_contributors SET status=%s, removed_by=%s, updated_at=%s
                        WHERE project_id=%s AND student_id=%s''',
                     (new_status, student['id'], _now(), project_id, student_id))
    if new_status == 'cancelled':
        return {'message': 'Invitation cancelled.'}
    return {'message': 'Contributor hidden from the project. The relationship is kept and can be restored.'}


@router.post('/api/projects/{project_id}/contributors/{student_id}/restore')
def restore_contributor(project_id: str, student_id: str, student=Depends(require_verified)):
    with _db() as conn:
        project = load_project(conn, project_id)
        require_maintainer(project, student)
        m = membership(conn, project_id, student_id)
        if not m or m['status'] != 'removed':
            raise HTTPException(404, 'Nothing to restore for that student.')
        conn.execute('''UPDATE project_contributors SET status='accepted', removed_by=NULL, updated_at=%s
                        WHERE project_id=%s AND student_id=%s''', (_now(), project_id, student_id))
    return {'message': 'Contributor restored with their original role and statement.'}


class Transfer(BaseModel):
    student_id: str


@router.post('/api/projects/{project_id}/transfer')
def transfer(project_id: str, payload: Transfer, student=Depends(require_verified)):
    with _db() as conn:
        project = load_project(conn, project_id)
        require_maintainer(project, student)
        m = membership(conn, project_id, payload.student_id)
        if not m or m['status'] != 'accepted' or payload.student_id == student['id']:
            raise HTTPException(422, 'Maintenance can only move to another accepted contributor.')
        conn.execute('UPDATE projects SET maintainer_id=%s, updated_at=%s, version=version+1 WHERE id=%s',
                     (payload.student_id, _now(), project_id))
    return {'message': 'Maintenance transferred. The project keeps the same page and URL.'}


# ---------------------------------------------------------------- signed-in views

@router.get('/api/my/projects')
def my_projects(student=Depends(require_verified)):
    with _db() as conn:
        rows = conn.execute(
            '''SELECT p.id, p.title, p.is_published, p.maintainer_id, c.role, c.status, c.statement, c.featured
               FROM project_contributors c JOIN projects p ON p.id=c.project_id
               WHERE c.student_id=%s ORDER BY p.title''', (student['id'],)).fetchall()
        requests_rows = conn.execute(
            '''SELECT c.project_id, p.title, c.student_id, s.name, c.role FROM project_contributors c
               JOIN projects p ON p.id=c.project_id JOIN students s ON s.id=c.student_id
               WHERE p.maintainer_id=%s AND c.status='requested' ''', (student['id'],)).fetchall()
    projects, invitations = [], []
    for r in rows:
        item = {'id': r['id'], 'title': r['title'], 'published': bool(r['is_published']),
                'is_maintainer': r['maintainer_id'] == student['id'], 'role': r['role'],
                'status': r['status'], 'statement': r['statement'] or '', 'featured': bool(r['featured'])}
        (invitations if r['status'] == 'invited' else projects).append(item)
    return {'projects': projects, 'invitations': invitations,
            'join_requests': [dict(x) for x in requests_rows]}


@router.get('/api/my/projects/{project_id}')
def my_project_detail(project_id: str, student=Depends(require_verified)):
    with _db() as conn:
        project = load_project(conn, project_id)
        m = membership(conn, project_id, student['id'])
        is_maintainer = project.get('maintainer_id') == student['id']
        if not is_maintainer and not m:
            raise HTTPException(403, 'You are not part of this project.')
        out = project_core(project, repos_for(conn, project_id))
        rows = contributor_rows(conn, project_id)
    out['version'] = project['version']
    out['is_maintainer'] = is_maintainer
    out['my_status'] = m['status'] if m else None
    visible = rows if is_maintainer else [c for c in rows if c['status'] == 'accepted' or c['student_id'] == student['id']]
    out['contributors'] = [{
        'student_id': c['student_id'], 'name': c.get('name') or 'Student', 'role': c['role'],
        'status': c['status'], 'statement': c['statement'] or '', 'featured': bool(c['featured']),
        'is_maintainer': c['student_id'] == project.get('maintainer_id'), 'is_me': c['student_id'] == student['id'],
    } for c in visible]
    return out
