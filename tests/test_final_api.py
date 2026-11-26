"""Final Release API checks against a real, disposable PostgreSQL database.

Run locally (never against production), on an EMPTY database:
    createdb imx_final_test
    DATABASE_URL=postgresql://localhost/imx_final_test \
      STAFF_BOOTSTRAP_USERNAME=staff.test STAFF_BOOTSTRAP_PASSWORD=Local-Test-Pass-2026 \
      python tests/test_final_api.py

Each check is named after the Final Peer QA scenario (A-K) and requirement (F.xx)
it covers. R1-R4 regression is in tests/test_r4_api.py (run it too).
"""
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('FRONTEND_URL', 'http://localhost:8080')
os.environ.setdefault('GITHUB_CLIENT_ID', 'x')
os.environ.setdefault('GITHUB_CLIENT_SECRET', 'y')
# The legacy fixture's addresses use algoma.example; allow it here so the
# automatic-claim path (exact verified-email match) can be exercised.
os.environ['APPROVED_EMAIL_DOMAINS'] = 'algomau.ca,algoma.example'

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import seed_db  # noqa: E402

FIX = ROOT / 'fixtures' / 'final'
PASSED = []


def check(name, cond, detail=''):
    if not cond:
        raise AssertionError(f'FAIL {name}: {detail}')
    PASSED.append(name)
    print('  ok ', name)


def account(conn, sid, name, email, verified=1, github=None):
    """A signed-in student account (what GitHub sign-in + R2.04 verification creates)."""
    conn.execute('''INSERT INTO students (id,name,headline,skills,availability,project_ids,status,is_published,
                    github_id,github_link,is_algoma_verified,email,claim_state,publication,talent_mode)
                    VALUES (%s,%s,'Student profile draft','[]','[]','[]','Current',0,%s,%s,%s,%s,'owned','unpublished','showcase')''',
                 (sid, name, str(abs(hash(sid)) % 10**9), 'https://github.com/' + (github or sid), verified, email))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO auth_sessions VALUES (%s,%s,'2099-01-01T00:00:00+00:00')", (main.hash_token(token), sid))
    return {'Authorization': 'Bearer ' + token}


def leaks(payload, needles):
    text = json.dumps(payload)
    return [n for n in needles if n in text]


def run():
    legacy = json.loads((FIX / 'legacy_export.json').read_text())
    expected = json.loads((FIX / 'legacy_expected_results.json').read_text())
    scale = json.loads((FIX / 'scale_fixture.json').read_text())
    with TestClient(main.app) as api:
        with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as conn:
            s, p = seed_db.load_fixtures(ROOT / 'data')
            seed_db.import_fixture_data(conn, s, p)
            ana = account(conn, 'u_ana', 'Ana Claimant', 'ana@algomau.ca')
            ben = account(conn, 'u_ben', 'Ben Student', 'ben@algomau.ca')
            avery = account(conn, 'u_avery', 'Avery Chen', 'avery.chen@algoma.example')
            dk = account(conn, 'u_dk', 'Daniel Kim', 'dkim@algomau.ca', github='daniel-kim')
        login = api.post('/api/staff/login', json={'username': os.environ['STAFF_BOOTSTRAP_USERNAME'],
                                                   'password': os.environ['STAFF_BOOTSTRAP_PASSWORD']})
        assert login.status_code == 200, login.text
        staff = {'Authorization': 'Bearer ' + login.json()['access_token']}

        def db():
            return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)

        def sid(legacy_id):
            with db() as c:
                return c.execute('SELECT id FROM students WHERE legacy_id=%s', (legacy_id,)).fetchone()['id']

        def pid(legacy_id):
            with db() as c:
                return c.execute('SELECT id FROM projects WHERE legacy_id=%s', (legacy_id,)).fetchone()['id']

        def cid(legacy_id):
            with db() as c:
                return c.execute('SELECT id FROM companies WHERE legacy_id=%s', (legacy_id,)).fetchone()['id']

        print('Scenario C - Legacy migration / claim')
        r = api.post('/api/staff/migrations', headers=ben, json={'data': legacy})
        check('C0 F.01 student cannot run migration', r.status_code == 403, r.status_code)
        r = api.post('/api/staff/migrations', headers=staff, json={'data': legacy, 'dry_run': True, 'expected': expected})
        check('C1 F.03 dry run reports without writing', r.status_code == 200 and r.json()['acceptance']['all_pass'], r.text[:300])
        with db() as c:
            check('C1 dry run left no legacy rows', c.execute('SELECT count(*) n FROM students WHERE legacy_id IS NOT NULL').fetchone()['n'] == 0)
        first = api.post('/api/staff/migrations', headers=staff, json={'data': legacy, 'expected': expected}).json()
        check('C2 F.01 import applies', first['results']['students']['created'] == 6, first['results'])
        check('C2 F.03 acceptance against legacy_expected_results.json', first['acceptance']['all_pass'], first['acceptance'])
        check('C2 F.03 duplicate LS04~LS01 reported', any(d['legacy_id'] == 'LS04' and d['possible_duplicate_of'] == 'LS01'
                                                          for d in first['duplicate_candidates']))
        check('C2 F.03 broken LP02->LS99 reported, not invented',
              any(b.get('student_legacy_id') == 'LS99' for b in first['broken_references']))
        second = api.post('/api/staff/migrations', headers=staff, json={'data': legacy}).json()
        created = sum(v['created'] for v in second['results'].values())
        check('C3 F.02 re-import creates nothing', created == 0, second['results'])
        check('C3 F.02 re-import reports skipped counts', second['results']['students']['skipped'] == 6, second['results'])
        with db() as c:
            n = c.execute("SELECT count(*) n FROM projects WHERE legacy_id='LP01'").fetchone()['n']
        check('C4 F.04 shared legacy project exists exactly once', n == 1, n)
        check('C4 same-title R1 project reported for review, not merged by name',
              any(m['entity'] == 'project' and m['legacy_id'] == 'LP01' for m in first['existing_platform_matches']))
        lp01 = api.get(f"/api/projects/{pid('LP01')}").json()
        names = sorted(x['name'] for x in lp01['contributors'])
        check('C4 F.04 LP01 has both intended contributors', names == ['Avery Chen', 'Daniel Kim'], names)
        check('C4 F.04 legacy roles kept', sorted(x['role'] for x in lp01['contributors']) == ['Interaction Developer', 'XR Developer'])
        check('C5 F.06 internal id is not the legacy id', not sid('LS01').startswith('LS'))
        ls02 = api.get(f"/api/students/{sid('LS02')}").json()
        check('C6 F.07 imported profile public while unclaimed', ls02['name'] == 'Daniel Kim' and ls02['claimed'] is False)
        check('C6 F.20 legacy email not in public profile', not leaks(ls02, ['@alumni.example', 'daniel.kim']))
        runs = api.get('/api/staff/migrations', headers=staff).json()
        check('C7 migration runs are recorded with counts', len(runs) >= 3 and 'students' in runs[0]['counts'])

        # ---- claims
        r = api.post('/api/claims', headers=ana, json={'profile_id': sid('LS02'), 'note': 'This is my old profile'})
        check('C8 F.08 ambiguous claim goes to staff review', r.status_code == 201 and r.json()['status'] == 'pending', r.text)
        claim_id = r.json()['id']
        with db() as c:
            row = c.execute('SELECT github_id FROM students WHERE id=%s', (sid('LS02'),)).fetchone()
        check('C8 F.08 pending claim grants nothing', row['github_id'] is None)
        r = api.put('/api/profile/talent', headers=ana, json={'mode': 'active'})
        me = api.get('/api/auth/me', headers=ana).json()
        check('C8 claimant still edits only their own account', me['id'] == 'u_ana', me)
        r = api.post('/api/claims', headers=dk, json={'profile_id': sid('LS05')})
        check('C9 F.09 same-name/GitHub handle is not auto-approved', r.json()['status'] == 'pending', r.text)
        r = api.post('/api/claims', headers=ben, json={'profile_id': sid('LS01')})
        check('C9 F.09 any Algoma address is not enough', r.json()['status'] == 'pending', r.text)
        ben_claim = r.json()['id']
        r = api.post('/api/claims', headers=avery, json={'profile_id': sid('LS01')})
        check('C10 F.08 exact verified-email match auto-approves', r.json()['status'] == 'auto_approved', r.text)
        me = api.get('/api/auth/me', headers=avery).json()
        check('C10 auto-claimed account now signs in as the legacy profile', me['id'] == sid('LS01') and me['verified'], me)
        r = api.post(f'/api/staff/claims/{ben_claim}/decision', headers=staff, json={'approve': True})
        check('C10 a claim on an owned profile cannot be approved', r.status_code in (404, 409), r.status_code)
        pending = api.get('/api/staff/claims', headers=staff).json()
        check('C11 staff see pending claims with match signals', any(x['id'] == claim_id and 'signals' in x for x in pending))
        r = api.post(f'/api/staff/claims/{claim_id}/decision', headers=ben, json={'approve': True})
        check('C11 F.21 student cannot decide claims', r.status_code == 403)
        r = api.post(f'/api/staff/claims/{claim_id}/decision', headers=staff, json={'approve': False})
        check('C11 rejection needs a note', r.status_code == 422)
        r = api.post(f'/api/staff/claims/{claim_id}/decision', headers=staff, json={'approve': True, 'note': 'Confirmed by alumni office'})
        check('C12 F.10 staff approve claim', r.status_code == 200, r.text)
        me = api.get('/api/auth/me', headers=ana).json()
        check('C12 claimant now owns the legacy profile', me['id'] == sid('LS02') and me['verified'], me)
        r = api.get('/api/students/u_ana')
        check('C12 claimant draft account was not deleted (redirect or 404 for an unpublished draft)', r.status_code in (200, 404))
        r = api.post(f"/api/staff/students/{sid('LS02')}/owner", headers=staff, json={'action': 'release', 'note': 'wrong person'})
        check('C13 F.10 staff can release ownership', r.status_code == 200 and api.get('/api/auth/me', headers=ana).status_code == 401)
        r = api.post(f"/api/staff/students/{sid('LS02')}/owner", headers=staff,
                     json={'action': 'assign', 'account_id': 'u_dk', 'note': 'recovered to the right owner'})
        check('C13 F.10 staff can reassign ownership to the right account', r.status_code == 200, r.text)
        check('C13 reassigned owner signs in as that profile', api.get('/api/auth/me', headers=dk).json()['id'] == sid('LS02'))
        r = api.post('/api/claims', headers=ben, json={'profile_id': sid('LS02')})
        check('C14 owned profile cannot be claimed', r.status_code == 404)

        print('Scenario B - Student/alumni lifecycle')
        r = api.post(f"/api/staff/students/{sid('LS01')}/lifecycle", headers=staff, json={'status': 'Alumni', 'note': 'graduated'})
        check('B1 F.11 staff set alumni status', r.status_code == 200, r.text)
        prof = api.get(f"/api/students/{sid('LS01')}").json()
        check('B2 F.11 graduation does not retire the portfolio', prof.get('status') == 'Alumni' and not prof.get('retired'))
        me = api.get('/api/auth/me', headers=avery).json()
        check('B3 F.12 verified affiliation persists after alumni change', me['verified'] is True, me)
        r = api.put('/api/students/update', headers=avery, json={'name': 'Avery Chen', 'availability': ['internship'], 'skills': []})
        check('B3 F.12 alumni can still edit without re-verifying', r.status_code == 200, r.text)
        check('B4 F.14 LS01 (confirmed 2026-08-01) is Active Talent', prof['talent_state'] == 'active' and prof['availability'] == ['internship'], prof)
        ls02 = api.get(f"/api/students/{sid('LS02')}").json()
        check('B5 F.14 LS02 (confirmed 2024-06-01) is stale, not shown as available',
              ls02['talent_state'] == 'stale' and ls02['availability'] == [] and ls02['last_stated_availability'] == ['full-time'], ls02)
        ls05 = api.get(f"/api/students/{sid('LS05')}").json()
        check('B6 F.13 no availability = Showcase Only', ls05['talent_state'] == 'showcase' and ls05['availability'] == [])
        r = api.put('/api/profile/talent', headers=avery, json={'mode': 'showcase'})
        prof = api.get(f"/api/students/{sid('LS01')}").json()
        check('B7 F.13 student switches to Showcase Only', prof['talent_state'] == 'showcase' and prof['availability'] == [])
        api.put('/api/profile/talent', headers=avery, json={'mode': 'active'})
        r = api.post('/api/profile/availability/confirm', headers=dk)
        ls02 = api.get(f"/api/students/{sid('LS02')}").json()
        check('B8 F.14 reconfirming makes stale availability current', ls02['talent_state'] == 'active' and ls02['availability'] == ['full-time'], ls02)
        api.post(f"/api/staff/students/{sid('LS02')}/lifecycle", headers=staff, json={'availability_confirmed_at': '2024-06-01'})
        check('B8 staff test tool can set the confirmation date back',
              api.get(f"/api/students/{sid('LS02')}").json()['talent_state'] == 'stale')

        print('Scenario A - Employer acceptance')
        t = api.get('/api/talent', params={'skills': [], 'availability': ['internship'], 'talent': 'active'}).json()
        ids = {x['id'] for x in t['items']}
        check('A1 Active Talent + internship finds LS01', sid('LS01') in ids, ids)
        t = api.get('/api/talent', params={'availability': ['full-time']}).json()
        check('A5 F.13/F.14 stale full-time LS02 not presented as available', sid('LS02') not in {x['id'] for x in t['items']})
        t = api.get('/api/talent', params={'q': 'unclaimed alum'}).json()
        check('A5 showcase profile still browsable', [x['talent_state'] for x in t['items']] == ['showcase'], t['items'])
        r = api.post('/api/inquiries', json={'name': 'E', 'company': 'Co', 'email': 'e@co.example', 'message': 'Hi',
                                             'role_type': 'Internship', 'source_type': 'student', 'source_id': sid('LS01')})
        check('A4 inquiry keeps student context', r.status_code == 201, r.text)

        print('Scenario D - Duplicate / recovery')
        ls04 = sid('LS04')
        check('D0 duplicate LS04 was publicly reachable before merge', api.get(f'/api/students/{ls04}').status_code == 200)
        with db() as c:
            c.execute("INSERT INTO project_contributors (project_id,student_id,role,status,statement,featured) "
                      "VALUES (%s,%s,'Software Developer','accepted','Built the quest engine',1)", (pid('LP02'), ls04))
        dupes = api.get('/api/staff/duplicates', headers=staff).json()
        check('D1 duplicate queue lists LS04~LS01 and LC02~LC01',
              {d['entity'] for d in dupes} >= {'student', 'company'}, dupes)
        r = api.post('/api/staff/students/merge', headers=ben, json={'survivor_id': sid('LS01'), 'duplicate_id': ls04})
        check('D1 F.21 student cannot merge', r.status_code == 403)
        r = api.post('/api/staff/students/merge', headers=staff, json={'survivor_id': sid('LS01'), 'duplicate_id': ls04, 'note': 'same email'})
        check('D1 F.17 staff merge duplicate student', r.status_code == 200, r.text)
        lp02 = api.get(f"/api/projects/{pid('LP02')}").json()
        avery_row = [c for c in lp02['contributors'] if c['student_id'] == sid('LS01')]
        check('D2 F.17 relationship moved to survivor with statement intact',
              avery_row and avery_row[0]['statement'] == 'Built the quest engine', lp02['contributors'])
        old = api.get(f'/api/students/{ls04}').json()
        check('D3 F.18 old URL leads to survivor', old.get('moved') and old['moved_to'] == sid('LS01'), old)
        with db() as c:
            dangling = c.execute('SELECT count(*) n FROM project_contributors WHERE student_id=%s AND status<>%s', (ls04, 'merged')).fetchone()['n']
        check('D3 F.17 no dangling references to merged record', dangling == 0, dangling)
        rerun = api.post('/api/staff/migrations', headers=staff, json={'data': legacy}).json()
        check('D3 F.02 re-import after merge does not resurrect LS04', rerun['results']['students']['created'] == 0)
        r = api.post('/api/staff/companies/merge', headers=staff, json={'survivor_id': cid('LC01'), 'duplicate_id': cid('LC02')})
        check('D3 F.17 staff merge duplicate company', r.status_code == 200, r.text)
        part = api.get(f"/api/partners/{cid('LC01')}").json()
        check('D3 F.05 merged partner keeps current and past history',
              {x['title'] for x in part['past']} >= {'Industrial Safety Training', 'Legacy Brand Event'} and part['current'], part)
        old = api.get(f"/api/partners/{cid('LC02')}").json()
        check('D3 F.18 old partner id leads to survivor', old.get('moved_to') == cid('LC01'), old)
        lp01 = pid('LP01')
        before = api.get(f'/api/projects/{lp01}').json()
        r = api.post(f'/api/staff/projects/{lp01}/maintainer', headers=staff, json={'student_id': 'u_ben', 'note': 'x'})
        check('D4 new maintainer must be an accepted contributor or given a role', r.status_code == 422, r.text)
        r = api.post(f'/api/staff/projects/{lp01}/maintainer', headers=staff, json={'student_id': sid('LS02'), 'note': 'previous maintainer graduated'})
        check('D4 F.19 staff assign new maintainer', r.status_code == 200, r.text)
        after = api.get(f'/api/projects/{lp01}').json()
        check('D5 F.19 same project id, contributors unchanged',
              after['id'] == lp01 and len(after['contributors']) == len(before['contributors']) and
              {c['role'] for c in after['contributors']} == {c['role'] for c in before['contributors']})
        mine = api.get(f'/api/my/projects/{lp01}', headers=dk).json()
        check('D5 new maintainer can maintain', mine['is_maintainer'] is True)
        detail = api.get(f'/api/staff/projects/{lp01}', headers=staff).json()
        check('D5 maintainer history recorded', len(detail['maintainer_history']) == 1)

        print('Scenario E - Privacy / authorization regression')
        lc03 = cid('LC03')
        pubs = [api.get('/api/partners').json(), api.get(f'/api/partners/{lc03}').json(),
                api.get(f"/api/projects/{pid('LP02')}/industry").json(), api.get(f"/api/projects/{pid('LP02')}").json()]
        check('E1 F.20 private collaboration absent from public responses', not leaks(pubs, ['Confidential Prototype']), pubs)
        everyone = api.get('/api/directory', params={'limit': 100}).json()
        talent = api.get('/api/talent', params={'limit': 48}).json()
        details = [api.get(f"/api/students/{x['id']}").json() for x in everyone]
        check('E1 F.20 no email or legacy email in any public profile response',
              not leaks([everyone, talent, details], ['@algomau.ca', '@algoma.example', '@alumni.example', '@example.test', 'legacy_email']))
        check('E1 F.20 no GitHub identity id in public responses', not leaks([everyone, details], ['github_id', 'is_algoma_verified']))
        r = api.get(f'/api/my/projects/{lp01}', headers=ben)
        check('E2 F.21 non-member cannot read project workspace', r.status_code == 403)
        r = api.put(f'/api/projects/{lp01}/my-contribution', headers=ben, json={'role': 'QA/Tester', 'statement': 'x'})
        check('E3 F.21 another student cannot write a contribution statement', r.status_code == 403)
        r = api.put(f'/api/projects/{lp01}', headers=ben, json={'title': 'hijack', 'version': 1})
        check('E3 F.21 non-maintainer cannot edit shared fields', r.status_code == 403)
        for path, body in ((f"/api/staff/students/{sid('LS01')}/lifecycle", {'status': 'Current'}),
                           (f'/api/staff/projects/{lp01}/maintainer', {'student_id': 'u_ben', 'note': 'take'}),
                           (f"/api/staff/students/{sid('LS01')}/owner", {'action': 'release', 'note': 'take'})):
            check(f'E4 F.21 student blocked from {path.split("/")[3]} staff action', api.post(path, headers=ben, json=body).status_code == 403)
        check('E4 F.21 student cannot read diagnostics', api.get('/api/staff/diagnostics', headers=ben).status_code == 403)
        check('E4 F.21 staff token rejected on student routes', api.get('/api/profile/me', headers=staff).status_code == 401)

        print('Scenario G - Scale')
        small = api.get('/api/talent')
        small_bytes = len(small.content)
        r = api.post('/api/staff/migrations', headers=staff, json={'data': scale, 'source_name': 'scale_fixture.json'})
        rep = r.json()
        check('G0 F.27 scale fixture imported through the same importer',
              rep['results']['students']['created'] == 220 and rep['results']['projects']['created'] == 110, rep['results'])
        big = api.get('/api/talent')
        bj = big.json()
        check('G1 F.27 directory now holds 200+ published profiles', bj['facets']['total_published'] >= 200, bj['facets'])
        check('G1 F.28 first load returns one page only', len(bj['items']) == 24, len(bj['items']))
        check('G1 F.28 first-load bytes do not grow with the dataset',
              len(big.content) < small_bytes * 2.5, (small_bytes, len(big.content)))
        heavy = {'hero_media', 'playable_url', 'video_url', 'fallback_url', 'bio', 'education', 'experience'}
        check('G2 F.28/F.29 cards carry no media, demo or long-text fields', not (heavy & set(bj['items'][0])), set(bj['items'][0]))
        d = api.get('/api/directory')
        check('G2 F.28 R1 /api/directory contract stays an array but bounded',
              isinstance(d.json(), list) and len(d.json()) == 50 and int(d.headers['x-total-count']) >= 200)
        want_openxr = sum(1 for x in scale['students'] if x['publication'] == 'published' and 'OpenXR' in x['skills'])
        f = api.get('/api/talent', params={'skills': ['OpenXR'], 'limit': 48}).json()
        check('G3 skill filter still uses structured skills at scale',
              f['total'] >= want_openxr and all('OpenXR' in x['skills'] for x in f['items']), (f['total'], want_openxr))
        p2 = api.get('/api/talent', params={'page': 2}).json()
        check('G3 pagination returns the next page', p2['page'] == 2 and {x['id'] for x in p2['items']}.isdisjoint({x['id'] for x in bj['items']}))
        again = api.post('/api/staff/migrations', headers=staff, json={'data': scale}).json()
        check('G4 F.02 scale re-import creates nothing', sum(v['created'] for v in again['results'].values()) == 0, again['results'])

        print('Scenario H/I - External failure, playable hardening')
        with db() as c:
            c.execute("UPDATE projects SET maintainer_id='u_ben' WHERE id=%s", (pid('LP03'),))
            c.execute("INSERT INTO project_contributors (project_id,student_id,role,status) VALUES (%s,'u_ben','QA/Tester','accepted') ON CONFLICT DO NOTHING", (pid('LP03'),))
        lp03 = pid('LP03')
        cur = api.get(f'/api/my/projects/{lp03}', headers=ben).json()
        body = {'title': cur['title'], 'version': cur['version'], 'playable_url': 'javascript:alert(1)', 'demo_type': 'embed'}
        check('I0 F.36 non-https demo link refused', api.put(f'/api/projects/{lp03}', headers=ben, json=body).status_code == 422)
        body.update(playable_url='https://sajal19-sketch.github.io/immxrsive-platform/demo/working_demo.html', demo_type='<iframe>')
        check('I0 F.36 demo type must be a known value, never markup', api.put(f'/api/projects/{lp03}', headers=ben, json=body).status_code == 422)
        body.update(demo_type='embed', fallback_url='https://sajal19-sketch.github.io/immxrsive-platform/demo/fallback.svg',
                    fallback_text='Screenshot of the training demo')
        r = api.put(f'/api/projects/{lp03}', headers=ben, json=body)
        check('I1 F.36 structured embed saved', r.status_code == 200, r.text)
        pub = api.get(f'/api/projects/{lp03}').json()
        check('I1 public project exposes demo type and state, not markup', pub['demo_type'] == 'embed' and pub['demo_state'] == 'available')
        r = api.post(f'/api/projects/{lp03}/demo-state', headers=ben, json={'demo_state': 'unavailable', 'demo_note': 'Build is being rebuilt'})
        check('I4 F.37 maintainer marks demo unavailable', r.status_code == 200)
        pub = api.get(f'/api/projects/{lp03}').json()
        check('I4 F.37 project and fallback survive a broken build',
              pub['demo_state'] == 'unavailable' and pub['fallback_url'] and pub['contributors'], pub)
        r = api.post(f'/api/staff/projects/{lp03}/demo-state', headers=staff, json={'demo_state': 'replaced'})
        check('I4 replaced state needs a replacement link', r.status_code == 422)
        r = api.post(f'/api/projects/{lp03}/demo-state', headers=dk, json={'demo_state': 'archived'})
        check('I4 F.21 only the maintainer changes demo state', r.status_code == 403)
        r = api.post('/api/staff/company-imports', headers=staff, json={'url': 'https://does-not-exist.invalid/'})
        check('H1 F.31 failed company import gives a readable error and manual path',
              r.json().get('status') == 'failed' and r.json()['error'] and 'by hand' in r.json()['message'], r.text)
        r = api.get('/api/github/repo', headers=ben, params={'url': 'not a repo'})
        check('H2 F.31 invalid GitHub repo gives a readable error', r.status_code == 422 and 'GitHub' in r.json()['detail'])
        check('H3 F.30 public browsing unaffected after failures', api.get('/api/talent').status_code == 200 and
              api.get(f'/api/projects/{lp01}').status_code == 200)
        diag = api.get('/api/staff/diagnostics', headers=staff).json()
        check('H4 F.32 integration failure recorded for staff', any(e['kind'] == 'company_import' for e in diag['events']), diag['events'][:3])
        check('H4 F.32 diagnostics show configuration presence only', set(diag['configured']) >= {'github_oauth', 'verification_email'}
              and not leaks(diag, ['Local-Test-Pass', 'Bearer ']))
        r = api.get('/api/talent')
        check('H4 F.32 every response carries a request id', len(r.headers.get('x-request-id', '')) == 12)

        print('Scenario J - Industry history / retirement')
        lp03pub = api.get(f'/api/projects/{lp03}').json()
        check('J1 F.16 retired contributor keeps credit on shared project',
              any('Retired Contributor' in c['name'] and c['student_id'] is None for c in lp03pub['contributors']), lp03pub['contributors'])
        ret = api.get(f"/api/students/{sid('LS06')}").json()
        check('J2 F.15 retired profile is archived, not deleted', ret.get('retired') is True and ret['projects'], ret)
        check('J2 F.15 retired profile not in the directory', sid('LS06') not in {x['id'] for x in api.get('/api/directory', params={'q': 'retired', 'limit': 100}).json()})
        r = api.post('/api/profile/retire', headers=avery)
        check('J3 F.15 student can retire own portfolio', r.status_code == 200)
        lp01pub = api.get(f'/api/projects/{lp01}').json()
        check('J3 F.16 retiring does not remove shared project or contributor', any('Avery' in c['name'] for c in lp01pub['contributors']))
        part = api.get(f"/api/partners/{cid('LC01')}").json()
        check('J4 F.16 partner history still lists the project after retirement', any(p['id'] == lp01 for p in part['related_projects']))
        r = api.post('/api/profile/publish', headers=avery)
        check('J5 retired portfolio can be published again', api.get(f"/api/students/{sid('LS01')}").json().get('talent_state'))

    print(f'\nAll {len(PASSED)} checks passed.')


if __name__ == '__main__':
    run()
