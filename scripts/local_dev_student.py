"""LOCAL TESTING ONLY: create a verified test student and print a sign-in token.

GitHub sign-in cannot work on localhost, so this inserts a test student straight
into a *local* database. It refuses to run against anything but localhost.

    DATABASE_URL=postgresql://localhost/imx_local python3 scripts/local_dev_student.py ana "Ana Maintainer"

Then in the browser console on http://localhost:8080:
    sessionStorage.setItem('imx_token', '<printed token>')
"""
import hashlib
import os
import secrets
import sys
from urllib.parse import urlsplit

import psycopg

url = os.environ.get('DATABASE_URL', '')
host = urlsplit(url).hostname or 'localhost'
if host not in ('localhost', '127.0.0.1', ''):
    sys.exit('Refusing: DATABASE_URL is not a local database.')
handle = sys.argv[1] if len(sys.argv) > 1 else 'localtester'
name = sys.argv[2] if len(sys.argv) > 2 else 'Local Tester'
sid = 'u_local_' + handle
token = secrets.token_urlsafe(32)
with psycopg.connect(url) as conn:
    conn.execute('''INSERT INTO students (id,name,headline,skills,availability,project_ids,status,is_published,
                    github_id,github_link,is_algoma_verified,email)
                    VALUES (%s,%s,'Local test student','[]','[]','[]','Current',1,%s,%s,1,%s)
                    ON CONFLICT (id) DO NOTHING''',
                 (sid, name, str(int(hashlib.sha256(sid.encode()).hexdigest(), 16) % 10**9),
                  'https://github.com/' + handle, handle + '@algomau.ca'))
    conn.execute("INSERT INTO auth_sessions VALUES (%s,%s,'2099-01-01T00:00:00+00:00')",
                 (hashlib.sha256(token.encode()).hexdigest(), sid))
print('Student id:', sid)
print("Paste in the browser console:  sessionStorage.setItem('imx_token', '" + token + "')")
