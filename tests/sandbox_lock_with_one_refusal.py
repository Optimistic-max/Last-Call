# Sandbox rehearsal helper (Option A, approved Nov 7). Run BY HAND only, never by pytest:
#     .venv\Scripts\python -m tests.sandbox_lock_with_one_refusal <event_id> "<friend name>"
# pytest never collects this file, because its name doesn't start with "test_" (same as sandbox_smoke.py).
#
# What it does: it runs the real lifecycle.lock_and_charge for ONE demo event on the database in .env
# (meant for the Neon dev branch), with the real PayPal sandbox client. The only difference: the capture
# for ONE named friend is answered here with a made-up 422 TRANSACTION_REFUSED, without calling PayPal.
# That friend's hold therefore stays CREATED in PayPal (it was never captured), their pledge ends FAILED,
# the other friends are charged for real, and the event ends NEEDS_ATTENTION.
# So that one refusal is SIMULATED; everything else (holds, read-backs, captures) is real sandbox.
# It changes no app code. Rule 6 still holds: capture is sent only by send_capture, after lock_and_charge
# wins its compare-and-set (LAST_CALL -> LOCKING).
#
# Before running: stop the Flask server and close every app tab BEFORE last call ends. Any request to the
# app after that (even the board's 10-second refresh) lets settle-on-wake lock the event first and charge
# everyone; this script then safely reports NOT_LOCKED and you need a new event.
# It prints IDs, names, statuses and the database endpoint name only, never a URL, key or token.

import logging
import sys
import types
from datetime import datetime, timezone
from urllib.parse import urlsplit

import config
import db
import lifecycle
import paypal_client

LOCAL_HOSTS = ("localhost", "127.0.0.1")


# PayPal's answer for a refused capture, in the shape paypal_client returns (docs/PAYPAL_INTEGRATION.md).
def refused_answer():
    return {"http_status": 422, "debug_id": None,
            "data": {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "TRANSACTION_REFUSED"}]}}


# The real sandbox client, except that capturing the one chosen authorization is refused here, with no
# call to PayPal. Every other function, including every other capture, is the real one.
def client_refusing(refused_auth_id):
    names = {}
    for name in dir(paypal_client):
        if not name.startswith("_"):
            names[name] = getattr(paypal_client, name)

    def capture_authorization(auth_id, amount_cents, request_id):
        if auth_id == refused_auth_id:
            print("   SIMULATED refusal for the chosen friend's capture (request id saved: %s); PayPal not called" % request_id)
            return refused_answer()
        return paypal_client.capture_authorization(auth_id, amount_cents, request_id)

    names["capture_authorization"] = capture_authorization
    return types.SimpleNamespace(**names)


# Stop with a message. Nothing has been written when any of these checks fail.
def refuse(reason):
    print("REFUSED: " + reason + ". Nothing was changed.")
    sys.exit(1)


# Only the part of the database host that names the Neon endpoint, like "ep-bold-field-...". Never the URL.
def endpoint_name(database_url):
    host = urlsplit(database_url).hostname or ""
    return host.split(".")[0] or "(unknown)"


# Every check that must pass before anything is written. Returns the event and the friend's pledge and hold.
def checked_target(conn, event_id, friend_name, now):
    event = lifecycle.find_event(conn, event_id)
    if event is None:
        refuse("event %d does not exist" % event_id)
    if not event["demo_mode"]:
        refuse("event %d is not a demo-mode event" % event_id)
    if event["status"] != "LAST_CALL":
        refuse("event %d is %s, not LAST_CALL" % (event_id, event["status"]))
    if event["last_call_ends"] is None or event["last_call_ends"] > now:
        refuse("last call of event %d has not ended yet; wait, and keep the app stopped" % event_id)
    pledge = db.fetch_one(conn, "SELECT id, name, status FROM pledges WHERE event_id = %s AND lower(name) = lower(%s)",
                          (event_id, friend_name))
    if pledge is None or pledge["status"] != "HELD":
        refuse("no HELD pledge named %r in event %d" % (friend_name, event_id))
    holds = db.fetch_all(conn, "SELECT id, auth_id FROM holds WHERE pledge_id = %s AND status = 'CREATED' "
                               "AND auth_id IS NOT NULL", (pledge["id"],))
    if len(holds) != 1:
        refuse("pledge %d needs exactly one CREATED hold with an authorization (found %d)" % (pledge["id"], len(holds)))
    return event, pledge, holds[0]


# After the lock: what happened, for the run log. IDs and statuses only.
def print_result(conn, event_id):
    print("\nPledges:")
    for row in db.fetch_all(conn, "SELECT id, name, status, share_cents FROM pledges WHERE event_id = %s ORDER BY id", (event_id,)):
        print("   pledge %d  %-20s %-10s share_cents=%s" % (row["id"], row["name"], row["status"], row["share_cents"]))
    print("Holds and capture attempts:")
    rows = db.fetch_all(conn, "SELECT h.id AS hold_id, h.status AS hold_status, h.auth_id, c.attempt, c.status AS capture_status, "
                              "c.capture_id, c.error_code FROM holds h JOIN pledges p ON p.id = h.pledge_id "
                              "LEFT JOIN captures c ON c.hold_id = h.id WHERE p.event_id = %s ORDER BY h.id, c.attempt", (event_id,))
    for row in rows:
        print("   hold %d %-8s auth %s  attempt %s %s capture %s %s" % (row["hold_id"], row["hold_status"], row["auth_id"],
              row["attempt"], row["capture_status"], row["capture_id"], row["error_code"] or ""))


def main():
    logging.basicConfig(level=logging.INFO, format="   log: %(message)s")
    config.check_sandbox_url(config.PAYPAL_BASE_URL)
    if urlsplit(config.APP_BASE_URL).hostname not in LOCAL_HOSTS:
        refuse("APP_BASE_URL is not a local address; this helper is for a laptop rehearsal only")
    if len(sys.argv) != 3 or not sys.argv[1].isdigit():
        refuse('usage: python -m tests.sandbox_lock_with_one_refusal <event_id> "<friend name>"')
    event_id = int(sys.argv[1])
    friend_name = sys.argv[2]
    now = datetime.now(timezone.utc)

    conn = db.connect(config.DATABASE_URL)
    try:
        event, pledge, hold = checked_target(conn, event_id, friend_name, now)
        print("Database endpoint : " + endpoint_name(config.DATABASE_URL) + "   (check in the Neon console that this is DEV)")
        print("Event             : %d  %r  (demo mode, LAST_CALL, last call ended)" % (event["id"], event["title"]))
        print("Refused capture   : pledge %d %r, hold %d, authorization %s" % (pledge["id"], pledge["name"], hold["id"], hold["auth_id"]))
        print("Every other HELD friend will be charged for real in the PayPal sandbox.")
        if input('Type "yes" to lock and charge: ').strip() != "yes":
            refuse("not confirmed")
        result = lifecycle.lock_and_charge(conn, event_id, datetime.now(timezone.utc), client_refusing(hold["auth_id"]))
        print("\nlock_and_charge returned: " + result + "   (expected NEEDS_ATTENTION)")
        print_result(conn, event_id)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
