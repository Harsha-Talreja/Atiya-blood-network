# AI Usage Disclosure

This project was built with substantial help from **Claude** (Anthropic) across several chat sessions. This document covers what Claude did. **Sections marked `[FILL IN]` must be completed by the team.** Claude can only see its own conversations, not work done by hand or with other tools outside them, and it should not guess at those.

## Earlier session (not visible to Claude later)

`[FILL IN]` Judging by the project's state when later sessions began, an earlier session covered project setup, the layout and theme, authentication, the blood-compatibility logic and its tests, donor profiles (registration, availability switch, 90-day cooldown) and the first version of the request and matching data model. Please state:
- which of this Claude wrote and which a team member wrote
- anything Claude got wrong that you corrected by hand
- roughly how much was used as-is versus rewritten

## Later sessions: what Claude did

**Features built, each with automated tests**
- Blood request posting, board with filters, detail page, "mark fulfilled", and "I can help" donor responses.
- Donor search page (blood type and city). Phone numbers are deliberately not shown there, to respect the donor's consent setting.
- `seed_demo_data` command for optional rehearsal data (not used for real data).
- **Hospital verification:** a `hospitals` app with a fixed hospital list, one login per hospital, a verification dashboard, and a rule that requests stay hidden from donors until their hospital verifies them. Includes a data-preserving migration that converted the old free-text hospital field.
- **Abuse prevention:** a report button with an admin review queue, one report per person per request, and a 3-requests-per-day limit.
- **Match-found banner** on the owner's request page.
- **Auto-approval:** a request the hospital hasn't verified within the wait is released to donors on its own, badged "Auto-approved" rather than "Verified by hospital". Computed when a page loads, so there is no scheduler.
- Removed "Find donors" from the main navigation (the page remains, linked from the donor dashboard), so patients are steered to posting a request rather than browsing donors.
- `set_hospital_logins` command (memorable hospital usernames and a known password).
- README and this disclosure.

**Bugs Claude found and fixed in existing code**
- Several pages 404'd because `config/urls.py` never included the accounts and donors URLs.
- The donor dashboard imported a function that didn't exist.
- Logout posted to the wrong URL, and login/logout redirected to a page that doesn't exist.
- The success pop-up was three pieces that had never been connected.
- About 50 CSS classes used in templates had no styles (this caused the black eligibility ring and the unstyled login page).
- A duplicate "I can help" click could break a database transaction.
- A hospital could verify a request it had posted itself (a conflict of interest). Now blocked.
- Two tests meant to prove an unverified request stays off the public board searched the page for the patient's name, but those cards show the hospital's name - so they would have passed even if the hiding broke. They now check the request's own link.
- All hospital logins shared one password. Now unique by default from `migrate`.
- A hospital login was shown donor and patient menus, buttons and a call-to-action banner. Now hidden for hospital accounts.
- The home page's "No donors registered yet" button was a dead placeholder. It now goes to the right page, and the shared component can no longer render a button without a real destination.
- `seed_demo_data` would crash if two hospitals shared a name (the model allows branches).

**How it was checked**
- The test suite has 310 passing tests as of this version. Claude ran it after every change.
- Destructive operations (the `--reset` command, the hospital-field migration, merging duplicate hospitals) were tried against a copy of the project's real data before being given to the team. That caught a real risk: an early draft of `--reset` would have deleted the team's own `admin` account.
- Several problems were found only by running against real data rather than a clean test database (the duplicate-hospital crash and the tests that wrongly assumed an empty user table).
- Partway through, Claude's working copy was reset and the project was rebuilt from the zips it had delivered, then re-verified (the 269-test baseline matched exactly) before continuing.

**Limits of that checking**
- Claude could not see the team's machine. Instructions given for Windows/PowerShell were reasoned out, not run there, and needed several corrections.
- Passwords set by `set_hospital_logins` are shared. That is a convenience for the demo and not production-grade.

The team should still be able to read and explain any part of this code in Q&A. Claude writing code does not replace understanding it.

## Tools other than Claude

`[FILL IN]` e.g. GitHub Copilot, ChatGPT or anything else, and what it was used for.

## What the team did itself

`[FILL IN]` Design decisions (for example choosing hospital verification and the hidden-until-verified rule), testing on real devices, debugging on your own machines, anything written or changed by hand, and reviewing Claude's output.
