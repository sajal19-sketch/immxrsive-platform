# Release Submission — ImmXrsive Talent Platform

Release: FINAL
Team: team-10 (Sajal Patel, Dhruv Panchani, Harshit Piyushkumar Patel)
Project Option: Project 1
Deployment: https://sajal19-sketch.github.io/immxrsive-platform/ (frontend) · https://immxrsive-api.onrender.com (API)
Repository: https://github.com/sajal19-sketch/immxrsive-platform
Release tag: FINAL-submission
Commit: __FINAL_SHA__
Adapter: evaluation_adapter.json
Known issues: see RELEASE_NOTES_FINAL.md → "Known issues and limitations" (secrets in early git history must be rotated; legacy records with the same name as R1 seed records are queued for staff review rather than merged; scale-fixture students have no availability confirmation date; cross-origin demos cannot report a 404 to the parent page)
Test notes: Staff tools are at admin.html → Operations (staff-ops.html). The legacy export and the scale fixture were applied on the deployed database through Operations → Legacy migration, and the reports are under Previous runs. The API sleeps when idle, so the first request can take up to a minute.

## Test accounts

- **Staff/admin:** one staff test account. Sign in at `admin.html`, then open **Operations**.
  The username and password are only in the Online text of our Moodle Final Product Result
  submission, under *Reviewer test access*. They are not in this repository.
- **Student / contributor / claimant:** reviewers sign in with their own GitHub account
  (`login.html`) and verify their own @algomau.ca email, as in R2–R4. To test a claim,
  claim an imported synthetic profile, for example "Daniel Kim" (alumni) or "Unclaimed Alum".
  The staff account then approves or rejects it. To test maintainer/contributor flows,
  create a project under My Projects.
- **Public visitor / employer:** no account. Use a private window.

## Release-specific evidence

- Migration command/tool/instructions: RELEASE_NOTES_FINAL.md → "Migration: how to run it".
  - Staff screen: https://sajal19-sketch.github.io/immxrsive-platform/staff-ops.html#migrate
  - CLI: `scripts/migrate_legacy.py`
- Migration result report for the supplied legacy fixture: `evidence/final/migration_console_log.txt`,
  `evidence/final/legacy_migration_report.json`, and the re-run in `evidence/final/legacy_migration_rerun_report.json`.
  The acceptance checks against `legacy_expected_results.json` all pass.
- Release/launch notes and known issues: [RELEASE_NOTES_FINAL.md](RELEASE_NOTES_FINAL.md)
- Scale-fixture test: `evidence/final/scale_payload_before.json`, `scale_payload_after.json`, `scale_import_report.json`.
  The first directory load is 24 cards and about 10 KB with 17 or 230 profiles.
- Completed team regression checklist: RELEASE_NOTES_FINAL.md → "Team regression checklist".
- Automated checks: `tests/test_r4_api.py` (76, R1–R4 regression) and `tests/test_final_api.py`
  (106, Final scenarios A–J). All passed on a disposable local PostgreSQL database.
- Fixtures: `fixtures/final/` holds byte-for-byte copies of the Moodle Final fixtures (`SHA256SUMS`).

## Operational note (Final Release only)

- **Deploy:** push to `main`. GitHub Pages serves the static pages and Render redeploys the FastAPI API.
  Schema changes run at API startup and are additive only. Roll back by redeploying an earlier commit.
- **Configuration:** Render environment variables only (database, GitHub OAuth, Gmail API,
  approved email domains, staff bootstrap account). The browser receives only the public API URL (`config.js`).
- **External dependencies:** GitHub (sign-in, repository import), Gmail API (verification codes),
  company websites (partner import), externally hosted demos/videos, PostgreSQL. If one fails,
  only its own workflow fails, with a readable message and a manual path.
- **Diagnostics:** Staff → Operations → Diagnostics shows failed integrations and server errors
  with time, route, status, short detail and a reference id. The same id is in the response
  header `X-Request-ID`, in user-facing error messages and in the timestamped Render log line.
  Secrets, tokens, codes and form contents are never logged.

---

## Release 4 (frozen R4 evidence, unchanged)

Chosen challenge: R4.10 - Untrusted Website Content


Release: R4
Team: team-10 (Sajal Patel, Dhruv Panchani, Harshit Piyushkumar Patel)
Project Option: Project 1
Deployment: https://sajal19-sketch.github.io/immxrsive-platform/ (frontend) · https://immxrsive-api.onrender.com (API)
Repository: https://github.com/sajal19-sketch/immxrsive-platform
Release tag: R4-submission
Commit: 874302df422bba9a44be84cac71c61daca519d14
Adapter: evaluation_adapter.json
Known issues: see RELEASE_NOTES_R4.md → "Known issues / limits"
Test notes: staff area is https://sajal19-sketch.github.io/immxrsive-platform/admin.html. The API sleeps when idle; the first request can take up to a minute.

## Test accounts

- **Staff/admin (R4.01):** one staff test account, sign in at `admin.html` with a
  username and password. The username and password are in the online text of our
  Moodle Release 4 Product Result submission (not in this public repository).
  Do not try to get staff access any other way.
- **Student maintainer:** reviewers sign in with their own GitHub account
  (`login.html`) and verify their own @algomau.ca email, as in R2–R3. To test the
  student partner request (Scenario I), create a project under My Projects; you
  are its maintainer.
- **Public visitor:** no account. Use an incognito window.

## Release-specific evidence

- Chosen Challenge: **R4.10 – Untrusted Website Content** (details in RELEASE_NOTES_R4.md)
- Fixture source URLs (published unchanged on GitHub Pages):
  - company_normal.html → https://sajal19-sketch.github.io/immxrsive-platform/fixtures/r4/company_normal.html
  - company_sparse.html → https://sajal19-sketch.github.io/immxrsive-platform/fixtures/r4/company_sparse.html
  - company_prompt_injection.html → https://sajal19-sketch.github.io/immxrsive-platform/fixtures/r4/company_prompt_injection.html
  - company_same_name_other_domain.html → https://sajal19-sketch.github.io/immxrsive-platform/fixtures/r4/company_same_name_other_domain.html
  - Setup to repeat an import: staff sign-in → Import partner from website → paste URL → Get details from website.
- Published fixture partner imported from a supplied page: https://sajal19-sketch.github.io/immxrsive-platform/partner.html?id=c_6cf0e9cc392a (North Shore Simulations, imported from company_normal.html, description edited by staff, then published after review)
- Company with at least two collaborations: https://sajal19-sketch.github.io/immxrsive-platform/partner.html?id=c_6cf0e9cc392a (Industrial Safety Training Prototype: 2025, Past, Public, project P01; XR Maintenance Training Study: 2026, Current, Public, project P04; Confidential Pilot: 2026, Current, Limited. Superior Immersive Labs (draft) holds Confidential Spatial Prototype: 2026, Current, Private.)
- Student-requested relationship shown pending → staff review: https://sajal19-sketch.github.io/immxrsive-platform/project.html?id=p_7eb4b3c84a54aaae (ImmXrsive Talent Platform: North Shore Simulations request approved by staff and now shown as Industry partner. A second request, Soo Robotics as a suggested new company, and a project verification request are left pending for reviewers on Staff home.)
- Release notes / known issues: [RELEASE_NOTES_R4.md](RELEASE_NOTES_R4.md)
- Automated evidence: `tests/test_r4_api.py` (76 checks, all passed on a local disposable database)

---

## Earlier releases

### Team and links (from R1–R3) 

**Team Members:**
- Sajal Patel
- Dhruv Panchani
- Harshit piyushkumar Patel

**GitHub Repository:**
https://github.com/sajal19-sketch/immxrsive-platform

**Live Frontend (GitHub Pages):**
https://sajal19-sketch.github.io/immxrsive-platform/

**Live Backend (Render):**
https://immxrsive-api.onrender.com

---

## Release 3 — Shared Projects, Contributor Evidence, Playable Demos

**Release Tag:** R3-submission
**Commit SHA:** a37b83d34ccd9c38a2e358c9d066752b788653b1

_The R3-submission tag points to commit a37b83d, the last commit made before the Release 3 freeze (Oct 29, 2026, 9:56 p.m. Toronto time). No code changes were made after it._
**Project Option:** Project 1
**Release notes / known issues / team decisions:** [RELEASE_NOTES_R3.md](RELEASE_NOTES_R3.md)
**Evaluation adapter:** [evaluation_adapter.json](evaluation_adapter.json) (release R3)

**QA evidence**
- Shared published project with 2+ accepted contributors: https://sajal19-sketch.github.io/immxrsive-platform/project.html?id=p_7eb4b3c84a54aaae
- Project with working demo and fallback: https://sajal19-sketch.github.io/immxrsive-platform/project.html?id=p_7eb4b3c84a54aaae
- Public repository used for GitHub import: https://github.com/sajal19-sketch/immxrsive-platform
- Hosted demo: https://sajal19-sketch.github.io/immxrsive-platform/demo/working_demo.html
- Hosted fallback: https://sajal19-sketch.github.io/immxrsive-platform/demo/fallback.svg

**Test access:** reviewers sign in with their own GitHub account and verify their own @algomau.ca email. No shared passwords; nothing sensitive is in this repository.

---

## Release 2 — Resume Parsing & Security

**Release Tag:** R2-submission
**Commit SHA:**  1f7fba859ab5413a56de8a9afff2a611923b10c6

**Release 2 Notes for Evaluator:**
* **Core Requirements:** Added secure PDF upload and parsing endpoint (`/api/resumes/parse`) via FastAPI and `pypdf`. Implemented frontend interface (`upload.html`) and applied a new multi-page "Interstellar" UI theme.
* **Robustness & Regression:** Verified HTML sanitization successfully neutralizes the `<script>` injection attack from the `resume_untrusted_text.pdf` fixture. R1 directory and profile workflows remain fully intact and operational across the new UI.
* **Test Setup:** No authentication required. Upload page is accessible directly via `upload.html` or the "Upload" link in the navigation bar.

---
### Release 2 SHA Correction

The original Release 2 document recorded commit
9792ba312dee462887c46f71327ca88f0c5b5493.

The correct frozen Release 2 commit is
1f7fba859ab5413a56de8a9afff2a611923b10c6,
as identified by the R2-submission tag.

Both commits were completed before the submission
deadline of October 16, 2026.

This correction is documentation-only.
The original R2-submission tag remains unchanged.

## Release 1 — Post-Freeze Corrections

### Original Frozen Submission
- Tag: R1-submission
- Commit: 142be5ba8e125181c560559a2c0eda24858b921e
- Date: October 2, 2026

We accept the instructor's findings regarding the critical errors in the original frozen submission.

### Corrections Made After the Freeze
1. Directory (index.html)
   - Removed malformed API URL syntax.
   - Corrected directory loading and profile navigation.

2. Student Profile (student.html)
   - Fixed the JavaScript syntax error.
   - Corrected the student API request.
   - Fix commit: 02b7020c77d50e7e09dad231651811fe132af7c6

3. Project Details (project.html)
   - Replaced localhost with the production Render API.
   - Fix commit: 29d95b2f693f41aa76ff651873445b7df27bb02e

### Verification on Updated Deployment
- Student directory keyword search: PASS
- Student profile loading: PASS
- Student profile direct URL in Incognito: PASS
- Project details loading: PASS
- Project contributors displayed: PASS
- Student inquiry form navigation: PASS
- Project inquiry form navigation: PASS

These tests were performed on the updated deployment, not the original frozen release.
Affected requirements: R1.01, R1.04, R1.11, R1.12, R1.13, R1.14, R1.17.

### Known Issues
The employer inquiry form currently simulates submission. It does not send or store an inquiry.
The original frozen release contained critical errors, so the earlier statement that there were no known issues was inaccurate.

### Submission Corrections
The original Moodle submission listed an incorrect commit hash beginning with fc14b549.
The correct frozen commit is: 142be5ba8e125181c560559a2c0eda24858b921e
The directory was modified after the release freeze on October 6, 2026. Peer QA reviewed the newer deployed version.
The original R1-submission tag remains unchanged. Post-freeze fixes do not replace the frozen submission.
