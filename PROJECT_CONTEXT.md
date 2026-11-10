# PROJECT_CONTEXT.md — Blood Donor & Emergency Request Network
> Reference for the developer and any AI assistant. Keep under 150 lines. Site name is a placeholder: `SITE_NAME = "Blood Network"` in `config/settings.py`, exposed to templates by a context processor (change it in one place only).

## 1. Summary
Semester project for CSC-206 Software Engineering (Aror University, Sukkur), built by a team of three. A Django web app that connects blood donors with people who urgently need blood: donors register and toggle availability, requesters post requests, hospitals verify them, and the system surfaces compatible, eligible, nearby donors. It must be demoable live on a Windows laptop **fully offline** (all CSS, JS, icons, fonts in `static/vendor`; no CDN links). Reliability beats features: a broken extra costs more than a missing one. AI use is disclosed in `AI_USAGE.md`.

## 2. Tech Stack & Why
| Piece | Why |
|---|---|
| Python 3.14 + Django 6.1 | Batteries included: hashed passwords, ORM, form validation, CSRF, admin. Covers most security marks with little code |
| SQLite | A real database with zero setup; one file, easy to back up |
| Server-rendered templates | Simpler and less buggy than API + SPA; fast on cheap phones |
| Bootstrap 5 + Bootstrap Icons | Mobile-first responsive UI without writing much CSS; served locally |
| HTMX | Partial page updates (availability toggle, live filters) without a JS framework |
| Chart.js | Analytics charts (Tier 2) |
| AOS | Light scroll-in animation (disabled under reduced motion) |
| Inter (woff2, local) | Clean, readable font that works offline |

## 3. Architecture (layers)
| Layer | Role |
|---|---|
| Browser | Bootstrap + HTMX + Chart.js + AOS, all from `static/vendor` |
| URLs & views | `urls.py` routes; thin function-based views: check permission, call a form/service, render. Every view has an explicit permission check |
| Services | Business logic, no HTTP: `core/blood.py`, `donors/eligibility.py`, `blood_requests/matching.py`, `blood_requests/services.py`, `donors/ranking.py` |
| Models | Data + simple properties (e.g. `is_eligible`); validation lives in forms and model validators |
| Database | SQLite (`db.sqlite3`), migrations in git, indexes on blood_type, city, status |
| Templates | `base.html` + reusable partials (navbar, messages, badges, cards); no inline styles |
| Email | Console backend by default, SMTP optional (Tier 2); failures are caught and never block a request from posting |
| Admin | Django admin for users, requests, reports, and verification |

## 4. Apps & Folder Structure
```
blood-network/
├── manage.py  .gitignore  requirements.txt  README.md  AI_USAGE.md  PROJECT_CONTEXT.md
├── config/           settings.py (SITE_NAME), urls.py
├── core/             blood.py (BLOOD_TYPES, COMPATIBLE_DONORS), views.py (home, dashboard),
│                     context_processors.py, management/commands/seed_demo_data.py
├── accounts/         signup/login/logout forms + views, tests/
├── donors/           models.py (DonorProfile), forms.py, views.py, eligibility.py, ranking.py (T2), tests/
├── blood_requests/   models.py (BloodRequest, DonorResponse, Report), forms.py, views.py,
│                     matching.py, services.py, tests/
├── templates/        base.html, partials/, accounts/, donors/, blood_requests/, core/, errors/
└── static/
    ├── css/          theme.css (ALL colour/spacing variables), app.css (components)
    ├── js/app.js     AOS init + small helpers
    └── vendor/       bootstrap/, bootstrap-icons/, htmx/, chartjs/, aos/, fonts/inter/
```

## 5. Page Map
| URL | Who | Purpose |
|---|---|---|
| `/` | Public | Home: emergency button, live counts, how it works |
| `/accounts/signup/`, `/login/`, `/logout/` | Public (logout: POST, logged-in) | Create account, sign in/out |
| `/requests/` | Public | Active requests with filters; patient phone numbers shown only to the requester, the named hospital, admins and donors who offered to help |
| `/requests/<id>/` | Public view; contact needs login | Details and status; owner sees matching donors; donors can respond |
| `/requests/new/` | Logged-in | Post a request |
| `/requests/mine/` | Logged-in | My requests, mark fulfilled |
| `/requests/<id>/fulfil/` | Owner or admin, POST | Mark Fulfilled |
| `/requests/<id>/report/` | Logged-in, POST (T2) | Report a suspicious request |
| `/donors/register/` | Logged-in, no profile yet | Become a donor |
| `/donors/profile/` | Logged-in donor | Edit profile, availability toggle (HTMX), cooldown status |
| `/donors/search/` | Logged-in | Search compatible donors by blood type + city |
| `/dashboard/` | Admin (T2) | Analytics charts |
| `/admin/` | Admin | Manage users, verify requests, review reports |
| 403 / 404 / 500 | Public | Friendly error pages |

## 6. Data Model
- **User** (Django built-in, unique email, hashed password). Any logged-in user can post requests. Built-in chosen for simplicity.
- **DonorProfile**: user (1–1), phone, blood_type, city, area, is_available, last_donation_date (nullable), created_at. Properties `is_eligible`, `next_eligible_date`.
- **BloodRequest**: requester (FK User), patient_name, blood_type, units_needed, urgency (Critical/Urgent/Normal), hospital, city, area, contact_phone, note, status (Pending/Fulfilled/Expired), expires_at, created_at, fulfilled_at. T2: is_verified, verified_by.
- **DonorResponse**: request (FK), donor (FK DonorProfile), status (Willing/Declined/Donated), created_at; unique (request, donor). Feeds reliability ranking.
- **Report** (T2): request (FK), reporter (FK User), reason, details, created_at, resolved; unique (request, reporter).
- Relationships: User 1–1 DonorProfile; User 1–N BloodRequest; BloodRequest 1–N DonorResponse and Report; DonorProfile 1–N DonorResponse.
- Expiry is computed lazily by `services.expire_overdue()` (called on list/detail views); no scheduler needed. Phone validated with a Pakistani-format regex.

## 7. Feature Tiers
- **Tier 1 (core, must be flawless):** authentication; donor registration with availability toggle and 90-day cooldown; request posting; search and matching; Pending/Fulfilled/Expired status.
- **Tier 2 (only after Tier 1 is frozen, in this order):** 1) smart donor ranking, 2) verification layer, 3) abuse prevention (report button + daily request limit), 4) analytics dashboard, 5) email notifications.
- **Tier 3 (stretch):** Urdu/Sindhi support.

## 8. Theme Tokens (Clinical teal) — all in `static/css/theme.css`
```css
:root {
  --primary:#0E7C86; --primary-dark:#0A5F67; --navy:#0B2545; --blood:#D62839;
  --tint:#E3F3F4; --bg:#F5FAFB; --surface:#FFFFFF; --border:#D5E6E8; --muted:#5B6B7C;
  --warning:#B7791F; --success:#1E8E5A;
  --font:"Inter", system-ui, sans-serif;
  --space-1:4px; --space-2:8px; --space-3:12px; --space-4:16px; --space-5:24px; --space-6:32px; --space-7:48px;
  --radius-md:12px; --radius-lg:16px;
  --shadow-sm:0 1px 3px rgba(11,37,69,.08); --shadow-md:0 6px 20px rgba(11,37,69,.10);
  --dur-fast:150ms; --dur-base:250ms; --dur-slow:300ms;
}
```
- Blood red is used ONLY for blood-type badges, Critical urgency, and the emergency button. Nothing else (errors use amber `--warning`).
- Urgency: Critical = red, Urgent = amber, Normal = teal. Status: Pending = amber, Fulfilled = green, Expired = grey.
- Body text navy on `--bg`; cards on `--surface` with 12–16px radius and soft shadow; buttons at least 44px tall for touch.
- Animate only `transform` and `opacity`, 150–300ms; wrap motion in `@media (prefers-reduced-motion: reduce)` to disable it. Override Bootstrap through variables, not `!important`.

## 9. Blood Compatibility (recipient → compatible donors)
| Recipient | Compatible donors |
|---|---|
| A+ | A+, A-, O+, O- |
| A- | A-, O- |
| B+ | B+, B-, O+, O- |
| B- | B-, O- |
| AB+ | A+, A-, B+, B-, AB+, AB-, O+, O- (all eight) |
| AB- | A-, B-, AB-, O- |
| O+ | O+, O- |
| O- | O- only |

Stored as `COMPATIBLE_DONORS` in `core/blood.py` (pure Python, no Django imports). O- is the universal donor; AB+ is the universal recipient. Unit tests check all 8 recipients and all 64 pairs.

## 10. Build Order (each milestone ends with "done when")
**M0 Setup:** venv, install Django, `startproject config`, four apps, `git init`, `.gitignore`, download vendor files.
Done when: [ ] `runserver` shows the welcome page [ ] first commit exists [ ] every CSS/JS/font file is in `static/vendor`.
**M1 Layout & theme:** `theme.css`, `app.css`, `base.html`, navbar, messages, home page, error pages, `SITE_NAME`.
Done when: [ ] pages load with Wi-Fi off and DevTools shows zero external requests [ ] looks right at 375px width [ ] reduced motion respected.
**M2 Authentication:** signup, login, logout (POST), `@login_required` pattern, auth tests.
Done when: [ ] passwords are hashed in the DB [ ] anonymous users are redirected from protected pages [ ] tests pass.
**M3 Blood compatibility:** `core/blood.py` + exhaustive tests.
Done when: [ ] `python manage.py test core` passes [ ] O- donates to all, AB+ receives from all, O- receives only O-.
**M4 Donor profile:** model, register form, profile page, HTMX availability toggle, `eligibility.py` (90-day rule).
Done when: [ ] donor registers [ ] toggle works without reload [ ] 89 days = ineligible, 90 = eligible (tested) [ ] future dates rejected.
**M5 Requests:** model, post form, list with filters, detail, mark fulfilled, `services.expire_overdue`.
Done when: [ ] new request is Pending [ ] only owner/admin can fulfil (others get 403) [ ] overdue becomes Expired [ ] contact hidden from anonymous users.
**M6 Search & matching:** `matching.py`, donor search page, matching donors on request detail, "I can help" DonorResponse.
Done when: [ ] results exclude unavailable, cooling-down, wrong-city, and own profile [ ] only compatible types shown [ ] exact type first, then same area [ ] tests pass.
**M7 `seed_demo_data` command:** ~30 donors across Sukkur, Khairpur, Rohri (all 8 types, mixed availability/cooldown), ~12 requests (all statuses and urgencies), demo admin + demo user, `--reset` flag.
Done when: [ ] one command gives a demo-ready DB [ ] running twice does not duplicate data [ ] demo logins are listed in README.
**M8 Hardening & Tier 1 freeze:** permission audit of every view, validation review, error pages, mobile pass, README, `AI_USAGE.md`, 3–5 min demo video, tag `v1-core`.
Done when: [ ] full test suite green [ ] demo script runs twice in a row from a fresh seed [ ] repo pushed to GitHub [ ] backup made.
**M9 Smart ranking:** `ranking.py` (proximity by area, days since last donation, response history), pure function, unit-tested. Done when: [ ] order is explainable and tested.
**M10 Verification:** admin action + "Verified" badge; unverified requests stay visible. Done when: [ ] admin verifies in one click.
**M11 Abuse prevention:** report button, max 3 requests per user per day in `services.py`. Done when: [ ] 4th request is blocked with a clear message [ ] duplicate report blocked.
**M12 Analytics:** `/dashboard/` with Chart.js (requests by blood type and area, status split, trend), admin only. Done when: [ ] renders offline [ ] non-admins get 403.
**M13 Email:** console backend, optional SMTP. Done when: [ ] matching request triggers email [ ] an email failure never blocks posting.
**M14 Urdu/Sindhi (stretch):** Django i18n, RTL CSS, local Naskh font. Done when: [ ] language switch works on all Tier 1 pages.

## 11. Conventions, Testing, Backups
- **Code:** PEP 8, snake_case, function-based views, logic in service files (views stay under ~25 lines), ModelForms for validation, ORM only (no raw SQL), state changes via POST only, `get_object_or_404`, owner/admin checks on every mutating view.
- **Templates/static:** extend `base.html`, reuse partials, no inline styles or CDN links, colours only from CSS variables. Secrets via environment variables with a dev fallback in settings.
- **Security:** hashed passwords (Django default), CSRF on every form, server-side validation, donor and request contact details visible to logged-in users only.
- **Testing:** `python manage.py test` after every milestone. Unit tests for compatibility (all 64 pairs), eligibility boundaries (89/90/91 days), matching filters, expiry, and the daily limit. View tests for permissions (anonymous redirected, non-owner denied). Manual click-through of the demo script before every commit.
- **Git:** `git add .` → `git commit -m "M4: donor profile"` → `git push` after each working milestone; never commit `.venv` or `db.sqlite3`.
- **Manual backup after each working milestone (PowerShell, from inside `blood-network`):**
  `robocopy . ..\backups\blood-network_M4 /E /XD .venv .git __pycache__` (robocopy exit codes below 8 mean success). Keep the last 3 backups and re-run `seed_demo_data` before demos.