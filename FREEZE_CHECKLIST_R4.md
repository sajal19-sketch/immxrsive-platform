# R4 freeze checklist (do this on the DEPLOYED site before clicking Submit)

Peer reviewers test only the deployed site, never a local copy.

1. Merge `release-4` into `main` and push. GitHub Pages and Render then redeploy.
2. On Render → Environment, add `STAFF_BOOTSTRAP_USERNAME`, `STAFF_BOOTSTRAP_PASSWORD`
   (12+ characters) and `STAFF_BOOTSTRAP_NAME`, then redeploy. Do **not** set
   `ALLOW_LOCAL_IMPORTS` on Render.
3. In a fresh private window, check:
   - each fixture URL in RELEASE_NOTES_R4.md opens (GitHub Pages can take a few minutes);
   - `admin.html` staff sign-in works;
   - importing `company_normal.html` gives North Shore Simulations.
4. Create the evidence on the live site:
   - publish North Shore Simulations (imported, one field edited);
   - add COL01 (2025, Past, Public, Industrial Safety VR Trainer) and COL02
     (2026, Current, Public, XR Anatomy Lab) to it;
   - import Superior Immersive Labs (prompt-injection page), save it as a draft,
     and add COL03 (2026, Current, **Private**);
   - from a student project you maintain, send one partner request and approve
     it (pending → staff review).
5. **Leave work waiting for Scenario A:** one project verification request, one
   student partner request, and one draft company (e.g. Algoma Field Systems).
6. Check that reviewers and the instructor can open the repository and create
   issues.
7. Tag the frozen commit: `git tag R4-submission && git push origin R4-submission`.
8. Fill the placeholders in `release_submission.md` (commit SHA, evidence links),
   then upload `release_submission.md` + `evaluation_adapter.json` to Moodle and
   click **Submit**. A draft is not a submission.
9. Send the staff username and password privately (instructor QA email thread).
   Never put them in GitHub.
