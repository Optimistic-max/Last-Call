# Flask routes only (AGENTS.md section 7). Owner: Emmanuel.
# Malama's M0 task added GET /health (docs/MVP_PLAN.md, M0), so Render can see the app is up and the
# database answers. Emmanuel's step 2.3 added the startup sandbox guard and the pledge and order routes.
# Routes read the request, call lifecycle.py, and turn its answer into JSON. They do no money math.

import logging
from datetime import datetime, timezone

import psycopg
from flask import Flask, jsonify, request

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
HELD_TEXT = "Held. You'll pay only your share, at most %s, and only if the goal is reached."
DECLINED_TEXT = "Card declined. Nothing was held. Try another card."
CLOSED_AND_VOIDED_TEXT = ("Pledging closed before your hold went through. "
                          "We're cancelling the hold, and nothing will be charged.")
ERROR_TEXT = "Something went wrong. Nothing was charged. Please try again."
ALREADY_PLEDGED_TEXT = "%s has already pledged."    # D26; Samuel's to-do adds it to UI_DESIGN
# Not in UI_DESIGN yet, so Samuel should check them: pledging closed before any hold was placed,
# a blank name, and a max under $5.
CLOSED_TEXT = "Pledging is closed for this event. Nothing was held."
NO_NAME_TEXT = "Type your name."
TOO_SMALL_TEXT = "The smallest max is $5.00."


# The one place the app reads the clock (AGENTS.md section 5: time is passed in). Always UTC.
# Tests replace this function to move time.
def utc_now():
    return datetime.now(timezone.utc)


# 4000 -> "$40.00", 123456 -> "$1,234.56": how money is shown on screen (docs/UI_DESIGN.md section 7).
# Whole-number math only. In "{:,}.{:02d}", the "," puts a comma between groups of three digits and
# "02" pads the cents to two digits.
def dollars(cents):
    return "$" + "{:,}.{:02d}".format(cents // 100, cents % 100)


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
        return jsonify({"pledger_token": result["pledger_token"]})
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
