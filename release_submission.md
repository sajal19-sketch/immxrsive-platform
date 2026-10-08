# ImmXrsive Talent Platform - Release 1

**Team Members:**

* Sajal Patel
* Dhruv Panchani
* Harshit piyushkumar Patel

**GitHub Repository:**
https://github.com/sajal19-sketch/immxrsive-platform

**Live Frontend (GitHub Pages):**
https://sajal19-sketch.github.io/immxrsive-platform/

**Live Backend (Render):**
https://immxrsive-api.onrender.com

**Notes for Evaluator:**

* Backend API deployed via Render.
* Frontend deployed via GitHub pages.
* Synthetic JSON data is populated and searchable. Mobile responsiveness (390px) and keyboard accessibility implemented.


---

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

The correct frozen commit is:
142be5ba8e125181c560559a2c0eda24858b921e

The directory was modified after the release freeze on October 6, 2026. Peer QA reviewed the newer deployed version.

The original R1-submission tag remains unchanged.

Post-freeze fixes do not replace the frozen submission.

### Updated Deployment

Frontend:
https://sajal19-sketch.github.io/immxrsive-platform/

Backend:
https://immxrsive-api.onrender.com

Fix verification commit:
d9299a0804a653366982fcffc70015047c60113c
