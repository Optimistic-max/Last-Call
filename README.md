# Last Call (working name)

> **SANDBOX DEMO.** Everything in this project runs in PayPal's sandbox with fake money. No real payments are made.

> **Status: in development.** The app isn't built yet. This page describes the design. [`docs/CLAIMS.md`](docs/CLAIMS.md) shows what has actually been tested.

**Nobody pays unless the goal is reached.**

Last Call is a group-payment app for clubs. Everyone pledges the most they'd pay, PayPal holds that amount without charging it, and only if the group reaches its goal is everyone charged once, for their fair share. If the goal is missed, every hold is cancelled and nobody pays. Each friend types their pledge in their own words, an AI suggests the amount, cap and condition, and the friend confirms or fixes them. Plain code handles every dollar.

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/).

---

## Try it

**Live demo:** _link goes here_
_First load may take up to a minute (free hosting wakes up)._

**Sandbox test logins for judges:** _filled in before submission. Sandbox buyer accounts only. The app's secret keys are never in this repo._

**Demo video (under 3 minutes):** _YouTube link goes here_

## How it works

1. The treasurer sets a goal (for example, a $300 deposit). The app raises the goal slightly so PayPal's fees are covered and the club still receives the full $300.
2. Pledgers open the link and pledge a maximum. PayPal places a **hold** for that amount. Nothing is charged yet.
3. When the goal is reached, a **last call** opens for one hour (or until the 48-hour deadline). More people can join and everyone's share drops. People already counted can't leave.
4. Shares lock and each person is **charged once** for their share. PayPal closes the rest of the hold.
5. If the goal is missed, every hold is **voided** and nobody pays.

## What we tested (and what we didn't)

See [`docs/CLAIMS.md`](docs/CLAIMS.md) for every claim with its evidence and status. Untested parts are labeled **designed, not tested**. Capture declines are **simulated** with PayPal's negative-testing header.

## AI and tools used

- **AI model:** _name goes here._ It reads each friend's pledge, typed in their own words, and suggests the amount, cap and condition. The friend confirms or fixes them before anything is saved. It never moves money.
- **PayPal:** Orders v2 (intent `AUTHORIZE`), Payments v2 (capture, void, refund), JavaScript SDK card fields, all in the sandbox.
- **Hosting:** Render (web app), Neon (Postgres).
- **AI coding assistants used while building:** _list them honestly._

## Run it yourself

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # fill in your own sandbox keys
psql "$DATABASE_URL" -f schema.sql
flask --app app run --debug
pytest
```

You need a free PayPal developer account with a sandbox app (Advanced Credit and Debit Card Payments enabled), a free Neon Postgres database, and an API key for the AI model.

## Team

- Emmanuel: lead, PayPal money flow
- Samuel: UI and design
- Malama: AI pledge reader, math, database

## License

MIT. See `LICENSE`.
