# Testing Release 4 on your own computer (before pushing)

Everything here runs on your Mac only. Nothing touches Render, GitHub Pages or
the real database.

## One-time setup (Mac)

```bash
cd ~/immxrsive-platform
source venv/bin/activate
pip install -r requirements.txt            # adds google-auth etc. if missing
brew install postgresql@16                 # skip if you already have PostgreSQL
brew services start postgresql@16
createdb imx_local
```

## Start it

```bash
cd ~/immxrsive-platform && source venv/bin/activate
./scripts/run_local.sh                     # leave this running
```

In a second Terminal tab, load the R1 fixture students and projects once:

```bash
cd ~/immxrsive-platform && source venv/bin/activate
DATABASE_URL=postgresql://localhost/imx_local python3 seed_db.py --apply
```

## Try the R4 journeys

1. **Staff:** open http://localhost:8080/admin.html and sign in with
   `staff.local` / `Local-Only-Pass-2026` (local only).
2. **Import partner from website:** paste
   `http://127.0.0.1:8080/fixtures/r4/company_normal.html`. Edit a field, save
   the draft, tick "I reviewed…", then Publish. Repeat with `company_sparse.html`,
   `company_prompt_injection.html` (look for "Untrusted text ignored") and
   `company_same_name_other_domain.html`.
3. **Collaborations:** on the published partner, add a Past and a Current one,
   then a Limited and a Private one. Open http://localhost:8080/partners.html in a
   private window: the private one must not appear, and the limited one shows
   only its summary.
4. **Student:** GitHub sign-in can't work on localhost, so make a test student:
   ```bash
   DATABASE_URL=postgresql://localhost/imx_local python3 scripts/local_dev_student.py ana "Ana Maintainer"
   ```
   Paste the printed `sessionStorage.setItem(...)` line into the browser console
   on http://localhost:8080. Then open My Projects, create a project, and use
   **Request verification** and **Industry partners**. Back in the staff home,
   review both.
5. **Public:** on the partner page, click "Ask about this collaboration" and send
   an inquiry. It appears in the staff **Inquiries** with its source.

## Automated checks

```bash
createdb imx_r4_test
# with run_local.sh still running (it serves the fixtures on :8080):
DATABASE_URL=postgresql://localhost/imx_r4_test ALLOW_LOCAL_IMPORTS=1 \
STAFF_BOOTSTRAP_USERNAME=staff.test STAFF_BOOTSTRAP_PASSWORD=Local-Test-Pass-2026 \
python3 tests/test_r4_api.py
```
Expected last line: `All 76 checks passed.`
