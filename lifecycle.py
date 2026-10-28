# Every status change for events, pledges and holds (docs/STATE_MACHINE.md). Owner: Emmanuel.
# This is the only file that connects the database, the PayPal calls and the money math.
#
# Each function that talks to PayPal takes a `paypal` argument: app.py passes the real paypal_client
# module, and the tests pass tests/fake_paypal.py, which has the same function names.
# Each function that depends on time takes `now`, so tests can control the clock (AGENTS.md section 5).
# Each function takes `conn`, a connection from db.connect(). Every write is saved the moment it runs
# (db.py's autocommit), which is what "save before you send" relies on (rule 3).
#
# Step 2.3 has the pledge and hold steps. Settle, lock and charge, and expire come in step 2.5.
# The log shows IDs and statuses only: never a token, a name or an email (docs/SECURITY.md).

import logging
import secrets
import uuid
from datetime import datetime

import psycopg

import conditions
import config
import db

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
def confirm_pledge(conn, event_id, name, max_cents, now):
    name = conditions.tidy_name(name)
    if name == "":
        return {"outcome": "NO_NAME"}
    if max_cents < config.MIN_MAX_CENTS:
        return {"outcome": "TOO_SMALL"}
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
