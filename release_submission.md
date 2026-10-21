# Release 2 — ImmXrsive Project Option 1

**Team:** Sajal Patel / Dhruv Panchani / Harshit Patel (confirm roster)  
**Release:** R2  
**Project Option:** Project 1 — ImmXrsive Talent and Industry Platform  
**Frontend:** https://sajal19-sketch.github.io/immxrsive-platform/  
**Backend:** https://immxrsive-api.onrender.com  
**Repository:** https://github.com/sajal19-sketch/immxrsive-platform  
**Assessed tag:** `R2-submission`  
**Reported frozen SHA:** `9792ba312dee462887c46f71327ca88f0c5b5493` — **verify against GitHub; not independently verified.**

## Critical version distinction

The original R2 Product Result deadline was October 16, 2026. This package contains **post-freeze candidate repairs**, not the frozen release. Do not move the original assessed tag. Record GitHub Issues, later repair commit(s), deployment timestamps, and retest evidence separately for Engineering Response to QA. Do not imply these repairs alter the frozen product grade.

## Release notes (repair candidate)

- GitHub OAuth with backend internal identity, short-lived state/ticket and bearer session.
- Algoma verification with configurable approved domains and OTP expiry/attempt protections.
- Owned private drafts, standardized skills source, resume PDF candidate extraction and explicit suggestion review.
- Public API excludes unpublished profiles and hides student-controlled availability and links.
- Preview, publish/unpublish and public controlled theme presets.
- Four supplied PDF fixtures exercised by local API tests.

## Test accounts, assumptions and privacy

Peer student uses their own GitHub account and `@algomau.ca` email; actual OTP and OAuth values stay private. Course instructor may need to authorize email-delivery test mode if Resend cannot deliver to course addresses; no such approval is assumed. Backend secrets must be supplied as Render environment variables, never GitHub. GitHub Pages serves root-level `login.html`, `upload.html`, and `editor.html`. Data should persist across restarts by using an approved persistent database service. Retain imported R1 fixture data.

**Public data:** published only. An owner can hide availability and professional links; those values are withheld in public API responses. Original PDF data is not saved as a file by parser code. Input custom text is rendered with `textContent`, not arbitrary HTML.

## Known issues / not yet demonstrated

1. Existing Algoma email record conflicts with newly signed-in GitHub identity (HTTP 409); needs a verified, authorized administrative recovery workflow; do not bypass ownership checks.
2. Render Free service using a local SQLite file may lose writes during redeploy/restart. Durable database persistence has not been configured/verified in this package.
3. R1 canonical standardized skills and fixture data must remain in repository `data/`; package cannot certify their current live state.
4. Complex-layout PDF sections can be under-extracted; human review and manual entry remain available.
5. GitHub OAuth return, email delivery, mobile/keyboard review and fully deployed public workflow have not been end-to-end tested in this environment.
6. Original frozen SHA and reviewer Issues access require confirmation by the team.

## Release-specific evidence

- `evaluation_adapter.json`: route/role/fixture mapping for R2 scenarios, **not pass evidence**.
- `TEST_RESULTS.md`: local tests executed on a temporary SQLite database and the four instructor fixtures.
- `DEPLOY_AND_RETEST.md`: deployment and peer QA checklist.

**Do not submit this repaired file as if it described the originally frozen build.** Adapt the original R2 submission evidence accurately and cite subsequent repairs separately.
