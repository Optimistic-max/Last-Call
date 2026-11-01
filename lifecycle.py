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


# True only if the event takes pledges right now: status OPEN or LAST_CALL, and the hard deadline
# hasn't passed. The clock is checked too, in case settling failed earlier in this request (approved
# item 11). In M1, last call also ends at the hard deadline (D25). M2 must check last_call_ends here.
def pledging_is_open(event, now):
    if event is None or event["status"] not in PLEDGING_STATUSES:
        return False
    if event["hard_deadline"] is None:
        return False
    return now < event["hard_deadline"]


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
def confirm_pledge(conn, event_id, name, max_cents, now):
    name = conditions.tidy_name(name)
    if name == "":
        return {"outcome": "NO_NAME"}
    if max_cents < config.MIN_MAX_CENTS:
        return {"outcome": "TOO_SMALL"}
    if max_cents > config.MAX_MAX_CENTS:
        return {"outcome": "TOO_BIG"}
    event = find_event(conn, event_id)
    if event is None:
        return {"outcome": "NOT_FOUND"}
    if not pledging_is_open(event, now):
        return {"outcome": "CLOSED"}
    existing = find_pledge_by_name(conn, event_id, name)
    if existing is None:
        try:
            return create_pledge(conn, event_id, name, max_cents)
        except psycopg.errors.UniqueViolation:
            # Someone saved the same name a moment ago, between our check and our INSERT.
            existing = find_pledge_by_name(conn, event_id, name)
    return reuse_pledge(conn, existing, max_cents)


# A brand-new pledge. Its status starts as PENDING_PAY (the column's default in schema.sql).
def create_pledge(conn, event_id, name, max_cents):
    row = db.fetch_one(conn, "INSERT INTO pledges (event_id, name, max_cents, pledger_token) "
                             "VALUES (%s, %s, %s, %s) RETURNING id, pledger_token",
                       (event_id, name, max_cents, new_token()))
    return {"outcome": "CONFIRMED", "pledge_id": row["id"], "pledger_token": row["pledger_token"]}


# D26 and D32: only an unpaid pledge (PENDING_PAY or DECLINED) can be reused. It gets the new max, goes
# back to PENDING_PAY, and gets a new token, so a page still holding the old token can no longer start
# or authorize a hold. This is a compare-and-set: if the pledge became HELD a moment ago, 0 rows change
# and the answer is "[Name] has already pledged."
def reuse_pledge(conn, pledge, max_cents):
    token = new_token()
    changed = db.run(conn, "UPDATE pledges SET max_cents = %s, status = 'PENDING_PAY', pledger_token = %s "
                           "WHERE id = %s AND status IN ('PENDING_PAY', 'DECLINED')",
                     (max_cents, token, pledge["id"]))
    if changed == 0:
        return {"outcome": "ALREADY_PLEDGED", "name": pledge["name"]}
    return {"outcome": "CONFIRMED", "pledge_id": pledge["id"], "pledger_token": token}


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
# order money.compute_shares_cents needs (MONEY_RULES.md section 6). In M1 every HELD pledge is
# counted (D37). Only one hold per pledge is taken, so nobody can be charged twice even if a second
# hold was left open by mistake. A HELD pledge with no CREATED hold (a hold voided by hand) can't be
# charged, so it isn't listed: drop_pledges_without_a_hold drops it.
def held_pledges(conn, event_id):
    pledges = db.fetch_all(conn, "SELECT id, max_cents FROM pledges WHERE event_id = %s AND status = 'HELD' "
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


# The max of each pledge, in the same order: the list Malama's money.py functions take.
def max_list(pledges):
    maxes = []
    for pledge in pledges:
        maxes.append(pledge["max_cents"])
    return maxes


# Did this event reach its goal? If so, open last call: OPEN -> LAST_CALL in one compare-and-set
# (docs/SYSTEM_DESIGN.md section 5B). In M1 last call runs until the hard deadline (D25), so `now` isn't
# used yet: M2 changes only the last_call_ends part, to min(now + 1 hour, hard_deadline).
# Runs after each new hold, and once more when a due event is settled. True if this call opened it.
def check_goal(conn, event_id, now):
    event = find_event(conn, event_id)
    if event is None or event["status"] != "OPEN":
        return False
    if not money.goal_is_reached(event["deposit_cents"], max_list(held_pledges(conn, event_id))):
        return False
    changed = db.run(conn, "UPDATE events SET status = 'LAST_CALL', last_call_ends = hard_deadline "
                           "WHERE id = %s AND status = 'OPEN'", (event_id,))
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
# Returns what happened: NOT_LOCKED, EXPIRED, SETTLED or NEEDS_ATTENTION.
def lock_and_charge(conn, event_id, now, paypal):
    won = db.run(conn, "UPDATE events SET status = 'LOCKING', lock_started_at = %s "
                       "WHERE id = %s AND status = 'LAST_CALL' AND last_call_ends <= %s",
                 (now, event_id, now))
    if won == 0:
        return "NOT_LOCKED"
    event = find_event(conn, event_id)
    pledges = held_pledges(conn, event_id)
    if not money.goal_is_reached(event["deposit_cents"], max_list(pledges)):
        return give_up_lock(conn, event_id, paypal)
    shares = save_shares(conn, event, pledges)
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
