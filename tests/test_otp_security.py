"""Local-only OTP endpoint tests for the SQLite main.py in this project.

Run from project root: python -m pytest -q tests/test_otp_security.py
Never use production credentials. Each test creates its own temporary database.
"""
import importlib
import os
import secrets
import sqlite3
import sys
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    # This specific version of main.py reads DATABASE_PATH at import time.
    # Force a new empty SQLite file and remove connection settings for safety.
    path = tmp_path / 'only_this_test.sqlite3'
    monkeypatch.setenv('DATABASE_PATH', str(path))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('APPROVED_EMAIL_DOMAINS', 'algomau.ca')
    monkeypatch.setenv('OTP_EXPIRY_MINUTES', '10')
    if 'main' in sys.modules:
        module = importlib.reload(sys.modules['main'])
    else:
        module = importlib.import_module('main')
    assert os.path.abspath(module.DB_PATH) == os.path.abspath(str(path)), 'Refusing non-test database'
    module.setup_db()

    student_id = 'test_otp_student'
    test_email = 'test-only@algomau.ca'
    token = secrets.token_urlsafe(32)
    with module.db() as conn:
        conn.execute('''INSERT INTO students
            (id, name, headline, status, skills, availability, project_ids,
             is_published, is_algoma_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)''',
            (student_id, 'Test Only', 'Test', 'current', '[]', '[]', '[]'))
        conn.execute('INSERT INTO auth_sessions (token_hash, student_id, expires_at) VALUES (?, ?, ?)',
            (module.hash_token(token), student_id, module.stamp(module.now() + timedelta(hours=1))))
    sent = []
    monkeypatch.setattr(module, 'send_verification_email', lambda address, code: sent.append((address, code)))
    client = TestClient(module.app)
    headers = {'Authorization': f'Bearer {token}'}

    def request():
        return client.post('/api/request-verification', json={'email': test_email}, headers=headers)

    def verify(code):
        return client.post('/api/verify-code', json={'email': test_email, 'code': code}, headers=headers)

    yield module, client, path, student_id, test_email, sent, request, verify
    client.close()


def test_request_and_successful_verification(env):
    module, _, _, sid, email, sent, request, verify = env
    assert request().status_code == 200
    assert len(sent) == 1 and sent[0][0] == email
    result = verify(sent[0][1]); assert result.status_code == 200, result.text
    with module.db() as conn:
        student = conn.execute('SELECT is_algoma_verified FROM students WHERE id=?', (sid,)).fetchone()
        challenge = conn.execute('SELECT * FROM otp_challenges WHERE student_id=?', (sid,)).fetchone()
    assert student['is_algoma_verified'] == 1
    assert challenge is None


def test_used_code_cannot_be_reused(env):
    _, _, _, _, _, sent, request, verify = env
    assert request().status_code == 200
    assert verify(sent[-1][1]).status_code == 200
    assert verify(sent[-1][1]).status_code != 200


def test_expired_code_rejected_and_deleted(env):
    module, _, _, sid, _, sent, request, verify = env
    assert request().status_code == 200
    with module.db() as conn:
        conn.execute('UPDATE otp_challenges SET expires_at=? WHERE student_id=?',
                     (module.stamp(module.now() - timedelta(seconds=1)), sid))
    response = verify(sent[-1][1])
    assert response.status_code == 400, response.text
    with module.db() as conn:
        challenge = conn.execute('SELECT 1 FROM otp_challenges WHERE student_id=?', (sid,)).fetchone()
    assert challenge is None, 'Expired challenge was not deleted (transaction may have rolled back)'


def test_wrong_code_count_and_lockout(env):
    module, _, _, sid, _, sent, request, verify = env
    assert request().status_code == 200
    correct = sent[-1][1]
    wrong = '999999' if correct != '999999' else '888888'
    for attempt in range(1, 6):
        response = verify(wrong)
        assert response.status_code == 400, (attempt, response.status_code, response.text)
        with module.db() as conn:
            recorded = conn.execute('SELECT attempts FROM otp_challenges WHERE student_id=?', (sid,)).fetchone()
        assert recorded['attempts'] == attempt
    locked = verify(correct)
    assert locked.status_code == 429, locked.text


def test_sixth_code_request_rate_limited(env):
    module, _, _, sid, _, sent, request, _ = env
    for _ in range(5):
        response = request()
        assert response.status_code == 200, response.text
    response = request()
    assert response.status_code == 429, response.text
    assert len(sent) == 5, 'Rate-limited request must not send an email'
    with module.db() as conn:
        row = conn.execute('SELECT requests FROM verification_rate WHERE student_id=?', (sid,)).fetchone()
    assert row['requests'] == 5


def test_unverified_other_student_cannot_read_otp(env):
    # The verification endpoints must not expose the raw code or its bcrypt hash.
    _, _, _, _, _, sent, request, _ = env
    response = request()
    assert response.status_code == 200
    assert sent[-1][1] not in response.text
    assert 'otp_hash' not in response.text
