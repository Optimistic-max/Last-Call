# Flask routes only (AGENTS.md section 7). Owner: Emmanuel.
# Malama's M0 task added GET /health (docs/MVP_PLAN.md, M0), so Render can see the app is up and the
# database answers. Emmanuel's step 2.3 added the startup sandbox guard and the pledge and order routes,
# step 2.4 the pledge page, step 2.5 settle-on-wake, step 5b creating and opening an event (S1, S2),
# step 5b C the board (S3, board.json, and the same board on S2), and M4 the AI parse route.
# Routes read the request, call lifecycle.py, and turn its answer into JSON or a page. They do no money math.

import logging
from datetime import datetime, timezone

import psycopg
from flask import Flask, jsonify, redirect, render_template, request, url_for

import ai_parser
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
# The parse route's refusals (M4). Placeholders until Samuel adds them to UI_DESIGN section 4 (D57).
NO_PLEDGE_TEXT = "Type your pledge."
PLEDGE_TOO_LONG_TEXT = "Keep it to %d characters or fewer."
# The confirm route's refusals for min and conditions (D77), the limits filled in from config.py.
# Placeholders until Samuel adds them to UI_DESIGN section 4 (D57).
MIN_ABOVE_MAX_TEXT = "Your amount can't be more than your max."
TOO_MANY_CONDITIONS_TEXT = "You can name up to %d people."
NAME_TOO_LONG_TEXT = "Keep your name to %d characters or fewer."
CONDITION_NAME_TOO_LONG_TEXT = "Keep each name to %d characters or fewer."
# The board's texts, copied from docs/UI_DESIGN.md section 10. DRAFT_TEXT and the time formats are
# D57's placeholders, and the "Charge failed" word is in BOARD_STATUS_WORDS below.
DRAFT_TEXT = "This event isn't open yet."
OPEN_BANNER_TEXT = "Pledging open: %s left"
LAST_CALL_BANNER_TEXT = "Last call! Goal reached. Join in the next %s and everyone's share drops."
LOCKING_TEXT = "Locking shares…"
SETTLED_TEXT = "Done! Club receives %s"
SETTLED_NO_NET_TEXT = "Charged once. PayPal closes the rest of each hold."    # D54, D57
NEEDS_ATTENTION_TEXT = "Needs the treasurer's attention"
CANCELLING_TEXT = "Cancelling holds…"                                         # D45
EXPIRED_TEXT = "Goal not reached. Every hold was cancelled. Nobody paid."
GOAL_TEXT = "Goal %s so the club gets a full %s after fees"
CHARGED_WORD = "Charged %s"
WAITING_ON_TEXT = "Waiting on %s"    # D79, a placeholder (D57)
BOARD_STATUS_WORDS = {"PENDING_PAY": "Pledged", "HELD": "Held", "DECLINED": "Declined",
                      "FAILED": "Charge failed"}


# The one place the app reads the clock (AGENTS.md section 5: time is passed in). Always UTC.
# Tests replace this function to move time.
def utc_now():
    return datetime.now(timezone.utc)


# Settle-on-wake (docs/SYSTEM_DESIGN.md section 3): the free server sleeps and has no timer, so before
# each request, any event whose time is up is settled first. Requests for /static/ files (D41),
# /health (D46) and /favicon.ico (D72) skip it: they come often, and /health must stay a quick database
# ping. Browsers ask for /favicon.ico by themselves, so settling there would double every page visit.
@app.before_request
def settle_anything_due():
    if request.path.startswith("/static/") or request.path == "/health" or request.path == "/favicon.ico":
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


# Cents as the plain text a friend would type in the max box: 4000 -> "40.00", 100050 -> "1000.50".
# No "$" and no commas, so the page can put it straight back in the box and money.py can read it
# again at confirm. None (no amount) stays None, which JSON sends as null.
def plain_dollars_text(cents):
    if cents is None:
        return None
    return "{}.{:02d}".format(cents // 100, cents % 100)


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
    if outcome == "MIN_ABOVE_MAX":
        return message_answer(MIN_ABOVE_MAX_TEXT, 400)
    if outcome == "TOO_MANY_CONDITIONS":
        return message_answer(TOO_MANY_CONDITIONS_TEXT % config.MAX_CONDITIONS, 400)
    if outcome == "NAME_TOO_LONG":
        return message_answer(NAME_TOO_LONG_TEXT % config.MAX_NAME_CHARS, 400)
    if outcome == "CONDITION_NAME_TOO_LONG":
        return message_answer(CONDITION_NAME_TOO_LONG_TEXT % config.MAX_NAME_CHARS, 400)
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
# The page sends {"event_id": 7, "name": "Ana", "max": "40"}, and may add "min": "20" and
# "conditions": ["Jay"] (D77). "max" and "min" are the typed text: money.py turns them into whole cents,
# so no float is ever made (rule 1). An empty or missing "min" means no minimum. There is no email field
# (D62).
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
        min_cents = typed_min_cents(body.get("min"))
    except ValueError as error:
        return message_answer(str(error), 400)
    condition_names = body.get("conditions")
    if condition_names is None:
        condition_names = []
    if not names_are_a_list_of_text(condition_names):
        return message_answer(ERROR_TEXT, 400)
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            result = lifecycle.confirm_pledge(conn, event_id, name, max_cents, utc_now(),
                                              min_cents=min_cents, condition_names=condition_names)
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("POST /api/pledges: database error (%s)", type(error).__name__)
        return message_answer(ERROR_TEXT, 503)
    if result["outcome"] == "CONFIRMED":
        return jsonify({"pledger_token": result["pledger_token"],
                        "hold_text": HOLD_PROMISE_TEXT % dollars(max_cents)})
    return refusal_answer(result)


# The typed "min" as whole cents, or None when the box was left empty (missing, null or blank text).
# Anything else goes through money.py, which raises ValueError with the friendly message.
def typed_min_cents(text):
    if text is None or (isinstance(text, str) and text.strip() == ""):
        return None
    return money.dollars_text_to_cents(text)


# True if the page sent "conditions" as a list of texts (an empty list is fine). The limits on how many
# and how long are lifecycle's, so the AI and a hand-typed request meet the same rules (D77).
def names_are_a_list_of_text(condition_names):
    if not isinstance(condition_names, list):
        return False
    for condition_name in condition_names:
        if not isinstance(condition_name, str):
            return False
    return True


# D31: the AI reads one friend's pledge, typed in their own words, and suggests a status, max, min and
# conditions. The page sends {"event_id": 7, "text": "down if Jay goes, max 40"}. Nothing is saved
# (D31, D62): the suggestion goes back to the page, where the friend fixes it and confirms it with
# POST /api/pledges. The cheap checks run first, so an empty, too long or closed request never reaches
# the AI. If the AI fails or times out, parse_pledge gives the "please retype" suggestion, which is
# still a normal answer: the page shows the question and the friend fills in the boxes by hand.
# Privacy: nothing here logs the friend's text (ai_parser.py logs only the HTTP code, never the key).
@app.route("/api/pledges/parse", methods=["POST"])
def api_parse_pledge():
    body = json_body()
    event_id = body.get("event_id")
    text = body.get("text")
    if type(event_id) is not int or not isinstance(text, str):
        return message_answer(ERROR_TEXT, 400)
    text = text.strip()
    if text == "":
        return message_answer(NO_PLEDGE_TEXT, 400)
    if len(text) > config.MAX_PLEDGE_TEXT_CHARS:
        return message_answer(PLEDGE_TOO_LONG_TEXT % config.MAX_PLEDGE_TEXT_CHARS, 400)
    try:
        event = event_for_id(event_id)
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("POST /api/pledges/parse: database error (%s)", type(error).__name__)
        return message_answer(ERROR_TEXT, 503)
    if event is None:
        return message_answer(ERROR_TEXT, 404)
    if not lifecycle.pledging_is_open(event, utc_now()):
        return message_answer(CLOSED_TEXT, 409)
    return jsonify(suggestion_answer(ai_parser.parse_pledge(text)))


# One event's row, or None. The connection is closed before this returns, so the AI call that comes
# next never holds a database connection while it waits (up to config.AI_TIMEOUT_SECONDS).
# Database errors are left for the route to answer.
def event_for_id(event_id):
    conn = db.connect(config.DATABASE_URL)
    try:
        return lifecycle.find_event(conn, event_id)
    finally:
        conn.close()


# The parser's suggestion as the page receives it: the same five fields, with each amount as plain
# text like "40.00" instead of cents, ready to go back in the boxes (docs/UI_DESIGN.md section 10).
def suggestion_answer(suggestion):
    return {"status": suggestion["status"],
            "max": plain_dollars_text(suggestion["max_cents"]),
            "min": plain_dollars_text(suggestion["min_cents"]),
            "conditions": suggestion["conditions"],
            "follow_up_question": suggestion["follow_up_question"]}


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
# an unknown event. The board is the same one S3 shows (board_panel.html, D76).
@app.route("/admin/<admin_token>")
def admin_page(admin_token):
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            event = lifecycle.find_event_by_admin_token(conn, admin_token)
            facts = None
            if event is not None:
                facts = lifecycle.board_facts(conn, event["id"])
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("GET /admin/<token>: database error (%s)", type(error).__name__)
        return ERROR_TEXT, 503
    if event is None:
        return ERROR_TEXT, 404
    return render_template("admin.html", title=event["title"], share_link=share_link_for(event["id"]),
                           can_open=event["status"] == "DRAFT",
                           open_url=url_for("open_pledging", admin_token=admin_token),
                           board=board_for_event(facts, utc_now()))


# ---------- Step 5b C: the board (S3 and board.json, docs/UI_DESIGN.md section 10) ----------

# S3, the public board. Settle-on-wake has already run for this request (settle_anything_due).
@app.route("/e/<int:event_id>")
def board_page(event_id):
    try:
        board = board_for_event_id(event_id)
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("GET /e/<id>: database error (%s)", type(error).__name__)
        return ERROR_TEXT, 503
    if board is None:
        return ERROR_TEXT, 404
    return render_template("board.html", board=board)


# The same board as JSON, for Samuel's 10-second refresh. It is exactly the board object, so the page
# can update key by key. Errors come back as {"message": ...}, like the other JSON routes.
@app.route("/e/<int:event_id>/board.json")
def board_json(event_id):
    try:
        board = board_for_event_id(event_id)
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("GET /e/<id>/board.json: database error (%s)", type(error).__name__)
        return message_answer(ERROR_TEXT, 503)
    if board is None:
        return message_answer(ERROR_TEXT, 404)
    return jsonify(board)


# The board object for one event, or None if there's no such event. Database errors are left to the
# route, so each one can answer in its own way (a page or JSON).
def board_for_event_id(event_id):
    conn = db.connect(config.DATABASE_URL)
    try:
        facts = lifecycle.board_facts(conn, event_id)
    finally:
        conn.close()
    if facts is None:
        return None
    return board_for_event(facts, utc_now())


# Turn lifecycle.board_facts (cents) into the exact board object of UI_DESIGN.md section 10 (finished
# text). Formatting only: every amount already comes from SQL's SUM (D43) or money.py (rule 2).
def board_for_event(facts, now):
    event = facts["event"]
    seconds = seconds_left(event, now)
    return {
        "event_id": event["id"],
        "title": event["title"],
        "status": event["status"],
        "banner_text": banner_text(facts, seconds),
        "seconds_left": seconds,
        "goal_text": GOAL_TEXT % (dollars(facts["goal_cents"]), dollars(event["deposit_cents"])),
        "held_total_text": dollars(facts["held_total_cents"]),
        "progress_percent": facts["progress_percent"],
        "pledging_open": lifecycle.pledging_is_open(event, now),
        "rows": board_row_texts(facts),
    }


# One text row per pledge, in the order board_facts gives them. estimated_share_text is "" except
# during LAST_CALL, when it shows what this person would pay if last call ended now.
# D79: counted is true for a held pledge the circle rule counts, and for one already charged or failed at
# lock (they were counted). waiting_on_text is "Waiting on Jay" for a held pledge that isn't counted yet,
# and "" for everyone else. The ids stay in facts and never reach the board.
def board_row_texts(facts):
    rows = []
    for row in facts["rows"]:
        estimated_share_text = ""
        if row["id"] in facts["estimated_shares"]:
            estimated_share_text = dollars(facts["estimated_shares"][row["id"]])
        counted = row["id"] in facts["counted_ids"] or row["status"] in ("CHARGED", "FAILED")
        rows.append({"name": row["name"], "status": row["status"], "status_word": status_word(row),
                     "max_text": dollars(row["max_cents"]), "estimated_share_text": estimated_share_text,
                     "counted": counted,
                     "waiting_on_text": waiting_on_text(facts["waiting_on"].get(row["id"], []))})
    return rows


# "Waiting on Jay", "Waiting on Jay and Maya", "Waiting on Jay, Maya and Kim"; "" when there is nobody.
# A placeholder wording until Samuel approves it (D57).
def waiting_on_text(names):
    if len(names) == 0:
        return ""
    if len(names) == 1:
        return WAITING_ON_TEXT % names[0]
    return WAITING_ON_TEXT % (", ".join(names[:-1]) + " and " + names[-1])


# The word for one row. A CHARGED row shows the share it paid, saved at lock.
def status_word(row):
    if row["status"] == "CHARGED":
        return CHARGED_WORD % dollars(row["share_cents"])
    return BOARD_STATUS_WORDS.get(row["status"], "")


# Whole seconds until pledging closes: last_call_ends during LAST_CALL, hard_deadline while OPEN, never
# below 0, and 0 if that time is missing (treated as closed, like pledging_is_open). None for every
# other status, which has no countdown. Samuel's board.js ticks it down live.
def seconds_left(event, now):
    if event["status"] == "LAST_CALL":
        closes_at = event["last_call_ends"]
    elif event["status"] == "OPEN":
        closes_at = event["hard_deadline"]
    else:
        return None
    if closes_at is None:
        return 0
    seconds = int((closes_at - now).total_seconds())
    if seconds < 0:
        return 0
    return seconds


# The banner for the event's status (UI_DESIGN.md section 10). seconds is seconds_left's answer.
def banner_text(facts, seconds):
    status = facts["event"]["status"]
    if status == "DRAFT":
        return DRAFT_TEXT
    if status == "OPEN":
        return OPEN_BANNER_TEXT % time_left_text(seconds)
    if status == "LAST_CALL":
        return LAST_CALL_BANNER_TEXT % countdown_text(seconds)
    if status == "LOCKING" or status == "CHARGING":
        return LOCKING_TEXT
    if status == "SETTLED":
        if facts["club_net_cents"] is None:
            return SETTLED_NO_NET_TEXT
        return SETTLED_TEXT % dollars(facts["club_net_cents"])
    if status == "NEEDS_ATTENTION":
        return NEEDS_ATTENTION_TEXT
    if status == "EXPIRED":
        if facts["any_hold_created"]:
            return CANCELLING_TEXT
        return EXPIRED_TEXT
    return ""


# Time left while OPEN: "1 h 5 min", "9 min" or "less than a minute" (D57 placeholder formats).
# Whole minutes, rounded down.
def time_left_text(seconds):
    if seconds < 60:
        return "less than a minute"
    minutes = seconds // 60
    if minutes < 60:
        return "%d min" % minutes
    return "%d h %d min" % (minutes // 60, minutes % 60)


# The last-call countdown: "4:59", or "1:02:03" from one hour up (D57 placeholder format).
def countdown_text(seconds):
    if seconds < 3600:
        return "%d:%02d" % (seconds // 60, seconds % 60)
    return "%d:%02d:%02d" % (seconds // 3600, seconds % 3600 // 60, seconds % 60)


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
