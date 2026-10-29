# ImmXrsive Talent Platform 

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
**Commit SHA:** `<PASTE FULL SHA OF THE R3-submission COMMIT>`
**Project Option:** Project 1
**Release notes / known issues / team decisions:** [RELEASE_NOTES_R3.md](RELEASE_NOTES_R3.md)
**Evaluation adapter:** [evaluation_adapter.json](evaluation_adapter.json) (release R3)

**QA evidence**
- Shared published project with 2+ accepted contributors: `<PASTE URL>`
- Project with working demo and fallback: `<PASTE URL>`
- Public repository used for GitHub import: `<PASTE URL>`
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
