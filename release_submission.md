Chosen challenge: R4.10 - Untrusted Website Content

# Release Submission — ImmXrsive Talent Platform

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
  username and password. The username and password are sent to reviewers and the
  instructor through the approved private course channel only. Do not try to
  get staff access any other way.
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
