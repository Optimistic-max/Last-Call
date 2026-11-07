# Treasurer browser security and read-only presentation. PayPal safety stays in lifecycle.py.
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import urlsplit

from flask import current_app, request, session
from itsdangerous import BadData, URLSafeSerializer
from werkzeug.security import check_password_hash

import config
import db
import lifecycle
import money


# Reserve only refund URLs; unrelated application routes retain settle-on-wake.
def is_refund_path(path):
    return re.fullmatch(r"/admin/(?:[^/]+/refund-access|events/[0-9]+/refunds(?:/.*)?)", path) is not None


# Store fingerprints rather than private admin tokens in signed, readable cookies.
def fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# Only an explicitly configured HTTPS origin (or opted-in loopback) can host refunds.
def configured_origin():
    try:
        parsed = urlsplit(config.APP_BASE_URL)
        parsed.port
    except ValueError:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        return None
    local = config.REFUND_ALLOW_LOCAL_HTTP and parsed.hostname in ("localhost", "127.0.0.1")
    if not parsed.netloc or (parsed.scheme != "https" and not (local and parsed.scheme == "http")):
        return None
    return parsed.scheme + "://" + parsed.netloc


# Missing configuration disables only refund controls, preserving the existing app.
def configured():
    return (len(config.FLASK_SECRET_KEY) >= 32 and current_app.secret_key == config.FLASK_SECRET_KEY
            and config.REFUND_APPROVAL_KEY_HASH.startswith(("scrypt:", "pbkdf2:"))
            and configured_origin() is not None)


# The token is secret to the browser session and is rotated after approval.
def csrf_token():
    if "refund_csrf" not in session:
        session["refund_csrf"] = secrets.token_urlsafe(32)
    return session["refund_csrf"]


# Exact origin checks supplement CSRF, including the authorization form itself.
def valid_post():
    origin = request.headers.get("Origin")
    if origin is None:
        try:
            referer = urlsplit(request.headers.get("Referer", ""))
        except ValueError:
            return False
        origin = referer.scheme + "://" + referer.netloc
    supplied = request.form.get("csrf_token", "")
    expected = session.get("refund_csrf", "")
    return (origin == configured_origin() and bool(expected) and len(supplied) <= 256
            and hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")))


# A high-entropy club key is independent of the event link; no enrollment via that link.
def approve(event, supplied_key, now):
    if not 32 <= len(supplied_key) <= 256:
        return False
    try:
        correct = check_password_hash(config.REFUND_APPROVAL_KEY_HASH, supplied_key)
    except ValueError:
        return False
    if not correct:
        return False
    session.clear()
    session["refund_grant"] = {"event_id": event["id"], "admin_hash": fingerprint(event["admin_token"]),
                               "key_hash": fingerprint(config.REFUND_APPROVAL_KEY_HASH),
                               "issued": int(now.timestamp()), "nonce": secrets.token_urlsafe(32)}
    csrf_token()
    return True


# Every request rechecks scope, expiry and credential rotation against the database event.
def authorized_event(conn, event_id, now):
    grant = session.get("refund_grant")
    if not isinstance(grant, dict) or grant.get("event_id") != event_id:
        return None
    issued = grant.get("issued")
    if not isinstance(issued, int) or not 0 <= int(now.timestamp()) - issued < config.REFUND_SESSION_SECONDS:
        return None
    event = lifecycle.find_event(conn, event_id)
    if event is None or grant.get("admin_hash") != fingerprint(event["admin_token"]):
        return None
    if grant.get("key_hash") != fingerprint(config.REFUND_APPROVAL_KEY_HASH):
        return None
    return event


# Read all records, including failed attempts; never silently omit unknown money.
def inventory(conn, event_id):
    return {
        "event": lifecycle.find_event(conn, event_id),
        "pledges": db.fetch_all(conn, "SELECT * FROM pledges WHERE event_id = %s ORDER BY id", (event_id,)),
        "holds": db.fetch_all(conn, "SELECT holds.* FROM holds JOIN pledges ON pledges.id = holds.pledge_id "
                                  "WHERE pledges.event_id = %s ORDER BY holds.id", (event_id,)),
        "captures": db.fetch_all(conn, "SELECT captures.* FROM captures JOIN holds ON holds.id = captures.hold_id "
                                     "JOIN pledges ON pledges.id = holds.pledge_id WHERE pledges.event_id = %s ORDER BY captures.id", (event_id,)),
        "refunds": db.fetch_all(conn, "SELECT refunds.* FROM refunds JOIN captures ON captures.id = refunds.capture_id "
                                    "JOIN holds ON holds.id = captures.hold_id JOIN pledges ON pledges.id = holds.pledge_id "
                                    "WHERE pledges.event_id = %s ORDER BY refunds.id", (event_id,)),
    }


# Bind confirmation to the exact reviewed records; changing them requires a fresh form.
def inventory_digest(records):
    return fingerprint(json.dumps(records, sort_keys=True, default=str))


# A signed random form is stateless until POST; GET does not insert or consume commands.
def make_action(records, kind, now, target=None):
    grant = session["refund_grant"]
    payload = {"nonce": secrets.token_urlsafe(32), "event_id": records["event"]["id"], "kind": kind,
               "session_hash": fingerprint(grant["nonce"]), "digest": inventory_digest(records),
               "expires": int(now.timestamp()) + config.REFUND_FORM_SECONDS, "target": target}
    if kind == "CHECK":
        payload["operation_revision"] = pending_refund(records, target)["operation_revision"]
    return URLSafeSerializer(current_app.secret_key, salt="refund-web-action").dumps(payload)


# Only this session's unexpired forms can be consumed; hidden input is never authority.
def read_action(token, event_id, kind, now, target):
    try:
        action = URLSafeSerializer(current_app.secret_key, salt="refund-web-action").loads(token)
    except BadData:
        return None
    grant = session.get("refund_grant", {})
    if (not isinstance(action, dict) or action.get("event_id") != event_id or action.get("kind") != kind
            or action.get("target") != target or action.get("session_hash") != fingerprint(grant.get("nonce", ""))
            or not isinstance(action.get("expires"), int) or action["expires"] < int(now.timestamp())):
        return None
    return action


# An active or uncertain web command never expires. Completed command history remains.
def active_command(conn, event_id):
    return db.fetch_one(conn, "SELECT action_hash FROM refund_web_actions WHERE event_id = %s AND state = 'CLAIMED'", (event_id,))


# Event-first locking serializes different forms and identical copied submissions.
def claim_action(conn, event_id, kind, token, now, target=None):
    action = read_action(token, event_id, kind, now, target)
    if action is None:
        return "STALE"
    action_hash = fingerprint(token)
    with conn.transaction():
        db.fetch_one(conn, "SELECT id FROM events WHERE id = %s FOR UPDATE", (event_id,))
        if authorized_event(conn, event_id, now) is None:
            return "STALE"
        previous = db.fetch_one(conn, "SELECT state FROM refund_web_actions WHERE action_hash = %s", (action_hash,))
        if previous is not None:
            return "REPLAY" if previous["state"] == "FINISHED" else "BUSY"
        if active_command(conn, event_id) is not None:
            return "BUSY"
        records = inventory(conn, event_id)
        if inventory_digest(records) != action["digest"] or not action_allowed(records, kind, target):
            return "STALE"
        db.run(conn, "INSERT INTO refund_web_actions (action_hash, event_id, session_hash, action_type, target_refund_id) "
                     "VALUES (%s, %s, %s, %s, %s)", (action_hash, event_id, action["session_hash"], kind, target))
    return "CLAIMED"


# Finish only a definitely returned command with no unresolved external sender.
def finish_action(conn, event_id, token):
    with conn.transaction():
        db.fetch_one(conn, "SELECT id FROM events WHERE id = %s FOR UPDATE", (event_id,))
        if lifecycle.refund_in_flight(conn, event_id) is not None:
            return False
        uncertain_void = db.fetch_one(conn, "SELECT holds.id FROM holds JOIN pledges ON pledges.id = holds.pledge_id "
                                           "WHERE pledges.event_id = %s AND holds.void_run_token IS NOT NULL LIMIT 1", (event_id,))
        if uncertain_void is not None:
            return False
        return db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = statement_timestamp() "
                            "WHERE action_hash = %s AND event_id = %s AND state = 'CLAIMED'", (fingerprint(token), event_id)) == 1


# Local warnings guide the screen; locked lifecycle preflight remains the final authority.
def blockers(records):
    messages = []
    for pledge in records["pledges"]:
        holds = [row for row in records["holds"] if row["pledge_id"] == pledge["id"]]
        payments = [row for row in records["captures"] if row["hold_id"] in [hold["id"] for hold in holds]]
        if not holds and (pledge["status"] in ("HELD", "FAILED", "CHARGED", "REFUNDED") or pledge["share_cents"] is not None):
            messages.append("Payment records are missing and require investigation.")
        if pledge["status"] in ("CHARGED", "REFUNDED") and not any(row["status"] in ("COMPLETED", "REFUNDED") for row in payments):
            messages.append("Recorded captured money is missing and requires investigation.")
        for hold in holds:
            if hold["void_run_token"] is not None:
                messages.append("An authorization cancellation is unresolved and requires investigation.")
            elif hold["status"] == "CAPTURED" and pledge["status"] == "FAILED":
                messages.append("PayPal reports captured money that needs reconciliation before refund-all can proceed.")
            elif hold["status"] == "CAPTURED" and len([row for row in payments if row["hold_id"] == hold["id"] and row["status"] in ("COMPLETED", "REFUNDED")]) != 1:
                messages.append("Recorded captured money is missing or inconsistent and requires investigation.")
            elif hold["refund_check_status"] == "MANUAL_REVIEW" or hold["status"] in ("PARTIALLY_CAPTURED", "PENDING"):
                messages.append("An authorization is unresolved and requires investigation.")
            elif hold["status"] != "NOT_PLACED" and (not isinstance(hold["auth_id"], str) or not hold["auth_id"].strip()):
                messages.append("An authorization record is missing and requires investigation.")
            elif hold["status"] == "NOT_PLACED" and (hold["auth_id"] is not None or hold["authorize_request_id"] is not None):
                messages.append("An authorization is unresolved and requires investigation.")
            elif records["event"]["status"] in ("REFUNDING", "REFUNDED") and hold["status"] != "NOT_PLACED" and hold["refund_check_status"] != "RESOLVED":
                messages.append("An authorization still needs reconciliation before completion.")
    if any(lifecycle.capture_is_unknown(row) for row in records["captures"]):
        messages.append("Captured money or a capture attempt is unresolved and requires investigation.")
    if records["event"]["status"] in ("REFUNDING", "REFUNDED"):
        for payment in records["captures"]:
            if payment["status"] not in ("COMPLETED", "REFUNDED"):
                continue
            matches = [row for row in records["refunds"] if row["capture_id"] == payment["id"]]
            if len(matches) != 1 or matches[0]["amount_cents"] != payment["amount_cents"]:
                messages.append("A required refund record is missing or inconsistent; investigation is required.")
            elif records["event"]["status"] == "REFUNDED" and payment_status(payment, matches[0]) != "Refunded - confirmed by PayPal":
                messages.append("A payment is not confirmed refunded; investigation is required.")
    if any(row["send_state"] in ("IN_FLIGHT", "UNCERTAIN", "CHECK_ONLY") for row in records["refunds"]):
        messages.append("A refund result is unresolved. Further sending is blocked for investigation.")
    if any(row["send_state"] == "READY" and not refund_is_unsent(row) for row in records["refunds"]):
        messages.append("A refund has unresolved sending history and requires investigation.")
    return list(dict.fromkeys(messages))


# Browser checks never include CHECK_ONLY, unknown IDs, active sends or completed outcomes.
def pending_refund(records, target):
    for row in records["refunds"]:
        if (row["id"] == target and row["send_state"] == "ANSWERED" and row["status"] == "PENDING"
                and isinstance(row["refund_id"], str) and row["refund_id"].strip()):
            return row
    return None


# The server repeats these predicates after locking; button visibility grants nothing.
def action_allowed(records, kind, target=None):
    status = records["event"]["status"]
    if kind == "CHECK":
        return status == "REFUNDING" and pending_refund(records, target) is not None
    if blockers(records):
        return False
    if kind == "START":
        return status == "NEEDS_ATTENTION" and not records["refunds"]
    return (kind == "CONTINUE" and status == "REFUNDING"
            and any(refund_is_unsent(row) for row in records["refunds"]))


# READY alone does not prove never-sent; historical evidence is preserved, never cleared.
def refund_is_unsent(row):
    return (row["send_state"] == "READY" and row["status"] == "PENDING" and row["refund_id"] is None
            and row["send_started_at"] is None and row["first_send_started_at"] is None
            and row["operation_revision"] == 0)


# An outcome is confirmed only when its refund and captured-payment records agree.
def payment_status(payment, refund):
    if refund is None:
        return "Not sent yet" if payment["status"] == "COMPLETED" else "Payment records require investigation"
    state = refund["send_state"]
    if state == "READY":
        return "Not sent yet" if refund_is_unsent(refund) else "Unresolved sending history; investigation required"
    if state == "IN_FLIGHT":
        return "Request started; result not yet confirmed"
    if state == "UNCERTAIN":
        return "Result unknown; blocked for investigation"
    if state == "CHECK_ONLY":
        return "Maintenance status check required; no further refund request allowed"
    if (state == "ANSWERED" and refund["status"] == "COMPLETED" and refund["refund_id"]
            and payment["status"] == "REFUNDED" and payment["amount_cents"] == refund["amount_cents"]):
        return "Refunded - confirmed by PayPal"
    if state == "ANSWERED" and refund["status"] == "PENDING" and refund["refund_id"]:
        return "Pending - PayPal is processing this refund"
    if state == "ANSWERED" and refund["status"] in ("FAILED", "CANCELLED"):
        return "Refund " + refund["status"].lower() + "; review required, no automatic retry"
    return "Payment records require investigation"


# Whitelist presentation fields; private PayPal IDs and request/owner tokens never leave here.
def people_view(records):
    people = []
    for pledge in records["pledges"]:
        hold_ids = [row["id"] for row in records["holds"] if row["pledge_id"] == pledge["id"]]
        payments = []
        for capture in records["captures"]:
            if capture["hold_id"] not in hold_ids or capture["status"] not in ("COMPLETED", "REFUNDED"):
                continue
            refund = next((row for row in records["refunds"] if row["capture_id"] == capture["id"]), None)
            payments.append({"amount_cents": capture["amount_cents"], "status": payment_status(capture, refund),
                             "check_target": refund["id"] if refund and pending_refund(records, refund["id"]) else None})
        complete = bool(payments) and all(row["status"] == "Refunded - confirmed by PayPal" for row in payments)
        owned_captures = [row for row in records["captures"] if row["hold_id"] in hold_ids]
        scoped = dict(records, pledges=[pledge], holds=[row for row in records["holds"] if row["id"] in hold_ids],
                      captures=owned_captures,
                      refunds=[row for row in records["refunds"] if row["capture_id"] in [capture["id"] for capture in owned_captures]])
        complete = complete and not blockers(scoped)
        people.append({"name": pledge["name"], "payments": payments,
                       "summary": "Fully refunded" if complete else "Review payment details" if payments else "No recorded captured payment"})
    return people


# Return only screen data and server-issued forms, never raw application records.
def view(conn, event_id, now, confirmation=False):
    records = inventory(conn, event_id)
    active = active_command(conn, event_id) is not None
    kind = "START" if confirmation else "CONTINUE"
    payments = [row for row in records["captures"] if row["status"] in ("COMPLETED", "REFUNDED") and not lifecycle.capture_is_unknown(row)]
    people = people_view(records)
    checks = {}
    if not active:
        for person in people:
            for payment in person["payments"]:
                target = payment["check_target"]
                if target is not None and action_allowed(records, "CHECK", target):
                    checks[target] = make_action(records, "CHECK", now, target)
    return {"event_id": event_id, "title": records["event"]["title"], "event_status": records["event"]["status"],
            "complete": records["event"]["status"] == "REFUNDED" and not blockers(records),
            "people": people, "totals": money.refund_summary_cents(payments), "blockers": blockers(records),
            "active_command": active, "checks": checks, "csrf_token": csrf_token(),
            "action_token": make_action(records, kind, now) if not active and action_allowed(records, kind) else None}
