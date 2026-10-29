# Release 3 Release Notes: Shared Projects, Contributor Evidence, Playable Demos

**Tag:** `R3-submission`
**Frontend:** https://sajal19-sketch.github.io/immxrsive-platform/
**Backend:** https://immxrsive-api.onrender.com
**Student entry point:** `projects.html` ("My Projects", also linked from the profile editor and sign-in page)

## What's new

| Area | Where | Requirements |
|---|---|---|
| Add Project (manual or GitHub import) | `projects.html` → **+ Add Project** | R3.01–R3.03 |
| Repository links separate from project identity (0, 1 or many) | Repository links field | R3.04, R3.26 |
| One shared project record, creator becomes maintainer | `POST /api/projects` | R3.05, R3.06 |
| Transfer maintenance (same ID and URL) | Project panel → Transfer maintenance | R3.07, R3.26 |
| Invite teammate by GitHub username with a standard role | Project panel → Add teammate | R3.08 |
| Accept / decline invitation; invitees are never public before accepting | My Projects → Invitations | R3.09 |
| Standard role plus personal contribution statement | Project panel → Your contribution | R3.10, R3.11 |
| Show/hide project on my profile without leaving it | "Show this project on my public profile" | R3.12 |
| Soft removal with restore | Contributors → Remove / Restore | R3.13 |
| Project technologies never become personal skills | Project page + directory filters | R3.14 |
| Contributor roles on the public page | `project.html` | R3.15 |
| Duplicate repository warning with View / Ask to join | Add Project form | R3.16 |
| No silent lost update (version check, 409 conflict) | Save project | R3.17 |
| Playable, video and source links; fallback image + caption | Project details form, `project.html` | R3.18–R3.21 |
| URLs only, no embed/script HTML; all text rendered as text | Server URL validation + `textContent` | R3.19 |
| Broken demo or media does not break the page | `project.html` | R3.22 |
| 390px mobile project page | `project.html` | R3.23 |
| Server-side project authorization | every write route | R3.24 |

## Required decisions

**Who edits shared project fields:** only the **maintainer**. Accepted contributors cannot change the title, description, technologies, links, demo, publish state or teammates. Every contributor, including the maintainer, controls only their own role, contribution statement and "show on my profile" setting. There is no route that writes another person's statement.

**Contributor removal (R3.13):** we use a **soft delete the maintainer can reverse**. "Remove" changes the relationship to `removed`: it disappears from the public project page, but the row, role and statement are kept. The removed student still sees the project in My Projects marked "Removed by maintainer". The maintainer can press **Restore** at any time, and the original role and statement come back. A contributor who wants to leave their own portfolio display unticks "Show this project on my public profile".

**Concurrent edits (R3.17):** every save sends the version the editor loaded. If another session saved first, the server refuses with 409 and the editor shows a conflict box with the user's unsaved text so they can reload and re-apply it.

**Duplicates (R3.16):** a repository URL already connected to another project triggers a warning with **View project** and **Ask to join**. URLs are compared after normalizing (`www.`, letter case, trailing `/` and `.git` on GitHub). A similar title is only mentioned, never merged. A student can still say "It's a different project. Create it anyway".

## Setup for peer testers

1. Sign in with GitHub on `login.html` and verify your `@algomau.ca` email (same as Release 2).
2. Open **My Projects**. Reviewer A: **+ Add Project**, then save, then **Add teammate** using Reviewer B's **GitHub username**. Reviewer B must have signed in and verified first.
3. Reviewer B: My Projects → **Accept**, then **Open** → edit **Your contribution**.
4. Reviewer A: **Publish**, then open **View public page** in a private window.

QA evidence prepared by the team:
- Shared published project with 2+ accepted contributors: https://sajal19-sketch.github.io/immxrsive-platform/project.html?id=p_7eb4b3c84a54aaae
- Project with working demo and fallback: https://sajal19-sketch.github.io/immxrsive-platform/project.html?id=p_7eb4b3c84a54aaae
- Public repository for GitHub import: https://github.com/sajal19-sketch/immxrsive-platform
- Hosted demo: https://sajal19-sketch.github.io/immxrsive-platform/demo/working_demo.html
- Hosted fallback image: https://sajal19-sketch.github.io/immxrsive-platform/demo/fallback.svg

## Known issues and limits

- Render free tier sleeps. The first request after inactivity can take up to about a minute.
- GitHub import uses the public GitHub API without a token (60 requests/hour per server). When limited, the form says so and manual entry still works. Setting `GITHUB_API_TOKEN` on Render raises the limit.
- Teammates are invited by GitHub username, so they must have signed in and verified once before they can be invited.
- Fixture projects from Release 1 have no platform maintainer, so nobody can edit them. They stay public and read-only.
- Demos open in a new tab rather than embedded. This keeps arbitrary embed code out of our pages and isolates broken demos.
- Not built (explicit non-requirements): staff verification, audit-history UI, duplicate merging.

## Tests

- 18 backend tests run against PostgreSQL 16 (including the three cases in `data/project_duplicate_cases.json` and the roles in `data/standard_roles.json`) covering create, invite, accept/decline, contribution ownership, authorization by changed IDs, soft remove/restore, transfer, duplicate warning and join, stale-version conflict, repository separation, technologies vs skills, unpublished visibility and GitHub import.
- Browser checks at 390px: project page (play/source links, broken fallback, contributor roles, no horizontal scroll, 404 state) and My Projects (import, similar-name and duplicate-repository warnings, conflict box, labels, keyboard focus). 22 of 22 passed.
