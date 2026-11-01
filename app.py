# Flask routes only (AGENTS.md section 7). Owner: Emmanuel.
# Malama's M0 task added GET /health (docs/MVP_PLAN.md, M0), so Render can see the app is up and the
# database answers. Emmanuel's step 2.3 added the startup sandbox guard and the pledge and order routes,
# step 2.4 the pledge page, step 2.5 settle-on-wake, and step 5b creating and opening an event (S1, S2).
# Routes read the request, call lifecycle.py, and turn its answer into JSON or a page. They do no money math.

import logging
from datetime import datetime, timezone

import psycopg
from flask import Flask, jsonify, redirect, render_template, request, url_for

import config
import db
import lifecycle
import money
import paypal_client

logger = logging.getLogger(__name__)

# Refuse to start unless PayPal's address is exactly the sandbox (rule 12, test E10). This line runs
# the moment the file is imported, which is how both "flask run" and Render's "gunicorn app:app" start
# the app, so nothing is ever served with a live, empty or mistyped PayPal address.
config.check_sandbox_url(config.PAYPAL_BASE_URL)

app = Flask(__name__)

# Screen text, copied exactly from docs/UI_DESIGN.md section 4 (checked for honesty). %s is filled in.
HOLD_PROMISE_TEXT = "If the goal is met, you're in. We'll hold up to %s now and charge only your share."
HELD_TEXT = "Held. You'll pay only your share, at most %s, and only if the goal is reached."
DECLINED_TEXT = "Card declined. Nothing was held. Try another card."
CLOSED_AND_VOIDED_TEXT = ("Pledging closed before your hold went through. "
                          "We're cancelling the hold, and nothing will be charged.")
ERROR_TEXT = "Something went wrong. Nothing was charged. Please try again."
ALREADY_PLEDGED_TEXT = "%s has already pledged."    # D26
CLOSED_TEXT = "Pledging is closed for this event. Nothing was held."
NO_NAME_TEXT = "Type your name."
TOO_SMALL_TEXT = "The smallest max is $5.00."
# D58's cap, filled in from config.py. A placeholder until Samuel adds it to UI_DESIGN section 4 (D57).
TOO_BIG_TEXT = "The largest max is %s."
# S1's refusals, the limits filled in from config.py. Placeholders until Samuel adds them to UI_DESIGN
# section 4 (D57, D58, D61).
NO_TITLE_TEXT = "Type a title."
DEPOSIT_TOO_SMALL_TEXT = "The smallest deposit is %s."
DEPOSIT_TOO_BIG_TEXT = "The largest deposit is %s."


# The one place the app reads the clock (AGENTS.md section 5: time is passed in). Always UTC.
# Tests replace this function to move time.
def utc_now():
    return datetime.now(timezone.utc)


# Settle-on-wake (docs/SYSTEM_DESIGN.md section 3): the free server sleeps and has no timer, so before
# each request, any event whose time is up is settled first. Requests for /static/ files (D41) and
# /health (D46) skip it: they come often, and /health must stay a quick database ping.
@app.before_request
def settle_anything_due():
    if request.path.startswith("/static/") or request.path == "/health":
        return
    settle_on_wake(utc_now())


# Open a connection and settle. If the database fails, log the error's type only and still serve the
# page (SYSTEM_DESIGN.md section 3), so one bad moment can't take down every page.
# Tests that send requests but aren't about settling replace this function (tests/test_routes.py).
def settle_on_wake(now):
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            lifecycle.settle_due_events(conn, now, paypal_client)
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("settle on wake failed: database error (%s)", type(error).__name__)


# 4000 -> "$40.00", 123456 -> "$1,234.56": how money is shown on screen (docs/UI_DESIGN.md section 7).
# Whole-number math only. In "{:,}.{:02d}", the "," puts a comma between groups of three digits and
# "02" pads the cents to two digits.
def dollars(cents):
    return "$" + "{:,}.{:02d}".format(cents // 100, cents % 100)


# The same dollars() as a template filter: {{ 4000|dollars }} shows "$40.00" (docs/UI_DESIGN.md
# section 7), so pages and JSON messages always format money the same way. Adding it to Flask's
# filter list like this needs no decorator (AGENTS.md section 5).
app.jinja_env.filters["dollars"] = dollars


# The JSON object the page sent, or {} if it sent nothing or something that isn't a JSON object.
# silent=True means "give back None instead of raising an error" for a body that isn't JSON.
def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


# A JSON answer carrying one message for the page to show, with an HTTP status code.
def message_answer(message, http_status):
    return jsonify({"message": message}), http_status


# Turn a lifecycle refusal into the answer the page shows. One place for every refusal, so the three
# routes word them the same way. Anything unexpected gets the general error text.
def refusal_answer(result):
    outcome = result["outcome"]
    if outcome == "ALREADY_PLEDGED":
        return message_answer(ALREADY_PLEDGED_TEXT % result["name"], 409)
    if outcome == "CLOSED":
        return message_answer(CLOSED_TEXT, 409)
    if outcome == "NO_NAME":
        return message_answer(NO_NAME_TEXT, 400)
    if outcome == "TOO_SMALL":
        return message_answer(TOO_SMALL_TEXT, 400)
    if outcome == "TOO_BIG":
        return message_answer(TOO_BIG_TEXT % dollars(config.MAX_MAX_CENTS), 400)
    if outcome == "NOT_FOUND":
        return message_answer(ERROR_TEXT, 404)
    return message_answer(ERROR_TEXT, 502)


# Render (and later an optional pinger) calls this to wake the app and check it works.
# "ok" means the app is running AND the database answered SELECT 1. Otherwise the answer is
# 503 (Service Unavailable) with a short message. The error itself is never shown, because it
# could name the database host (docs/SECURITY.md); only its type is logged.
# The inner try/finally closes the connection even if the query fails.
@app.route("/health")
def health():
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            db.fetch_one(conn, "SELECT 1")
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("/health: database check failed (%s)", type(error).__name__)
        return "database unavailable", 503
    return "ok"


# S4, the pledge page (docs/UI_DESIGN.md section 3). The friend types a name and a max, confirms them,
# then types a card into PayPal's card fields (static/js/pledge_paypal.js does the PayPal part).
# A closed event shows the "pledging is closed" text instead of the form. An unknown event is a 404.
# <int:event_id> means Flask only calls this for a whole number, so "/e/abc/pledge" is a 404 by itself.
@app.route("/e/<int:event_id>/pledge")
def pledge_page(event_id):
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            event = lifecycle.find_event(conn, event_id)
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("GET /e/<id>/pledge: database error (%s)", type(error).__name__)
        return ERROR_TEXT, 503
    if event is None:
        return ERROR_TEXT, 404
    return render_template("pledge.html", event=event,
                           pledging_open=lifecycle.pledging_is_open(event, utc_now()),
                           closed_text=CLOSED_TEXT, error_text=ERROR_TEXT)


# The browser-safe client token the PayPal SDK v6 card fields start with (D16). It's sent only to the
# page that asked, and never logged.
@app.route("/api/client-token")
def api_client_token():
    token = paypal_client.get_client_token()
    if token is None:
        return message_answer(ERROR_TEXT, 502)
    return jsonify({"clientToken": token})


# D31: the friend confirmed a name and a max, so save the pledge and send back its private token.
# The page sends {"event_id": 7, "name": "Ana", "max": "40"}. "max" is the typed text: money.py turns it
# into whole cents, so no float is ever made (rule 1). There is no email field until Malama approves
# the pledges.email column.
# The answer also carries the "We'll hold up to $40.00" sentence, already formatted here, because
# JavaScript never formats money (docs/UI_DESIGN.md section 7).
# type(event_id) is not int also refuses True and False, which Python otherwise counts as numbers.
@app.route("/api/pledges", methods=["POST"])
def api_create_pledge():
    body = json_body()
    event_id = body.get("event_id")
    name = body.get("name")
    if type(event_id) is not int or not isinstance(name, str):
        return message_answer(ERROR_TEXT, 400)
    try:
        max_cents = money.dollars_text_to_cents(body.get("max"))
    except ValueError as error:
        return message_answer(str(error), 400)
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            result = lifecycle.confirm_pledge(conn, event_id, name, max_cents, utc_now())
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("POST /api/pledges: database error (%s)", type(error).__name__)
        return message_answer(ERROR_TEXT, 503)
    if result["outcome"] == "CONFIRMED":
        return jsonify({"pledger_token": result["pledger_token"],
                        "hold_text": HOLD_PROMISE_TEXT % dollars(max_cents)})
    return refusal_answer(result)


# Create the hold row and the PayPal order (intent AUTHORIZE) for a confirmed pledge.
# The page sends {"pledger_token": "..."} in the body, never in the address, so it stays out of logs.
@app.route("/api/orders", methods=["POST"])
def api_create_order():
    pledger_token = json_body().get("pledger_token")
    if not isinstance(pledger_token, str):
        return message_answer(ERROR_TEXT, 400)
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            result = lifecycle.start_hold(conn, pledger_token, utc_now(), paypal_client)
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("POST /api/orders: database error (%s)", type(error).__name__)
        return message_answer(ERROR_TEXT, 503)
    if result["outcome"] == "ORDER_CREATED":
        return jsonify({"order_id": result["order_id"]})
    return refusal_answer(result)


# The card was approved in the browser: authorize the order and report HELD, DECLINED or CLOSED.
# The pledger_token must match the order's pledge, so nobody can authorize someone else's order.
# order_id comes from the address, but it's only ever used to look up a hold we saved ourselves.
@app.route("/api/orders/<order_id>/authorize", methods=["POST"])
def api_authorize_order(order_id):
    pledger_token = json_body().get("pledger_token")
    if not isinstance(pledger_token, str):
        return message_answer(ERROR_TEXT, 400)
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            result = lifecycle.authorize_hold(conn, order_id, pledger_token, utc_now(), paypal_client)
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("POST /api/orders/<id>/authorize: database error (%s)", type(error).__name__)
        return message_answer(ERROR_TEXT, 503)
    outcome = result["outcome"]
    if outcome == "HELD":
        return jsonify({"status": "HELD", "message": HELD_TEXT % dollars(result["held_cents"])})
    if outcome == "DECLINED":
        return jsonify({"status": "DECLINED", "message": DECLINED_TEXT})
    if outcome == "CLOSED_AND_VOIDED":
        return jsonify({"status": "CLOSED", "message": CLOSED_AND_VOIDED_TEXT})
    return refusal_answer(result)


# ---------- Step 5b: create and open an event (S1, S2) ----------
# The values each template gets are the contract in docs/UI_DESIGN.md section 10.

# S1, the create-event form (docs/UI_DESIGN.md section 3).
@app.route("/")
def create_event_page():
    return render_template("create_event.html", error_text="", title_value="", deposit_value="",
                           demo_mode_checked=False)


# S1 again after a refusal: the message, plus everything the treasurer typed, so nothing is typed twice.
def refused_create_page(error_text, http_status):
    return render_template("create_event.html", error_text=error_text,
                           title_value=request.form.get("title", ""),
                           deposit_value=request.form.get("deposit", ""),
                           demo_mode_checked=request.form.get("demo_mode") == "yes"), http_status


# The S1 message for each refusal from lifecycle.create_event.
def create_refusal_text(outcome):
    if outcome == "NO_TITLE":
        return NO_TITLE_TEXT
    if outcome == "TOO_SMALL":
        return DEPOSIT_TOO_SMALL_TEXT % dollars(config.MIN_DEPOSIT_CENTS)
    if outcome == "TOO_BIG":
        return DEPOSIT_TOO_BIG_TEXT % dollars(config.MAX_DEPOSIT_CENTS)
    return ERROR_TEXT


# "Create": save a DRAFT event, then send the treasurer to S2. The form sends title, deposit and
# demo_mode (a checkbox that sends "yes" only when ticked). The typed deposit becomes whole cents with
# money.py, so no float is ever made (rule 1). Code 303 tells the browser to load S2 with a GET, so
# refreshing S2 can't create the event a second time.
@app.route("/events", methods=["POST"])
def submit_event():
    try:
        deposit_cents = money.dollars_text_to_cents(request.form.get("deposit", ""))
    except ValueError as error:
        return refused_create_page(str(error), 400)
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            result = lifecycle.create_event(conn, request.form.get("title", ""), deposit_cents,
                                            request.form.get("demo_mode") == "yes")
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("POST /events: database error (%s)", type(error).__name__)
        return refused_create_page(ERROR_TEXT, 503)
    if result["outcome"] == "CREATED":
        return redirect(url_for("admin_page", admin_token=result["admin_token"]), code=303)
    return refused_create_page(create_refusal_text(result["outcome"]), 400)


# The link the treasurer shares in the group chat: the pledge page (D55). APP_BASE_URL is the app's
# public address (the Render URL). It may be empty on a laptop, so then the address this request came
# in on is used instead, like "http://localhost:5000/".
def share_link_for(event_id):
    base_url = config.APP_BASE_URL
    if base_url == "":
        base_url = request.url_root
    return base_url.rstrip("/") + url_for("pledge_page", event_id=event_id)


# S2, the treasurer view. The admin_token in the address is the treasurer's login (D18), so the log
# names the route only, never the token. An unknown token is a 404 with the general error text, like
# an unknown event. The board joins this page in step C (D54).
@app.route("/admin/<admin_token>")
def admin_page(admin_token):
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            event = lifecycle.find_event_by_admin_token(conn, admin_token)
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("GET /admin/<token>: database error (%s)", type(error).__name__)
        return ERROR_TEXT, 503
    if event is None:
        return ERROR_TEXT, 404
    return render_template("admin.html", title=event["title"], share_link=share_link_for(event["id"]),
                           can_open=event["status"] == "DRAFT",
                           open_url=url_for("open_pledging", admin_token=admin_token))


# "Open pledging": DRAFT -> OPEN through lifecycle.open_event, then back to S2 with a 303.
# A second click changes nothing and also goes back to S2.
@app.route("/admin/<admin_token>/open", methods=["POST"])
def open_pledging(admin_token):
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            outcome = lifecycle.open_event(conn, admin_token, utc_now())
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("POST /admin/<token>/open: database error (%s)", type(error).__name__)
        return ERROR_TEXT, 503
    if outcome == "NOT_FOUND":
        return ERROR_TEXT, 404
    return redirect(url_for("admin_page", admin_token=admin_token), code=303)
