# Prompt: Samuel, base layout + board + pledge screen

Paste everything below the line into your AI coding tool from the repo folder, on a branch like `samuel/board`.

---

Read `AGENTS.md` fully, then `docs/TEAM.md` (my open to-dos), `docs/UI_DESIGN.md` (all of it), `docs/PRODUCT.md`, `docs/MVP_PLAN.md` (M0, M1 and M4), D31 in `docs/DECISIONS.md`, and the "Pages and routes" table in `docs/SYSTEM_DESIGN.md`.

I am Samuel. I own `templates/`, `static/` and `docs/UI_DESIGN.md`. Don't touch any `.py` file; ask me first. If I need data from the server, tell me what the route should pass to the template and I'll ask Emmanuel. Git: I choose my own workflow (D22), but never push to `main` and never merge a pull request. Everything reaches `main` through a pull request Emmanuel reviews.

**Every APPROVED decision in `docs/DECISIONS.md` applies. The one that shapes my screens is D31, the own-words pledge flow:** each friend types their own pledge, the AI reads that one message, the friend fixes and confirms the amount, cap and condition, and nothing is saved until they confirm. The treasurer chat paste (S7) is deferred: don't build it.

**Task 0 (first): my TEAM.md to-do.** Add '[Name] has already pledged.' to the wording table in `docs/UI_DESIGN.md` §4. It's shown when someone confirms a name that already holds (D26). Then delete my row from the Open to-dos table in `docs/TEAM.md`.

**Task 1 (M0): `templates/base.html` + `static/style.css`.**
- The sandbox banner on every page, color tokens as CSS variables, two fonts, a phone-first layout (375px wide first), and `prefers-reduced-motion` support.
- Propose 2 color and font directions that fit "a friendly last call, not a bank". Show me both before building either.

**Task 2 (M1): S1 create event, S2 treasurer view, S3 board.**
- Use made-up sample data in the template for now (a fictional "Ridgeline Hiking Club"), so I can design before the backend is ready.
- The board refreshes every 10 seconds by fetching `/e/<id>/board.json`. Don't format or calculate money in JavaScript; the JSON sends formatted strings.
- **M1 board:** each person shows a plain status word: **Pledged**, **Held** or **Declined**. The total counts only held money, and it arrives already added up in `board.json`; the template and JavaScript never add amounts.
- Never show an email on the board or in `board.json` (`docs/SECURITY.md`).
- Use the exact wording from `docs/UI_DESIGN.md` §4.

**Task 3 (M1, with Emmanuel): restyle S4 pledge + S5 result.**
- Emmanuel creates a bare `templates/pledge.html` (plain fields for name and max, the promise text, PayPal's card fields and the "Hold my max" button) and `static/js/pledge_paypal.js`, already wired to the routes. I restyle the page. Don't change `static/js/pledge_paypal.js` (it's Emmanuel's) or the field names the routes read.
- The result states use the `UI_DESIGN.md` §4 wording: Held, Card declined, Pledging closed, and the error message.
- M1 has no own-words box, no quick amounts, no Share button and no styled chips yet. Those are M4.

**Task 4 (M4): the D31 screens.**
- **S4:** the own-words box with its privacy note, quick-amount buttons (the values come from `config.py`), and the editable confirm step: amount (the minimum, shown only), cap (the most that gets held) and condition. Never ask a friend for the same info twice: a retry after "Card declined" keeps what they typed. Add the optional email field only once Malama's `pledges.email` column exists.
- **S2:** a Share button using the Web Share API, with a copy-link fallback, and static Open Graph tags (`UI_DESIGN.md` §9). Wake the Render server before sharing the link.
- **Board:** styled chips **Pledged**, **Hold pending** and **Held** replace M1's plain status words. The total still counts only held money.
- **The friend's own link:** the declined-card text from `UI_DESIGN.md` §4.
- M4's done list in `docs/MVP_PLAN.md` has a manual check for each of these. They're recorded in the `TEST_PLAN.md` run log.

Work one task at a time. Show me a plan first and wait. After building, explain the HTML, CSS and JS line by line in plain English, and tell me how to view it locally.
