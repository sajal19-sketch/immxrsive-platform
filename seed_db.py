"""Idempotent fixture import for Supabase PostgreSQL.

Run ONLY with your private DATABASE_URL locally, after the API has created tables.
Does not copy OTPs, sessions, legacy emails, or automatically claim profile ownership.
"""
import argparse
import json
import os
import sqlite3
from pathlib import Path

import psycopg


def load_fixtures(base):
    base = Path(base)
    students = json.loads((base / 'students_2.json').read_text())
    projects = json.loads((base / 'projects_2.json').read_text())
    return students, projects


def import_fixture_data(conn, students, projects):
    counts = {'students': 0, 'projects': 0, 'contributors': 0}
    for s in students:
        if s.get('profile_status') != 'published':
            continue
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO students
                (id, name, headline, program, status, availability, skills, github_link, project_ids,
                 is_published, is_algoma_verified)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0)
                ON CONFLICT (id) DO NOTHING''',
                (s['id'], s.get('name'), s.get('headline'), s.get('program'), s.get('status'),
                 json.dumps(s.get('availability', [])), json.dumps(s.get('skills', [])),
                 (s.get('links') or {}).get('github', ''), json.dumps(s.get('project_ids', []))))
            counts['students'] += cur.rowcount
    for p in projects:
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO projects (id,title,description,domain,technologies)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING''',
                (p['id'],p.get('title'),p.get('description'),p.get('domain'),json.dumps(p.get('technologies', []))))
            counts['projects'] += cur.rowcount
            for c in p.get('contributors', []):
                cur.execute('''INSERT INTO project_contributors(project_id,student_id,role)
                    VALUES (%s,%s,%s) ON CONFLICT (project_id,student_id,role) DO NOTHING''',
                    (p['id'],c['student_id'],c.get('role','')))
                counts['contributors'] += cur.rowcount
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--fixtures', default='data', help='directory containing students_2.json and projects_2.json')
    p.add_argument('--apply', action='store_true', help='required to write to PostgreSQL')
    a = p.parse_args()
    students, projects = load_fixtures(a.fixtures)
    published = sum(s.get('profile_status') == 'published' for s in students)
    print(f'Fixture source: {published} published students, {len(projects)} projects')
    if not a.apply:
        print('Dry run only. Re-run with --apply to insert missing fixtures.')
        return
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL environment variable required')
    with psycopg.connect(url, connect_timeout=10) as conn:
        print('Inserted (existing IDs are preserved):', import_fixture_data(conn,students,projects))


if __name__ == '__main__':
    main()
