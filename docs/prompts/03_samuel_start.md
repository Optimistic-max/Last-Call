# Prompt: Samuel, base layout + board + pledge screen

Paste everything below the line into your AI coding tool from the repo folder, on a branch like `samuel/board`.

---

Read `AGENTS.md` fully, then `docs/UI_DESIGN.md` (all of it), `docs/PRODUCT.md` and the "Pages and routes" table in `docs/SYSTEM_DESIGN.md`.

I am Samuel. I own `templates/` and `static/`. Don't touch any `.py` file except to ask me first. If I need data from the server, tell me what the route should pass to the template and I'll ask Emmanuel.

**Task 1 (M0): `templates/base.html` + `static/style.css`.**
- The sandbox banner on every page, color tokens as CSS variables, two fonts, a phone-first layout (375px wide first), and `prefers-reduced-motion` support.
- Propose 2 color and font directions that fit "a friendly last call, not a bank". Show me both before building either.

**Task 2 (M1): S1 create event, S2 treasurer view, S3 board.**
- Use made-up sample data in the template for now (a fictional "Ridgeline Hiking Club"), so I can design before the backend is ready.
- The board refreshes every 10 seconds by fetching `/e/<id>/board.json`. Don't format or calculate money in JavaScript; the JSON sends formatted strings.
- Use the exact wording from `docs/UI_DESIGN.md` §4.

**Task 3 (M1, with Emmanuel): S4 pledge + S5 result.**
- The layout around PayPal's card fields: name, max, the promise text above the card fields, the "Hold my max" button, and the Held / Card declined / error states.
- Emmanuel handles the PayPal JavaScript wiring. You make the page and the states look right.

**To-do:** Add '[Name] has already pledged.' to UI_DESIGN (D26).

Work one task at a time. Show me a plan first and wait. After building, explain the HTML, CSS and JS line by line in plain English, and tell me how to view it locally.
