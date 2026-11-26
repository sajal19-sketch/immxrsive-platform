# ImmXrsive — Final Release launch notes

Release question: *could this replace the existing ImmXrsive public site and keep
working as students, projects, partners and external systems change?*

The Final release is hardening of what R1–R4 built. Nothing from earlier releases
was removed, and every schema change is additive (`ADD COLUMN IF NOT EXISTS`,
`CREATE TABLE IF NOT EXISTS`). Most of the new code is in `final_release.py`. The
staff screens are in `staff-ops.html`.

## Where each requirement lives

| Area | Requirements | Where |
|---|---|---|
| Repeatable legacy import with a report | F.01–F.03 | Staff → Operations → Legacy migration (`staff-ops.html#migrate`, `POST /api/staff/migrations`), or `scripts/migrate_legacy.py`. Both run `final_release.run_import`. |
| Shared project, partner history, stable ids | F.04–F.06 | Migrated projects keep every resolvable contributor. Collaborations keep current/past and visibility. Every record has a generated internal id plus a separate `legacy_id`. |
| Unclaimed profiles and claims | F.07–F.10 | Public profile shows "Is this you? Claim it" → `editor.html` claim section (`POST /api/claims`). Staff: Operations → Profile claims, and Students → Ownership recovery. |
| Alumni, availability, lifecycle | F.11–F.16 | Student: `editor.html` → Status and availability. Staff: Operations → Students → Lifecycle. Public: `talent_state` on profiles and directory cards. |
| Duplicate merge, redirects, maintainer recovery | F.17–F.19 | Operations → Duplicates; Operations → Projects & maintainers. Old ids are in `record_redirects`. |
| Privacy and authorization regression | F.20–F.23 | Server-side serializers (`public_profile`, `public_collaboration`). Staff routes reject student sessions. Secrets: see Known issues. |
| Accessibility and mobile | F.24–F.26 | All new controls are labelled native elements with visible focus. Form errors name the field. Checked at 390 px. |
| Scale and bounded loading | F.27–F.29 | `GET /api/talent` (24 cards per page, server-side search/filters/facets). `GET /api/directory` is capped at 50 per page and returns `X-Total-Count`. No media, resume or demo in listings. |
| External failure and diagnostics | F.30–F.32 | Readable errors with a reference id. Operations → Diagnostics (`GET /api/staff/diagnostics`). Timestamped access log with a request id. |
| Playable/XR hardening | F.33–F.38 | `project.html`: explicit Launch, sandboxed frame, WebXR capability check with fallback, demo states (available / unavailable / archived / replaced), Close/Escape. |
| Launch evidence | F.39–F.41 | This file, `tests/`, `evidence/final/`, tag `FINAL-submission`. |

## Team decisions

**Migration (F.01–F.06)**
- One importer for every path: the staff screen, the command-line tool and the scale fixture all call `run_import`. Scale data goes into the same tables and is read by the same directory query as any other profile.
- Records match on `legacy_id` only. Re-running the export reports `skipped` (or `updated` when a legacy value changed) and creates nothing. A record that staff merged stays merged on re-import.
- Problems are reported, not fixed silently. LP02's contributor LS99 does not exist, so that relationship is not created and it appears under *Broken references*. LS04 shares LS01's email and appears under *Duplicate candidates* and in the staff duplicate queue. LC02 (`www.` + the same domain as LC01) is held as a draft and queued as a duplicate company.
- Matching on a name alone is never treated as identity. The R1 seed data already holds people and projects with the same names as legacy records (Avery Chen, Maya Patel, Daniel Kim, "XR Anatomy Lab", "Museum Quest Experience"). These are listed under *Matches with records already on the platform* and queued for staff review, never merged automatically.
- A legacy company whose website domain matches a partner staff already created in R4 (North Shore Simulations, Superior Immersive Labs) is linked to that partner. The staff-entered details are kept.
- Legacy partners were public on the old site, so they import as published. Scale-fixture partners import as drafts.
- A *limited* legacy collaboration with no public summary gets the neutral text "A confidential collaboration with an industry partner." Private collaborations are never public.

**Claims (F.07–F.10)**
- Imported profiles have no GitHub identity. Their legacy email is stored in `legacy_email` and is never in any public response.
- A claim is approved automatically only when the address the claimant verified (R2.04) exactly matches the legacy record's address. Every other claim waits for staff.
- Staff see context signals (exact match, same domain) with the note that these are not proof. Rejecting a claim requires a note for the student.
- Approving moves the claimant's sign-in onto the imported profile. Their empty draft account is kept, marked as merged, with a redirect. Projects, requests and sessions move to the profile, and nothing is deleted.
- Staff can remove a wrong owner or assign the profile to the right verified account. Both need a written justification and are kept in the profile history.
- The legacy fixture's addresses (`@algoma.example`, `@alumni.example`, `@example.test`) are not approved verification domains in production, so every claim of a fixture profile goes to staff review. The automatic path is covered by `tests/test_final_api.py` (check C10).

**Lifecycle (F.11–F.16)**
- *Status* (Current/Alumni), *publication* (published/unpublished/retired) and *talent mode* (Active Talent/Showcase Only) are separate columns.
- Changing a student to Alumni never touches publication or `is_algoma_verified`. Sign-in for alumni works as before.
- Availability is shown as current only when the mode is Active Talent and the last-confirmed date is within 365 days. Otherwise the profile shows "last confirmed … may be out of date" (stale) or "not confirmed", and it is excluded from availability filters and the Active Talent filter.
- Students confirm availability with a button, or by changing their availability and saving.
- Retiring is not deletion. A retired profile leaves the directory, but its URL shows an archived page with its project history. Shared projects keep the person's name and role, marked "(portfolio archived)". Collaborations are untouched.

**Merges and recovery (F.17–F.19)**
- Merging moves project memberships (statements kept), maintainer roles, collaboration links, partner/verification requests, inquiries and pending claims to the record that is kept.
- The other record is kept with `merged_into` set, and its id gets a redirect. Old student and partner URLs show "This profile was combined with …" and then go to the surviving record.
- A record that has its own sign-in cannot be merged away. Staff remove the owner first, or keep that record as the survivor.
- New maintainer: staff choose an accepted contributor with a verified account, or add a verified student with a standard role. The project id, URL, contributors, roles and statements are unchanged, and the change is written to `maintainer_history`.

**Playable demos (F.33–F.38)**
- Owners give a link and a type: *opens in a new tab*, *embedded web build* or *WebXR*. Markup is never stored or rendered.
- Embedded builds load only after **Launch**, inside `<iframe sandbox="allow-scripts allow-pointer-lock">`. There is no `allow-same-origin`, so a build cannot read the visitor's session or act as them.
- Camera, microphone and XR permissions are delegated only to a WebXR build, and only when it launches. WebXR first checks `navigator.xr.isSessionSupported('immersive-vr')`. If that fails, the visitor sees the fallback with an option to try the browser version.
- **Close demo** and Escape unload the frame and return focus. "Not working? Show preview" swaps in the fallback.

**Diagnostics (F.32)**
- Every response carries `X-Request-ID`, and the server log has one timestamped line per request: method, path, status, duration.
- Query strings, headers and bodies are not logged, because OAuth codes and tokens travel there.
- Unexpected errors return "Something went wrong on our side… Reference: <id>" and are stored in `diagnostic_events`. So are integration failures: GitHub import and sign-in, verification email, company import and migration. Staff read them in Operations → Diagnostics, which also shows which integrations are configured (yes/no only).

## Migration: how to run it

On the deployed site (staff):
1. Sign in at `admin.html` and open **Operations → Legacy migration**.
2. Choose **Legacy export (legacy_export.json)**. Keep *Preview only* ticked and press **Run migration** to see the report.
3. Untick *Preview only* and run again to apply. The acceptance table compares the run with `legacy_expected_results.json`.
4. Repeat with **Scale fixture (scale_fixture.json)** to load the scale data.

Command line (same code):

```bash
DATABASE_URL=... python scripts/migrate_legacy.py fixtures/final/legacy_export.json --expected fixtures/final/legacy_expected_results.json          # preview
DATABASE_URL=... python scripts/migrate_legacy.py fixtures/final/legacy_export.json --apply --expected fixtures/final/legacy_expected_results.json  # apply
DATABASE_URL=... python scripts/migrate_legacy.py fixtures/final/scale_fixture.json --apply
```

The fixtures in `fixtures/final/` are byte-for-byte copies of the Moodle files (`SHA256SUMS`).

**Migration result (supplied fixture):** `evidence/final/migration_console_log.txt` and `evidence/final/legacy_migration_report.json`.
- First run: 6 students, 3 projects, 3 companies and 4 collaborations created; 4 contributor links created and 1 broken link reported.
- Duplicate LS04~LS01 (same email) and LC02~LC01 (same domain) detected. Broken reference LP02→LS99 reported. LS02, LS05 and LS06 left unclaimed. All four acceptance checks pass.
- Second run: everything skipped, nothing created (`legacy_migration_rerun_report.json`).
- The run on the deployed database is listed with its report under Operations → Legacy migration → Previous runs.

## Scale evidence (F.27–F.29)

`evidence/final/scale_payload_before.json` and `scale_payload_after.json`:

| Database | First directory load | Cards | Bytes |
|---|---|---|---|
| R1 seed (17 published profiles) | `GET /api/talent` | 17 | 8,103 |
| After scale fixture (230 published) | `GET /api/talent` | 24 (page 1 of 10) | 10,509 |

- Cards carry only short fields (no bio, resume, hero image, video, demo or fallback URL).
- The skill filter at scale returns exactly the published fixture students who list that skill.
- The directory page makes one API request. Project pages fetch no demo or video until Launch. The fallback image loads lazily.

## Automated tests

Both suites run against a real, disposable PostgreSQL database (never production):

- `tests/test_r4_api.py`: 76 checks (R4 scenarios plus R1–R3 regression). **All passed.**
- `tests/test_final_api.py`: 106 checks named after Final QA scenarios A–J and F.xx. **All passed.**

The browser walk-through used Chrome against a local copy with the migration and scale fixture loaded:
- Directory paging and filters, stale/showcase/retired profile views.
- Merged-URL redirect, staff duplicate merge, claims screen, migration preview report and diagnostics.
- Embedded demo launch/Escape/focus return, WebXR fallback, and archived contributor credit.
- 390 px with no horizontal scroll on the directory and editor. No unlabelled inputs on the editor.

## Team regression checklist (R1–R4 journeys, F.39)

| Journey | How checked | Result |
|---|---|---|
| R1 directory search (`,` AND, `|` OR), status/availability filters, profile page, project page, inquiry | test_final A1/A4/G3, browser | Pass. The search syntax is now evaluated on the server. |
| R2 GitHub sign-in, Algoma email verification, private draft, preview, publish/unpublish, resume suggestions, untrusted PDF text | test_r4 R2 checks, test_final B3 | Pass. Publish/unpublish now also set `publication`. |
| R3 shared projects, invitations, contributor-owned statements, soft remove/restore, transfer, stale-version 409, GitHub import, demo + fallback | test_r4 R3 checks, test_final E3/I0–I4 | Pass. Demo links gained a type and a state. |
| R4 staff sign-in, verification, website import (R4.10), partner publish, collaborations and visibility, partner requests, contextual inquiries | test_r4 (76) | Pass |
| Public pages at 390 px; keyboard on directory, profile form, project contribution, staff review | browser | Pass (native controls, visible focus, labelled) |

## Known issues and limitations

1. **Secrets in public git history (F.23).** A GitHub OAuth client secret (commits `0741b7b`, `8c0dc0f`, Oct 20–21) and a Gmail app password (`0741b7b`, `0459f20`, Oct 20) were committed during R2. Current code reads every secret from environment variables, and none is in browser-delivered files. The history still contains the old values, so they must be revoked: regenerate the GitHub OAuth client secret and revoke the Gmail app password, then update Render. We did not rewrite history because that would break the R1–R4 tags. *Status at freeze: the GitHub OAuth client secret was regenerated and the Gmail app password revoked on Nov 26, 2026; the new values exist only in Render environment variables, so the old values in history no longer work.*
2. Legacy records with the same name as R1 seed profiles/projects are queued for staff review rather than merged (see Decisions). Until staff decide, the directory shows both.
3. Scale-fixture students have no availability confirmation date. They show "Availability not confirmed" and are excluded from Active Talent filters by design.
4. Profiles that existed before this release had no confirmation date. Their current availability was marked confirmed on the deploy date (`availability_confirmed_source = 'existing profile at Final release'`). Profiles from this term are well within 365 days.
5. An embedded demo is cross-origin, so the page cannot detect a 404 page inside it. The visitor sees the build's own error page, with **Close demo** and **Not working? Show preview** always available.
6. Merging is available for students and partners, not projects. Same-title projects are reported for review only.
7. Directory filtering runs on the server over the published rows in Python. This is fine for hundreds of profiles; thousands would need SQL-side filtering. `diagnostic_events` has no automatic pruning.
8. The Render free tier sleeps. The first request can take up to a minute, and pages show a "waking up" message.
9. The staff Operations page is designed for desktop. The 390 px requirement covers the public and student journeys.
10. The migration report's `source_sha256` hashes the parsed JSON content, so whitespace-only changes give the same hash. File byte hashes are in `fixtures/final/SHA256SUMS`.

## Operational note

- **Deployment.** Push to `main`. GitHub Pages serves the static site (`/immxrsive-platform/`), and Render redeploys the FastAPI service (`uvicorn main:app`). Schema changes apply on API startup and are additive only. Rollback means redeploying a previous commit, since no data migration is destructive.
- **Configuration (Render environment, never committed):** `DATABASE_URL`, `FRONTEND_URL`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_SENDER_EMAIL`, `APPROVED_EMAIL_DOMAINS`, `STAFF_BOOTSTRAP_USERNAME`, `STAFF_BOOTSTRAP_PASSWORD`, `STAFF_BOOTSTRAP_NAME`, optional `GITHUB_API_TOKEN`. `config.js` contains only the public API URL.
- **External dependencies.** GitHub OAuth and the GitHub REST API (sign-in, repository import), the Gmail API (verification codes), company websites (R4 import), externally hosted demos and videos, and PostgreSQL. If any of these fails, only the workflow that uses it fails, with a readable message and a manual path. Browsing and saved records keep working.
- **Diagnostics.** Staff → Operations → Diagnostics shows stored failures (time, kind, route, status, reference, short detail) and which integrations are configured. The Render logs have the matching timestamped line for each request id. Users see the same reference id in error messages, so a report like "Reference 3f2a…" can be looked up directly.
