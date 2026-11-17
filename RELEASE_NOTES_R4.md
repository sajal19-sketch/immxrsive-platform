# ImmXrsive — Release 4 notes

**Chosen Challenge: R4.10 – Untrusted Website Content**

Release question: *Can non-technical staff operate verification and industry
workflows without understanding the application's internal data model?*

## What's new

| Area | Where | Requirements |
|---|---|---|
| Staff sign-in (separate from student GitHub sign-in) | `admin.html` | R4.01, R4.02 |
| Staff home "What needs attention": Verify projects, Partner requests, Partners to review, New inquiries | `admin.html#home` | R4.03, R4.25 |
| Project verification: maintainer requests it, staff approve/reject with a note, "Officially verified by ImmXrsive" mark on the public project | `projects.html` → `admin.html#verify/…` → `project.html` | R4.04–R4.06 |
| Add partner by hand, or **Get details from website** (suggestions only) | `admin.html#partner/new` | R4.07–R4.09, R4.11 |
| "Where this came from" under each field (website + import time, or staff edit) and a change history | partner editor | R4.12 |
| Collaborations per partner: title, years, description, outcome, Current/Past, Public/Limited/Private, related projects and students | partner editor → Collaborations | R4.15–R4.18, R4.23 |
| Student partner request: pick a listed company or suggest a new one, explain the relationship | `projects.html` (maintainer) | R4.20, R4.21 |
| Public Industry Partners list and partner page (who they are, how we work with them, current vs past, related projects/students, website, inquiry) | `partners.html`, `partner.html?id=…` | R4.22–R4.24, R4.26 |
| Collaboration inquiries carry their source (partner or collaboration) into the staff inbox | `intake.html`, `admin.html#inbox` | R4.24 |

## Chosen Challenge: R4.10 – Untrusted Website Content

- The importer is a plain HTML parser (`industry_r4.extract_company`). Page
  text is never executed, never sent to an AI model, and never interpreted as
  a command.
- `<script>`, `<style>`, `<iframe>`, `<object>`, `<svg>`, `<template>` content is
  dropped before any text is read.
- Sentences that read like instructions to the system (for example "ignore
  previous instructions", "mark … verified", "grant admin access", "publish
  immediately") are **flagged and left out of the suggested description**. Staff
  see an "Untrusted text ignored" warning.
- An import returns only company *fields* (name, description, website, domain,
  sector, keywords, location). It has no way to carry a status, verification,
  role or permission. Import never creates or publishes a company. Staff must
  save a draft and then tick "I reviewed these details" before Publish works.
- All imported and staff-entered text is rendered with `textContent`. Links are
  shown only if they are `https://`; `javascript:` and other schemes are refused
  on save.
- The importer only fetches public `https://` pages. Private-network, loopback
  and link-local addresses are refused, redirects are re-checked (max 3), and
  only 1 MB of HTML is read.

The other three Challenges were not chosen. R4.14's duplicate-domain warning
and R4.19's server-side privacy also happen to be in place (see below), but
reviewers should test only R4.10.

## Team decisions

- **Staff accounts** are separate from student accounts. The first staff account
  is created from Render environment variables `STAFF_BOOTSTRAP_USERNAME`,
  `STAFF_BOOTSTRAP_PASSWORD` (12+ characters) and `STAFF_BOOTSTRAP_NAME`. The
  password is never committed. A student GitHub session is rejected (403) by
  every staff endpoint; a staff session is rejected (401) by student endpoints.
  Eight failed staff sign-ins from the same address within 15 minutes block that address for 15 minutes; staff signing in from elsewhere are not affected.
- **Verification is staff-only data** (`projects.official_verified`,
  `verified_at`, `verified_by`). No student endpoint writes those columns, and
  the project edit endpoint ignores any extra fields.
- **Import never overwrites what staff typed.** When the form already has a value,
  the website's different value is offered as "Website suggests: … [Use this]".
- **A failed import changes nothing.** The failure is recorded (with its reason)
  and staff carry on by hand. Unsaved imports appear under "Partners to
  review" so they can be resumed.
- **Collaboration visibility is enforced on the server.** Private collaborations are
  never in `/api/partners…`. Limited ones are reduced to "Confidential
  collaboration", their public summary, years and current/past. A limited
  collaboration's projects and students are not exposed.
- **Current vs past** comes from each collaboration's status. A partner is shown as
  "Working with ImmXrsive now" if any visible collaboration is current. Past
  records are never deleted.
- **A suggested new company**, when approved, becomes a *draft* partner. The
  relationship shows publicly once staff publish that partner.
- **Duplicate domains:** a second partner with the same website domain is blocked with
  an "Open existing partner" link. Similar names alone are only listed as
  information and are never merged.
- **Schema changes are additive** (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT
  EXISTS`); no R1–R3 table or row is changed.

## Fixture source URLs (R4.08 evidence)

The four company-site fixtures are published unchanged with GitHub Pages:

| Fixture | Public test URL |
|---|---|
| company_normal.html | https://sajal19-sketch.github.io/immxrsive-platform/fixtures/r4/company_normal.html |
| company_sparse.html | https://sajal19-sketch.github.io/immxrsive-platform/fixtures/r4/company_sparse.html |
| company_prompt_injection.html | https://sajal19-sketch.github.io/immxrsive-platform/fixtures/r4/company_prompt_injection.html |
| company_same_name_other_domain.html | https://sajal19-sketch.github.io/immxrsive-platform/fixtures/r4/company_same_name_other_domain.html |

`fixtures/r4/` also holds `expected_company_imports.json`, `collaboration_seed.json`
and `README.md` from Moodle, byte-for-byte (SHA-256 sums in `fixtures/r4/SHA256SUMS`).

To repeat an import: sign in at `admin.html`, choose **Import partner from
website**, paste one of the URLs above, and click **Get details from website**.

## Testing done before the freeze

These tests ran against a disposable local PostgreSQL database, never production:

- `tests/test_r4_api.py`: 76 API checks covering every scenario in the R4 Peer QA
  Test Plan (A–L), plus R1–R3 regression. Results: all passed.
- Browser walk-through (Chrome, desktop for staff, 390 px mobile for public
  pages): 36 checks covering import, review, publish, collaborations, visibility,
  student requests, staff review, contextual inquiry, the back-button guard,
  and R1–R3 pages. Results: all passed, with no console errors and no horizontal
  scrolling at 390 px.

## Known issues / limits

- No company or employer accounts, messaging, merge tooling, or scheduled
  re-import (explicit non-requirements).
- One staff role only (no staff hierarchy). Additional staff accounts are
  created by the team in the database; there is no staff-management screen.
- The Render free tier sleeps. The first request after a while can take up to a
  minute, and pages show a "server may be waking up" message.
- The website importer reads the HTML the server receives. Pages that build their
  content with JavaScript give sparse suggestions; staff complete them by hand
  (R4.11 path).
