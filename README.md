# ImmXrsive Talent & Industry Platform

COSC3506 Team Project (Project Option 1), team-10: Sajal Patel, Dhruv Panchani, Harshit Piyushkumar Patel.

- **Live site:** https://sajal19-sketch.github.io/immxrsive-platform/
- **API:** https://immxrsive-api.onrender.com (free tier; the first request after idle can take up to a minute)
- **Assessed Final version:** tag `FINAL-submission`

## Start here

| If you are | Read |
|---|---|
| A reviewer or marker | [release_submission.md](release_submission.md), then [RELEASE_NOTES_FINAL.md](RELEASE_NOTES_FINAL.md) |
| Running the legacy migration | RELEASE_NOTES_FINAL.md → "Migration: how to run it" (`scripts/migrate_legacy.py`) |
| An automated evaluator | [evaluation_adapter.json](evaluation_adapter.json) |

Earlier releases: [RELEASE_NOTES_R3.md](RELEASE_NOTES_R3.md), [RELEASE_NOTES_R4.md](RELEASE_NOTES_R4.md), tags `R1-submission` to `R4-submission`.

## Layout

- Static pages (`*.html`, `site.js`, `style.css`) are served by GitHub Pages. `config.js` holds only the public API URL.
- FastAPI backend: `main.py` (R1/R2), `projects_r3.py`, `industry_r4.py`, `final_release.py`, `inquiries.py`, deployed on Render with PostgreSQL.
- Fixtures: `fixtures/r4/`, `fixtures/final/` (byte-for-byte copies of the Moodle files, see `SHA256SUMS`).
- Tests: `tests/test_r4_api.py` and `tests/test_final_api.py`, run against a disposable local PostgreSQL database only.

## Running the tests locally

```bash
pip install -r requirements.txt httpx
export STAFF_BOOTSTRAP_USERNAME=staff.test STAFF_BOOTSTRAP_PASSWORD=<any> STAFF_BOOTSTRAP_NAME="Test Staff"
DATABASE_URL=postgresql://localhost/imx_final_test python tests/test_final_api.py

# R4 suite also needs the fixture pages served locally
python -m http.server 8080 --bind 127.0.0.1 &
ALLOW_LOCAL_IMPORTS=1 DATABASE_URL=postgresql://localhost/imx_r4_test python tests/test_r4_api.py
```

Secrets are configured only as Render environment variables and are never committed.
