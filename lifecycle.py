# Every status change for events, pledges and holds (docs/STATE_MACHINE.md). Owner: Emmanuel.
# This is the only file that connects the database, the PayPal calls and the money math.
#
# Each function that talks to PayPal takes a `paypal` argument: app.py passes the real paypal_client
# module, and the tests pass tests/fake_paypal.py, which has the same function names.
# Each function that depends on time takes `now`, so tests can control the clock (AGENTS.md section 5).
# Each function takes `conn`, a connection from db.connect(). Every write is saved the moment it runs
# (db.py's autocommit), which is what "save before you send" relies on (rule 3).
#
# Step 2.3 added the pledge and hold steps. Step 2.5 added the goal check, settle-on-wake, lock and
# charge, and expire. Step 5b added creating and opening an event. All the money math in them is
# Malama's money.py (rule 2).
# The log shows IDs and statuses only: never a token, a name or an email (docs/SECURITY.md).

import logging
import secrets
import uuid
from datetime import datetime

import psycopg

import conditions
import config
import db
import money

logger = logging.getLogger(__name__)

# The event statuses in which people may pledge and place holds (docs/SYSTEM_DESIGN.md section 5A).
PLEDGING_STATUSES = ("OPEN", "LAST_CALL")


# A new PayPal-Request-Id. A UUID is random enough that two requests never share one by accident.
def new_request_id():
    return str(uuid.uuid4())


# A new private link token (docs/DATA_MODEL.md: secrets.token_urlsafe(24)). "secrets" is Python's
# module for things that must be impossible to guess, unlike "random".
def new_token():
    return secrets.token_urlsafe(24)


# PayPal's times look like "2026-11-25T21:04:51Z". fromisoformat turns that into a UTC datetime.
# A missing or strange value becomes None, so a bad expiry can't crash us right after a hold was placed.
def read_paypal_time(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


# True only if the event takes pledges right now: OPEN before its hard deadline, or LAST_CALL before
# last call ends (D04). The clock is checked too, in case settling failed earlier in this request
# (approved item 11). last_call_ends is never after the hard deadline, so a LAST_CALL event needs only it.
def pledging_is_open(event, now):
    if event is None or event["status"] not in PLEDGING_STATUSES:
        return False
    if event["status"] == "LAST_CALL":
        closes_at = event["last_call_ends"]
    else:
        closes_at = event["hard_deadline"]
    if closes_at is None:
        return False
    return now < closes_at


def find_event(conn, event_id):
    return db.fetch_one(conn, "SELECT * FROM events WHERE id = %s", (event_id,))


def find_pledge_by_token(conn, pledger_token):
    return db.fetch_one(conn, "SELECT * FROM pledges WHERE pledger_token = %s", (pledger_token,))


# Find a pledge by name, ignoring case. lower(name) = lower(%s) is the same rule as the unique name
# index in schema.sql, so Python and the database agree on who is the same person.
def find_pledge_by_name(conn, event_id, name):
    return db.fetch_one(conn, "SELECT * FROM pledges WHERE event_id = %s AND lower(name) = lower(%s)",
                        (event_id, name))


# D31: the friend confirmed a name and a max, so save the pledge (PENDING_PAY) and return its private
# token. D26: the same name again reuses that person's unpaid pledge, instead of failing on the unique
# name index. max_cents is whole cents: the route turned the typed "40" into 4000 with money.py.
# The max must be from $5 to $2,000 (config.py, D58).
# D77: min_cents ("in for $20", shown only, D12) and condition_names ("only if Jay's in") are saved too.
# Every limit is checked before the database is opened. The pledge and its conditions are then saved in
# ONE transaction, so a pledge is never saved without the conditions the friend confirmed: that would
# turn "only if Jay's in" into an unconditional pledge. A retry replaces the old min and conditions.
# Saving conditions does not decide who is counted: counted_held_pledges does, from HELD pledges (D70).
def confirm_pledge(conn, event_id, name, max_cents, now, min_cents=None, condition_names=()):
    name = conditions.tidy_name(name)
    if name == "":
        return {"outcome": "NO_NAME"}
    if len(name) > config.MAX_NAME_CHARS:
        return {"outcome": "NAME_TOO_LONG"}
    if max_cents < config.MIN_MAX_CENTS:
        return {"outcome": "TOO_SMALL"}
    if max_cents > config.MAX_MAX_CENTS:
        return {"outcome": "TOO_BIG"}
    if min_cents is not None and min_cents > max_cents:
        return {"outcome": "MIN_ABOVE_MAX"}
    cleaned = clean_condition_names(condition_names, name)
    for condition_name in cleaned:
        if len(condition_name) > config.MAX_NAME_CHARS:
            return {"outcome": "CONDITION_NAME_TOO_LONG"}
    if len(cleaned) > config.MAX_CONDITIONS:
        return {"outcome": "TOO_MANY_CONDITIONS"}
    event = find_event(conn, event_id)
    if event is None:
        return {"outcome": "NOT_FOUND"}
    if not pledging_is_open(event, now):
        return {"outcome": "CLOSED"}
    for attempt in range(2):
        try:
            return save_pledge_and_conditions(conn, event_id, name, max_cents, min_cents, cleaned)
        except psycopg.errors.UniqueViolation:
            # Someone saved the same name a moment ago, between our check and our INSERT. That whole
            # transaction was rolled back; the second try finds their pledge and reuses it (D26).
            logger.info("event %d: the same name was saved at the same moment, trying again", event_id)
    return {"outcome": "ERROR"}


# D77: the condition names to save, tidied (conditions.tidy_name) with blanks removed, the pledger's own
# name removed (a condition on yourself is always met, so it would only add a row that does nothing),
# and repeats removed. Names are compared with name_key, so "Jay", " jay " and "JAY" are one name. The
# first spelling is kept. Pure: no database. The limits on length and count are checked by the caller.
def clean_condition_names(condition_names, own_name):
    seen = [conditions.name_key(own_name)]
    cleaned = []
    for condition_name in condition_names:
        tidy = conditions.tidy_name(condition_name)
        if tidy != "" and conditions.name_key(tidy) not in seen:
            cleaned.append(tidy)
            seen.append(conditions.name_key(tidy))
    return cleaned


# One try at saving the pledge and its conditions, all in one transaction (D77): `with conn.transaction()`
# is BEGIN ... COMMIT even though db.py runs in autocommit, and any error inside rolls all of it back.
# The conditions are replaced only when the pledge was really confirmed, so a refused retry (the pledge
# is already HELD) leaves the old conditions alone. A UniqueViolation is left for confirm_pledge to retry.
def save_pledge_and_conditions(conn, event_id, name, max_cents, min_cents, cleaned):
    with conn.transaction():
        existing = find_pledge_by_name(conn, event_id, name)
        if existing is None:
            result = create_pledge(conn, event_id, name, max_cents, min_cents)
        else:
            result = reuse_pledge(conn, existing, max_cents, min_cents)
        if result["outcome"] == "CONFIRMED":
            replace_conditions(conn, result["pledge_id"], cleaned)
        return result


# A brand-new pledge. Its status starts as PENDING_PAY (the column's default in schema.sql).
def create_pledge(conn, event_id, name, max_cents, min_cents):
    row = db.fetch_one(conn, "INSERT INTO pledges (event_id, name, max_cents, min_cents, pledger_token) "
                             "VALUES (%s, %s, %s, %s, %s) RETURNING id, pledger_token",
                       (event_id, name, max_cents, min_cents, new_token()))
    return {"outcome": "CONFIRMED", "pledge_id": row["id"], "pledger_token": row["pledger_token"]}


# D26 and D32: only an unpaid pledge (PENDING_PAY or DECLINED) can be reused. It gets the new max and min
# (None clears the min), goes back to PENDING_PAY, and gets a new token, so a page still holding the old
# token can no longer start or authorize a hold. This is a compare-and-set: if the pledge became HELD a
# moment ago, 0 rows change and the answer is "[Name] has already pledged."
def reuse_pledge(conn, pledge, max_cents, min_cents):
    token = new_token()
    changed = db.run(conn, "UPDATE pledges SET max_cents = %s, min_cents = %s, status = 'PENDING_PAY', "
                           "pledger_token = %s WHERE id = %s AND status IN ('PENDING_PAY', 'DECLINED')",
                     (max_cents, min_cents, token, pledge["id"]))
    if changed == 0:
        return {"outcome": "ALREADY_PLEDGED", "name": pledge["name"]}
    return {"outcome": "CONFIRMED", "pledge_id": pledge["id"], "pledger_token": token}


# D77: a pledge's conditions are exactly these names. The old rows are deleted first, so a retry replaces
# the conditions and never adds to them, and a first save and a retry run the same code.
def replace_conditions(conn, pledge_id, names):
    db.run(conn, "DELETE FROM pledge_conditions WHERE pledge_id = %s", (pledge_id,))
    for condition_name in names:
        db.run(conn, "INSERT INTO pledge_conditions (pledge_id, depends_on_name) VALUES (%s, %s)",
               (pledge_id, condition_name))


# Step 1 of a hold. Save a new hold row with its PayPal-Request-Id first (rule 3), then create the PayPal
# order for the pledge's max, and save the order ID the moment it comes back. Nothing is held yet: that
# happens only after the card is approved in the browser and authorize_hold runs.
def start_hold(conn, pledger_token, now, paypal):
    pledge = find_pledge_by_token(conn, pledger_token)
    if pledge is None:
        return {"outcome": "NOT_FOUND"}
    if not pledging_is_open(find_event(conn, pledge["event_id"]), now):
        return {"outcome": "CLOSED"}
    if pledge["status"] == "HELD":
        return {"outcome": "ALREADY_PLEDGED", "name": pledge["name"]}
    if pledge["status"] != "PENDING_PAY":
        return {"outcome": "NOT_HELD"}
    request_id = new_request_id()
    hold = db.fetch_one(conn, "INSERT INTO holds (pledge_id, create_request_id, amount_cents) "
                              "VALUES (%s, %s, %s) RETURNING id",
                        (pledge["id"], request_id, pledge["max_cents"]))
    answer = paypal.create_order(pledge["max_cents"], "pledge-%d" % pledge["id"], request_id)
    order_id = answer["data"].get("id")
    if order_id is not None:
        db.run(conn, "UPDATE holds SET order_id = %s WHERE id = %s", (order_id, hold["id"]))
    if order_id is None or answer["data"].get("status") != "CREATED":
        logger.warning("create order for hold %d failed: HTTP %s, PayPal-Debug-Id %s",
                       hold["id"], answer["http_status"], answer["debug_id"])
        return {"outcome": "NOT_HELD"}
    return {"outcome": "ORDER_CREATED", "order_id": order_id}


# The hold for this order, with the pledge's details, but only if the token matches the pledge's
# current one. So nobody can authorize someone else's order, and an old token stops working (D32).
def find_hold_for_order(conn, order_id, pledger_token):
    return db.fetch_one(conn, "SELECT holds.*, pledges.event_id, pledges.name, pledges.pledger_token, "
                              "pledges.status AS pledge_status "
                              "FROM holds JOIN pledges ON pledges.id = holds.pledge_id "
                              "WHERE holds.order_id = %s AND pledges.pledger_token = %s",
                        (order_id, pledger_token))


# Step 2 of a hold, after the browser says the card was approved. Authorize the order, save PayPal's
# answer the moment it arrives (rule 3), then act on the authorization's status, never on the HTTP code
# alone (rule 5). The checks before the call mean we never place a hold we already know we can't keep.
def authorize_hold(conn, order_id, pledger_token, now, paypal):
    hold = find_hold_for_order(conn, order_id, pledger_token)
    if hold is None:
        return {"outcome": "NOT_FOUND"}
    if hold["authorize_request_id"] is not None:
        return saved_answer(conn, hold["id"])
    if not pledging_is_open(find_event(conn, hold["event_id"]), now):
        return {"outcome": "CLOSED"}
    if hold["pledge_status"] == "HELD":
        return {"outcome": "ALREADY_PLEDGED", "name": hold["name"]}
    if hold["pledge_status"] != "PENDING_PAY":
        return {"outcome": "NOT_HELD"}
    request_id = claim_authorize(conn, hold["id"])
    if request_id is None:
        return saved_answer(conn, hold["id"])
    authorization = send_authorize(conn, hold, request_id, paypal)
    return act_on_authorization(conn, hold, authorization, now, paypal)


# Save the authorize call's PayPal-Request-Id before the call (rule 3). It's a compare-and-set on the
# empty column: if two requests try to authorize the same order at once (a double click), only one gets
# an ID. The other returns None and never calls PayPal, so one order is never authorized twice.
def claim_authorize(conn, hold_id):
    request_id = new_request_id()
    changed = db.run(conn, "UPDATE holds SET authorize_request_id = %s "
                           "WHERE id = %s AND authorize_request_id IS NULL",
                     (request_id, hold_id))
    if changed == 0:
        return None
    return request_id


# Call authorize. If no answer came back at all, try once more with the same saved request ID
# (PAYPAL_INTEGRATION.md section 5, rule 4). Then save the authorization's ID, status and expiry before
# doing anything else (rule 3, test F1). Returns the authorization, or {} if PayPal sent none.
def send_authorize(conn, hold, request_id, paypal):
    answer = paypal.authorize_order(hold["order_id"], request_id)
    if answer["http_status"] is None:
        answer = paypal.authorize_order(hold["order_id"], request_id)
    authorization = paypal.first_authorization(answer["data"])
    if "id" in authorization:
        db.run(conn, "UPDATE holds SET auth_id = %s, status = %s, expires_at = %s WHERE id = %s",
               (authorization["id"], authorization.get("status", "UNKNOWN"),
                read_paypal_time(authorization.get("expiration_time")), hold["id"]))
    else:
        logger.warning("authorize for hold %d: no authorization came back (HTTP %s, PayPal-Debug-Id %s)",
                       hold["id"], answer["http_status"], answer["debug_id"])
    return authorization


# What the authorization's status means (PAYPAL_INTEGRATION.md section 4):
# DENIED is a declined card: the pledge is DECLINED and there is nothing to void.
# CREATED is a hold: the pledge becomes HELD, unless it can't any more (then give_back_hold).
# Anything else is "not held": if PayPal made an authorization anyway, void it.
def act_on_authorization(conn, hold, authorization, now, paypal):
    status = authorization.get("status")
    if status == "DENIED":
        db.run(conn, "UPDATE pledges SET status = 'DECLINED' "
                     "WHERE id = %s AND status = 'PENDING_PAY' AND pledger_token = %s",
               (hold["pledge_id"], hold["pledger_token"]))
        return {"outcome": "DECLINED"}
    if status != "CREATED":
        if "id" in authorization:
            void_hold(conn, hold["id"], paypal)
        return {"outcome": "NOT_HELD"}
    if mark_held(conn, hold, now):
        logger.info("hold %d is CREATED, pledge %d is HELD", hold["id"], hold["pledge_id"])
        check_goal_after_hold(conn, hold["event_id"], now)
        return {"outcome": "HELD", "held_cents": hold["amount_cents"]}
    return give_back_hold(conn, hold, now, paypal)


# PENDING_PAY -> HELD in one compare-and-set: only while this pledge still waits, still has this token,
# and its event still takes pledges (approved item 4). max_cents becomes the amount actually held, so a
# share can never be more than the hold.
# FOR SHARE locks the event row until this change is saved. A lock or an expiry that starts at the same
# moment has to wait, and then sees this pledge as HELD. If it got there first, this sees its new status
# and fails. Either way, no hold is ever missed by both.
# "with conn.transaction()" runs the SELECT and the UPDATE as one unit, saved together at the end.
def mark_held(conn, hold, now):
    with conn.transaction():
        event = db.fetch_one(conn, "SELECT * FROM events WHERE id = %s FOR SHARE", (hold["event_id"],))
        if not pledging_is_open(event, now):
            return False
        changed = db.run(conn, "UPDATE pledges SET status = 'HELD', max_cents = %s "
                               "WHERE id = %s AND status = 'PENDING_PAY' AND pledger_token = %s",
                         (hold["amount_cents"], hold["pledge_id"], hold["pledger_token"]))
    return changed == 1


# The hold was placed, but the pledge can't become HELD: pledging closed during the call (F11), another
# hold for the same pledge got there first, or a newer token replaced this one (D32). Void this hold at
# once, so it's never left open. If pledging closed, the pledge is DROPPED.
def give_back_hold(conn, hold, now, paypal):
    void_hold(conn, hold["id"], paypal)
    logger.info("hold %d placed but not kept, so it was voided", hold["id"])
    if not pledging_is_open(find_event(conn, hold["event_id"]), now):
        db.run(conn, "UPDATE pledges SET status = 'DROPPED' WHERE id = %s AND status = 'PENDING_PAY'",
               (hold["pledge_id"],))
        return {"outcome": "CLOSED_AND_VOIDED"}
    pledge = db.fetch_one(conn, "SELECT name, status FROM pledges WHERE id = %s", (hold["pledge_id"],))
    if pledge["status"] == "HELD":
        return {"outcome": "ALREADY_PLEDGED", "name": pledge["name"]}
    return {"outcome": "NOT_HELD"}


# The answer for an order whose authorize was already sent: read what was saved, and never call PayPal
# again. This is what stops a second click from placing a second hold.
def saved_answer(conn, hold_id):
    hold = db.fetch_one(conn, "SELECT holds.status, holds.amount_cents, pledges.status AS pledge_status "
                              "FROM holds JOIN pledges ON pledges.id = holds.pledge_id WHERE holds.id = %s",
                        (hold_id,))
    if hold["status"] == "CREATED" and hold["pledge_status"] == "HELD":
        return {"outcome": "HELD", "held_cents": hold["amount_cents"]}
    if hold["status"] == "DENIED":
        return {"outcome": "DECLINED"}
    return {"outcome": "NOT_HELD"}


# Cancel one hold (PAYPAL_INTEGRATION.md section 4). The void's PayPal-Request-Id is saved first, and
# any later try reuses the saved one (rules 3 and 4). A void answers 204 with no body, so the hold is
# read back with a GET, and PayPal's real status is saved whatever the void answered.
# Returns that status, or None if there was nothing to void or no answer.
def void_hold(conn, hold_id, paypal):
    db.run(conn, "UPDATE holds SET void_request_id = %s "
                 "WHERE id = %s AND auth_id IS NOT NULL AND void_request_id IS NULL",
           (new_request_id(), hold_id))
    hold = db.fetch_one(conn, "SELECT auth_id, void_request_id FROM holds WHERE id = %s", (hold_id,))
    if hold["auth_id"] is None:
        return None
    paypal.void_authorization(hold["auth_id"], hold["void_request_id"])
    check = paypal.get_authorization(hold["auth_id"])
    status = check["data"].get("status")
    if check["http_status"] == 200 and status is not None:
        db.run(conn, "UPDATE holds SET status = %s WHERE id = %s", (status, hold_id))
    logger.info("void hold %d: PayPal now says %s", hold_id, status)
    return status


# ---------- Step 2.5: goal check, settle-on-wake, lock and charge, expire ----------

# Every HELD pledge of the event with one CREATED hold each, in join order (created_at, then id), the
# order money.compute_shares_cents needs (MONEY_RULES.md section 6). These are the pledges that could be
# charged; counted_among picks which of them are counted (D70). Only one hold per pledge is taken, so
# nobody can be charged twice even if a second hold was left open by mistake. A HELD pledge with no
# CREATED hold (a hold voided by hand) can't be charged, so it isn't listed: drop_pledges_without_a_hold
# drops it.
def held_pledges(conn, event_id):
    pledges = db.fetch_all(conn, "SELECT id, name, max_cents FROM pledges WHERE event_id = %s AND status = 'HELD' "
                                 "ORDER BY created_at, id", (event_id,))
    chargeable = []
    for pledge in pledges:
        hold = db.fetch_one(conn, "SELECT id, auth_id FROM holds WHERE pledge_id = %s AND status = 'CREATED' "
                                  "ORDER BY id LIMIT 1", (pledge["id"],))
        if hold is not None:
            pledge["hold_id"] = hold["id"]
            pledge["auth_id"] = hold["auth_id"]
            chargeable.append(pledge)
    return chargeable


# The names one pledge's conditions need ("only if Jay's in"), in the order they were saved.
def pledge_conditions_of(conn, pledge_id):
    rows = db.fetch_all(conn, "SELECT depends_on_name FROM pledge_conditions WHERE pledge_id = %s ORDER BY id",
                        (pledge_id,))
    names = []
    for row in rows:
        names.append(row["depends_on_name"])
    return names


# D70: which of these held pledges are counted. Each pledge's conditions are loaded, Malama's circle rule
# (conditions.counted_pledges, D06) gives the counted names, and those names are matched back to the
# pledges with name_key. Names are unique per event, ignoring case (the unique index in schema.sql), so
# each name matches one pledge. Only someone in `held` (HELD, with a CREATED hold: someone who can really
# be charged) can meet a condition. The result keeps join order, which D13 needs.
def counted_among(conn, held):
    circle_input = []
    for pledge in held:
        circle_input.append({"name": pledge["name"], "conditions": pledge_conditions_of(conn, pledge["id"])})
    counted_keys = []
    for name in conditions.counted_pledges(circle_input):
        counted_keys.append(conditions.name_key(name))
    counted = []
    for pledge in held:
        if conditions.name_key(pledge["name"]) in counted_keys:
            counted.append(pledge)
    return counted


# D70: the counted pledges of an event, in join order. The goal check, the lock and the board all use
# this, so they can never disagree about who counts (C8). It is worked out every time and never stored
# (D78), so it can never disagree with the holds either.
def counted_held_pledges(conn, event_id):
    return counted_among(conn, held_pledges(conn, event_id))


# The max of each pledge, in the same order: the list Malama's money.py functions take.
def max_list(pledges):
    maxes = []
    for pledge in pledges:
        maxes.append(pledge["max_cents"])
    return maxes


# Did this event reach its goal? If so, open last call: OPEN -> LAST_CALL in one compare-and-set
# (docs/SYSTEM_DESIGN.md section 5B). Last call lasts one window from now, but never past the hard
# deadline (D04): last_call_ends = min(now + window, hard_deadline). When settling finds the goal only
# after the deadline, that gives the deadline itself, so the same request locks at once.
# Runs after each new hold, and once more when a due event is settled. True if this call opened it.
def check_goal(conn, event_id, now):
    event = find_event(conn, event_id)
    if event is None or event["status"] != "OPEN":
        return False
    if not money.goal_is_reached(event["deposit_cents"], max_list(counted_held_pledges(conn, event_id))):
        return False
    last_call_ends = min(now + last_call_window(event), event["hard_deadline"])
    changed = db.run(conn, "UPDATE events SET status = 'LAST_CALL', last_call_ends = %s "
                           "WHERE id = %s AND status = 'OPEN'", (last_call_ends, event_id))
    if changed == 1:
        logger.info("event %d reached its goal: last call is open", event_id)
    return changed == 1


# The goal check right after a hold. The hold is already placed, so a database error here must not turn
# "Held" into an error message: it's logged, and settling checks the goal again at the deadline.
def check_goal_after_hold(conn, event_id, now):
    try:
        check_goal(conn, event_id, now)
    except psycopg.Error as error:
        logger.warning("goal check for event %d failed: database error (%s)", event_id, type(error).__name__)


# Settle-on-wake (docs/SYSTEM_DESIGN.md section 3): settle every event whose time is up.
# OPEN past its hard deadline: check the goal one last time (in case the check after a hold failed),
# then lock and charge if last call opened, otherwise expire. LAST_CALL past last_call_ends: lock and
# charge. Each of the three steps starts with its own compare-and-set, so a step does nothing unless
# the status fits, and two requests settling at once can't both act (test E8).
# A database error on one event is logged, and the next event is still settled.
def settle_due_events(conn, now, paypal):
    due = db.fetch_all(conn, "SELECT id FROM events "
                             "WHERE (status = 'OPEN' AND hard_deadline <= %s) "
                             "OR (status = 'LAST_CALL' AND last_call_ends <= %s) ORDER BY id",
                       (now, now))
    for event in due:
        try:
            check_goal(conn, event["id"], now)
            lock_and_charge(conn, event["id"], now, paypal)
            expire_event(conn, event["id"], now, paypal)
        except psycopg.Error as error:
            logger.warning("settling event %d failed: database error (%s)", event["id"], type(error).__name__)


# The only path that captures money (AGENTS.md rule 6, docs/SYSTEM_DESIGN.md section 5C).
# Step 1 is the compare-and-set LAST_CALL -> LOCKING: only the request whose UPDATE changed that 1 row
# goes on, so two requests can never both charge (test E8). The same UPDATE saves lock_started_at
# (D36; resuming a lock that died halfway is M2, D27).
# D70: only the counted pledges are charged. `held` is every pledge that could be charged and `pledges`
# the counted ones among them; the holds of the others are voided before CHARGING, and they are dropped.
# Returns what happened: NOT_LOCKED, EXPIRED, SETTLED or NEEDS_ATTENTION.
def lock_and_charge(conn, event_id, now, paypal):
    won = db.run(conn, "UPDATE events SET status = 'LOCKING', lock_started_at = %s "
                       "WHERE id = %s AND status = 'LAST_CALL' AND last_call_ends <= %s",
                 (now, event_id, now))
    if won == 0:
        return "NOT_LOCKED"
    event = find_event(conn, event_id)
    held = held_pledges(conn, event_id)
    pledges = counted_among(conn, held)
    if not money.goal_is_reached(event["deposit_cents"], max_list(pledges)):
        return give_up_lock(conn, event_id, paypal)
    shares = save_shares(conn, event, pledges)
    void_uncounted_holds(conn, held, pledges, paypal)
    drop_pledges_without_a_hold(conn, event_id)
    db.run(conn, "UPDATE events SET status = 'CHARGING' WHERE id = %s AND status = 'LOCKING'", (event_id,))
    failed = 0
    for position in range(len(pledges)):
        if not charge_one_pledge(conn, pledges[position], shares[position], paypal):
            failed = failed + 1
    final_status = "SETTLED"
    if failed > 0:
        final_status = "NEEDS_ATTENTION"
    db.run(conn, "UPDATE events SET status = %s WHERE id = %s AND status = 'CHARGING'", (final_status, event_id))
    logger.info("event %d is %s: %d of %d charges failed", event_id, final_status, failed, len(pledges))
    return final_status


# D70: at lock, a HELD pledge that isn't counted (its condition never came true) is never charged. Each
# of its CREATED holds is voided by void_hold, which saves the void's PayPal-Request-Id first and reads
# the hold back with a GET (rules 3 and 4); drop_pledges_without_a_hold then makes the pledge DROPPED.
# A void that doesn't read back VOIDED is logged, and its pledge stays HELD with the hold CREATED for
# M2's cleanup sweep (D45). It still can't be charged, because only `counted` is charged.
# The log shows pledge and hold IDs only, never a name (docs/SECURITY.md).
def void_uncounted_holds(conn, held, counted, paypal):
    counted_ids = []
    for pledge in counted:
        counted_ids.append(pledge["id"])
    for pledge in held:
        if pledge["id"] in counted_ids:
            continue
        logger.info("pledge %d isn't counted at lock (D70), so its hold is voided", pledge["id"])
        holds = db.fetch_all(conn, "SELECT id FROM holds WHERE pledge_id = %s AND status = 'CREATED' ORDER BY id",
                             (pledge["id"],))
        for hold in holds:
            status = void_hold(conn, hold["id"], paypal)
            if status != "VOIDED":
                logger.warning("pledge %d: hold %d did not read back VOIDED (%s); left for the cleanup sweep",
                               pledge["id"], hold["id"], status)


# At lock, the goal is no longer reached. STATE_MACHINE.md's invariants say this can't happen, so it
# means a bug: charge nobody, cancel every hold, and end the event EXPIRED (D38, test F13).
def give_up_lock(conn, event_id, paypal):
    logger.warning("event %d: goal not reached at lock, so nobody is charged", event_id)
    release_holds(conn, event_id, paypal)
    db.run(conn, "UPDATE events SET status = 'EXPIRED' WHERE id = %s AND status = 'LOCKING'", (event_id,))
    return "EXPIRED"


# Work out every share and save it before any charge (STATE_MACHINE.md: LOCKING saves every share_cents
# and goal_cents). The math is Malama's money.py (rule 2): the fee-adjusted goal for this many people,
# then the even split, never above anyone's max, in join order. Returns the shares in the same order.
def save_shares(conn, event, pledges):
    goal_cents = money.fee_adjusted_goal_cents(event["deposit_cents"], len(pledges))
    shares = money.compute_shares_cents(goal_cents, max_list(pledges))
    db.run(conn, "UPDATE events SET goal_cents = %s WHERE id = %s", (goal_cents, event["id"]))
    for position in range(len(pledges)):
        db.run(conn, "UPDATE pledges SET share_cents = %s WHERE id = %s",
               (shares[position], pledges[position]["id"]))
    return shares


# Charge one pledge its share. Called only by lock_and_charge, after it won LAST_CALL -> LOCKING
# (rule 6): this is the app's one capture call. The capture row and its PayPal-Request-Id are saved
# before the call (rule 3), and PayPal's capture ID the moment it comes back. Only HTTP 201 with status
# COMPLETED counts as charged. Anything else, including no answer, is a failure, with no retry in M1
# (D39). Returns True if the pledge was charged.
def charge_one_pledge(conn, pledge, share_cents, paypal):
    request_id = new_request_id()
    capture = db.fetch_one(conn, "INSERT INTO captures (hold_id, request_id, attempt, amount_cents) "
                                 "VALUES (%s, %s, 1, %s) RETURNING id",
                           (pledge["hold_id"], request_id, share_cents))
    answer = paypal.capture_authorization(pledge["auth_id"], share_cents, request_id)
    capture_id = answer["data"].get("id")
    if capture_id is not None:
        db.run(conn, "UPDATE captures SET capture_id = %s WHERE id = %s", (capture_id, capture["id"]))
    if answer["http_status"] == 201 and answer["data"].get("status") == "COMPLETED":
        record_charge(conn, pledge, capture["id"], capture_id, paypal)
        return True
    record_failed_charge(conn, pledge, capture["id"], answer, paypal)
    return False


# The capture went through: the capture row is COMPLETED, the hold CAPTURED and the pledge CHARGED.
# Then the capture is read back for PayPal's real fee and net (STATE_MACHINE.md), which become the
# treasurer's real number (MONEY_RULES.md section 7). If that read fails, the charge still stands:
# only the fee and net stay empty, and the log says so.
def record_charge(conn, pledge, capture_row_id, capture_id, paypal):
    db.run(conn, "UPDATE captures SET status = 'COMPLETED' WHERE id = %s", (capture_row_id,))
    db.run(conn, "UPDATE holds SET status = 'CAPTURED' WHERE id = %s", (pledge["hold_id"],))
    db.run(conn, "UPDATE pledges SET status = 'CHARGED' WHERE id = %s AND status = 'HELD'", (pledge["id"],))
    check = paypal.get_capture(capture_id)
    breakdown = check["data"].get("seller_receivable_breakdown", {})
    fee_cents = read_paypal_cents(breakdown.get("paypal_fee"), paypal)
    net_cents = read_paypal_cents(breakdown.get("net_amount"), paypal)
    db.run(conn, "UPDATE captures SET fee_cents = %s, net_cents = %s WHERE id = %s",
           (fee_cents, net_cents, capture_row_id))
    if fee_cents is None or net_cents is None:
        logger.warning("capture %s: charged, but the fee and net couldn't be read (HTTP %s, PayPal-Debug-Id %s)",
                       capture_id, check["http_status"], check["debug_id"])


# One money amount from PayPal, like {"currency_code": "USD", "value": "0.62"}, as whole cents (62).
# The text becomes cents with paypal_client's helper, so no float is made (rule 1). Anything missing,
# in another currency or not an amount becomes None.
def read_paypal_cents(amount, paypal):
    if not isinstance(amount, dict) or amount.get("currency_code") != "USD":
        return None
    try:
        return paypal.paypal_string_to_cents(amount["value"])
    except (KeyError, TypeError, ValueError):
        return None


# Anything but 201 COMPLETED is a failed charge in M1, with no retry (D39). Read the hold back and save
# its real status, save PayPal's reason, and mark the pledge FAILED. If the read-back says CAPTURED, the
# money did move (for example, PayPal's answer was lost on the way back). D47 still marks the pledge
# FAILED in M1 and logs it as an error; finding that capture is M2 (F5, F6). That capture row stays
# PENDING, because its real result is unknown to us, not failed.
def record_failed_charge(conn, pledge, capture_row_id, answer, paypal):
    check = paypal.get_authorization(pledge["auth_id"])
    hold_status = check["data"].get("status")
    if check["http_status"] == 200 and hold_status is not None:
        db.run(conn, "UPDATE holds SET status = %s WHERE id = %s", (hold_status, pledge["hold_id"]))
    capture_status = "FAILED"
    if hold_status == "CAPTURED":
        capture_status = "PENDING"
    error_code = paypal_issue(answer)
    db.run(conn, "UPDATE captures SET status = %s, error_code = %s WHERE id = %s",
           (capture_status, error_code, capture_row_id))
    db.run(conn, "UPDATE pledges SET status = 'FAILED' WHERE id = %s AND status = 'HELD'", (pledge["id"],))
    if hold_status == "CAPTURED":
        logger.error("pledge %d: the capture answer was %s, but PayPal says hold %d is CAPTURED, so money moved. "
                     "Marked FAILED (D47): find the capture by hand", pledge["id"], error_code, pledge["hold_id"])
    else:
        logger.warning("pledge %d: capture failed (%s, PayPal-Debug-Id %s); the hold is %s",
                       pledge["id"], error_code, answer["debug_id"], hold_status)


# PayPal's reason for a refused call, saved in captures.error_code: the issue name, like
# "TRANSACTION_REFUSED" (details[0].issue). NO_ANSWER when nothing came back, STATUS_<status> for a
# capture that isn't COMPLETED (like PENDING), or HTTP_<code> when PayPal gave no reason.
def paypal_issue(answer):
    if answer["http_status"] is None:
        return "NO_ANSWER"
    data = answer["data"]
    try:
        return data["details"][0]["issue"]
    except (KeyError, IndexError, TypeError):
        pass
    if data.get("status") is not None:
        return "STATUS_" + str(data["status"])
    return "HTTP_%d" % answer["http_status"]


# The hard deadline passed without the goal: OPEN -> EXPIRED (STATE_MACHINE.md). The compare-and-set
# comes first, so only one request expires the event, and no pledge can become HELD after it (mark_held
# reads the event's status under FOR SHARE). Then every hold is cancelled and the pledges are dropped
# (D45). Returns True if this call expired the event.
def expire_event(conn, event_id, now, paypal):
    changed = db.run(conn, "UPDATE events SET status = 'EXPIRED' "
                           "WHERE id = %s AND status = 'OPEN' AND hard_deadline <= %s", (event_id, now))
    if changed == 0:
        return False
    release_holds(conn, event_id, paypal)
    logger.info("event %d expired and its holds were released", event_id)
    return True


# Cancel every hold still CREATED on this event, then drop the pledges that have no hold left (D45).
# void_hold saves each void's request ID before the call and reads the hold back with a GET. A void that
# doesn't read back VOIDED is logged and left for M2's cleanup sweep (PAYPAL_INTEGRATION.md section 4):
# its hold stays CREATED, so its pledge stays HELD.
def release_holds(conn, event_id, paypal):
    holds = db.fetch_all(conn, "SELECT holds.id FROM holds JOIN pledges ON pledges.id = holds.pledge_id "
                               "WHERE pledges.event_id = %s AND holds.status = 'CREATED' ORDER BY holds.id",
                         (event_id,))
    for hold in holds:
        status = void_hold(conn, hold["id"], paypal)
        if status != "VOIDED":
            logger.warning("event %d: hold %d did not read back VOIDED (%s); left for the cleanup sweep",
                           event_id, hold["id"], status)
    drop_pledges_without_a_hold(conn, event_id)


# Every HELD or PENDING_PAY pledge of the event with no CREATED hold left becomes DROPPED, in one UPDATE
# (D45). That covers a hold voided just now, a hold voided or declined earlier (no PayPal call needed),
# and an unpaid pledge with no hold at all. A pledge whose void failed still has a CREATED hold, so it
# stays HELD. "NOT EXISTS (...)" is true when the inner SELECT finds no row.
def drop_pledges_without_a_hold(conn, event_id):
    return db.run(conn, "UPDATE pledges SET status = 'DROPPED' "
                        "WHERE event_id = %s AND status IN ('HELD', 'PENDING_PAY') "
                        "AND NOT EXISTS (SELECT 1 FROM holds "
                        "WHERE holds.pledge_id = pledges.id AND holds.status = 'CREATED')",
                  (event_id,))


# ---------- Step 5b: create and open an event ----------

# S1, "Create": save a new DRAFT event with its private admin_token, the treasurer's login link (D18).
# STATE_MACHINE.md says a DRAFT must have its admin_token saved before it's shown; the one INSERT saves
# both. The status starts as DRAFT, the column's default in schema.sql. deposit_cents is whole cents:
# the route turned the typed "300" into 30000 with money.py. It must be from $20 to $2,000 (config.py,
# D58, D61), the range test C3 checked. The log shows the event ID only, never the title or the token.
def create_event(conn, title, deposit_cents, demo_mode):
    title = title.strip()
    if title == "":
        return {"outcome": "NO_TITLE"}
    if deposit_cents < config.MIN_DEPOSIT_CENTS:
        return {"outcome": "TOO_SMALL"}
    if deposit_cents > config.MAX_DEPOSIT_CENTS:
        return {"outcome": "TOO_BIG"}
    row = db.fetch_one(conn, "INSERT INTO events (title, deposit_cents, admin_token, demo_mode) "
                             "VALUES (%s, %s, %s, %s) RETURNING id, admin_token",
                       (title, deposit_cents, new_token(), demo_mode))
    logger.info("event %d created as DRAFT", row["id"])
    return {"outcome": "CREATED", "event_id": row["id"], "admin_token": row["admin_token"]}


def find_event_by_admin_token(conn, admin_token):
    return db.fetch_one(conn, "SELECT * FROM events WHERE admin_token = %s", (admin_token,))


# How long pledging stays open once the event opens (D04): 48 hours, or 10 minutes in demo mode, so a
# whole event can be tried in one sitting.
def pledging_window(event):
    if event["demo_mode"]:
        return config.DEMO_PLEDGING_WINDOW
    return config.PLEDGING_WINDOW


# How long last call lasts once the goal is reached (D04): 1 hour, or 3 minutes in demo mode.
def last_call_window(event):
    if event["demo_mode"]:
        return config.DEMO_LAST_CALL_WINDOW
    return config.LAST_CALL_WINDOW


# S2, "Open pledging": DRAFT -> OPEN in one compare-and-set (STATE_MACHINE.md). The same UPDATE saves
# opens_at and hard_deadline, so an OPEN event always has its deadline. If two clicks arrive at once,
# only one UPDATE still finds the event DRAFT; the other changes 0 rows, and the first click's times stay.
# An event that isn't DRAFT was always opened before, because this is DRAFT's only way out.
# Returns OPENED, ALREADY_OPENED or NOT_FOUND.
def open_event(conn, admin_token, now):
    event = find_event_by_admin_token(conn, admin_token)
    if event is None:
        return "NOT_FOUND"
    hard_deadline = now + pledging_window(event)
    changed = db.run(conn, "UPDATE events SET status = 'OPEN', opens_at = %s, hard_deadline = %s "
                           "WHERE id = %s AND status = 'DRAFT'", (now, hard_deadline, event["id"]))
    if changed == 0:
        return "ALREADY_OPENED"
    logger.info("event %d is open", event["id"])
    return "OPENED"


# ---------- Step 5b C: the board ----------

# From LAST_CALL on, the goal has been reached, so the progress bar shows 100 (UI_DESIGN.md section 10)
# even after the holds have turned into charges and nothing is HELD any more.
GOAL_REACHED_STATUSES = ("LAST_CALL", "LOCKING", "CHARGING", "SETTLED", "NEEDS_ATTENTION")


# Every fact the board needs (S2, S3 and board.json), in cents, or None for an unknown event.
# It only reads: no PayPal call and no change to the database. app.board_for_event turns it into text.
# "Counted" is counted_held_pledges (D70): the same pledges the goal check uses and the lock would
# charge, so the goal, the progress bar and the estimated shares match what really happens.
def board_facts(conn, event_id):
    event = find_event(conn, event_id)
    if event is None:
        return None
    held = held_pledges(conn, event_id)
    counted = counted_among(conn, held)
    goal_cents = board_goal_cents(event, counted)
    return {
        "event": event,
        "rows": board_rows(conn, event_id),
        "counted_ids": pledge_ids(counted),
        "waiting_on": board_waiting_on(conn, event, held, counted),
        "held_total_cents": held_total_cents(conn, event_id),
        "goal_cents": goal_cents,
        "progress_percent": board_progress_percent(event, counted),
        "estimated_shares": estimated_shares(event, counted, goal_cents),
        "any_hold_created": has_created_hold(conn, event_id),
        "club_net_cents": money.club_net_cents(charge_net_cents(conn, event_id)),
    }


# The id of each pledge in a list, in the same order.
def pledge_ids(pledges):
    ids = []
    for pledge in pledges:
        ids.append(pledge["id"])
    return ids


# D79: for each HELD pledge that is not counted, the names it is waiting on, keyed by pledge id, for the
# "Waiting on Jay" text. Only while pledging can still change who counts (OPEN or LAST_CALL): after that
# a held pledge that isn't counted is only waiting for the cleanup sweep, so there is nothing to wait on.
def board_waiting_on(conn, event, held, counted):
    if event["status"] not in PLEDGING_STATUSES:
        return {}
    held_by_key = {}
    for pledge in held:
        held_by_key[conditions.name_key(pledge["name"])] = pledge
    counted_keys = []
    for pledge in counted:
        counted_keys.append(conditions.name_key(pledge["name"]))
    waiting = {}
    for pledge in held:
        if conditions.name_key(pledge["name"]) not in counted_keys:
            waiting[pledge["id"]] = names_not_held_behind(conn, pledge, held_by_key, counted_keys)
    return waiting


# The names that nobody has held for yet, behind one uncounted pledge. Ana waits on Bo, who waits on Cy,
# who hasn't held: Ana's list is ["Cy"], not ["Bo"], because Bo is already held and the real wait is
# for Cy. A name is "held" if it is in held_by_key (HELD with a CREATED hold); that covers a name nobody
# pledged and a name whose pledge is still unpaid. Counted names are skipped (they are satisfied).
# `seen` stops it going round a circle forever. The first spelling saved is shown, tidied.
# An uncounted pledge always leads to at least one name nobody holds for, because the circle rule only
# drops someone for a condition that starts at a missing name.
def names_not_held_behind(conn, pledge, held_by_key, counted_keys):
    seen = [conditions.name_key(pledge["name"])]
    to_visit = [pledge]
    missing = []
    while len(to_visit) > 0:
        current = to_visit.pop(0)
        for condition_name in pledge_conditions_of(conn, current["id"]):
            key = conditions.name_key(condition_name)
            if key in seen or key in counted_keys:
                continue
            seen.append(key)
            if key in held_by_key:
                to_visit.append(held_by_key[key])
            else:
                missing.append(conditions.tidy_name(condition_name))
    return missing


# The board's rows: every pledge except DROPPED ones (D56), in join order. pledger_token is never
# selected, so it can't reach the board by mistake.
def board_rows(conn, event_id):
    return db.fetch_all(conn, "SELECT id, name, status, max_cents, share_cents FROM pledges "
                              "WHERE event_id = %s AND status <> 'DROPPED' ORDER BY created_at, id",
                        (event_id,))


# The held total: one SQL SUM of the HELD pledges' maxes (D43). SUM over no rows gives NULL, so
# COALESCE turns that into 0.
def held_total_cents(conn, event_id):
    row = db.fetch_one(conn, "SELECT COALESCE(SUM(max_cents), 0) AS total FROM pledges "
                             "WHERE event_id = %s AND status = 'HELD'", (event_id,))
    return row["total"]


# The goal to show: the one the lock saved, once it has saved one. Before that, the fee-adjusted goal
# for the people counted right now, so it rises a little with each person (PayPal's fixed fee per charge).
def board_goal_cents(event, counted):
    if event["goal_cents"] is not None:
        return event["goal_cents"]
    return money.fee_adjusted_goal_cents(event["deposit_cents"], len(counted))


# 100 from LAST_CALL on; before that, Malama's progress_percent over the counted maxes (D54).
def board_progress_percent(event, counted):
    if event["status"] in GOAL_REACHED_STATUSES:
        return 100
    return money.progress_percent(event["deposit_cents"], max_list(counted))


# During LAST_CALL only: what each counted pledge would pay if last call ended now, keyed by pledge id.
# These are the same money.py calls save_shares makes at lock, so a late joiner visibly lowers everyone's
# number. Outside LAST_CALL there are no estimates.
def estimated_shares(event, counted, goal_cents):
    if event["status"] != "LAST_CALL":
        return {}
    shares = money.compute_shares_cents(goal_cents, max_list(counted))
    shares_by_pledge = {}
    for position in range(len(counted)):
        shares_by_pledge[counted[position]["id"]] = shares[position]
    return shares_by_pledge


# True while any hold of the event is still CREATED. The missed-goal banner must not say "Every hold was
# cancelled" until this is False (D45).
def has_created_hold(conn, event_id):
    row = db.fetch_one(conn, "SELECT COUNT(*) AS created FROM holds JOIN pledges ON pledges.id = holds.pledge_id "
                             "WHERE pledges.event_id = %s AND holds.status = 'CREATED'", (event_id,))
    return row["created"] > 0


# PayPal's net for each completed charge of the event (None where it wasn't saved), for
# money.club_net_cents. An event with no charges gives an empty list.
def charge_net_cents(conn, event_id):
    rows = db.fetch_all(conn, "SELECT captures.net_cents FROM captures "
                              "JOIN holds ON holds.id = captures.hold_id "
                              "JOIN pledges ON pledges.id = holds.pledge_id "
                              "WHERE pledges.event_id = %s AND captures.status = 'COMPLETED' ORDER BY captures.id",
                        (event_id,))
    nets = []
    for row in rows:
        nets.append(row["net_cents"])
    return nets
