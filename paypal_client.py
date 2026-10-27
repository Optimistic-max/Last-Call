# Every PayPal HTTP call, and nothing else (docs/PAYPAL_INTEGRATION.md). Owner: Emmanuel.
# This file knows nothing about events, pledges or the database. Each call returns a plain dict,
# and lifecycle.py decides what PayPal's answer means.
#
# The log shows only the method, the path, the PayPal-Request-Id, the HTTP code and the PayPal-Debug-Id.
# Never a token, the client secret, an Authorization header or a request body (docs/SECURITY.md).

import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

# The server's access token, kept between calls so we don't ask PayPal for a new one every time.
# "expires_at" is a time.monotonic() reading (see get_access_token).
cached_token = {"value": "", "expires_at": 0}


# 4000 -> "40.00". PayPal wants amounts as text with exactly two decimals (section 2a).
# Whole-number math only: // divides and drops the remainder, % gives the remainder.
# Anything that isn't whole cents is refused, so a float can never reach PayPal (rule 1).
def cents_to_paypal_string(cents):
    if not isinstance(cents, int) or cents < 0:
        raise ValueError("amounts must be whole, non-negative cents")
    dollars = cents // 100
    leftover_cents = cents % 100
    return "%d.%02d" % (dollars, leftover_cents)


# "2.01" -> 201, without ever making a float (rule 1). PayPal sends a capture's fee and net like this.
# "2.5" means $2.50 and "2" means $2.00. Anything else that isn't plain digits is refused.
def paypal_string_to_cents(text):
    if "." in text:
        dollars_text, cents_text = text.split(".")
    else:
        dollars_text = text
        cents_text = "00"
    if len(cents_text) == 1:
        cents_text = cents_text + "0"
    if not dollars_text.isdigit() or not cents_text.isdigit() or len(cents_text) != 2:
        raise ValueError("not a PayPal USD amount")
    return int(dollars_text) * 100 + int(cents_text)


# PayPal IDs are capital letters and digits, like "1FV797880C126320B". They go inside URLs, so
# anything else is refused: an "ID" containing "/" or "?" could point the call at a different address.
def check_paypal_id(paypal_id):
    if not isinstance(paypal_id, str) or not paypal_id.isascii() or not paypal_id.isalnum():
        raise ValueError("not a PayPal ID")


# PayPal answers in JSON, except a void (204, empty body) or an outage page. Never crash on those.
def read_json(response):
    if response.text == "":
        return {}
    try:
        return response.json()
    except ValueError:
        return {"message": "response was not JSON"}


# Ask PayPal's token address for a token, logging in with the client ID and secret (HTTP Basic auth).
# Returns PayPal's answer as a dict, or None if it failed. The answer holds a token, so it is never logged.
def request_token(body):
    config.check_sandbox_url(config.PAYPAL_BASE_URL)
    try:
        response = requests.post(config.PAYPAL_BASE_URL + "/v1/oauth2/token", data=body,
                                 auth=(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET),
                                 timeout=config.PAYPAL_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        # Only the error's type ("Timeout") is logged: its full text could include request details.
        logger.warning("POST /v1/oauth2/token -> no answer (%s)", type(error).__name__)
        return None
    logger.info("POST /v1/oauth2/token -> HTTP %d", response.status_code)
    data = read_json(response)
    if response.status_code != 200 or "access_token" not in data:
        # PayPal's error and error_description never contain the keys, so they are safe to log.
        logger.warning("  token request failed: %s %s", data.get("error"), data.get("error_description"))
        return None
    return data


# The server's own token, sent with every API call. Reused until a minute before it runs out.
# time.monotonic() is a clock that only moves forward, made for measuring "how long since".
# This is the one place paypal_client reads the clock, an exception to "time is passed in":
# token expiry is PayPal plumbing, not a money rule.
def get_access_token():
    if cached_token["value"] != "" and time.monotonic() < cached_token["expires_at"]:
        return cached_token["value"]
    data = request_token({"grant_type": "client_credentials"})
    if data is None:
        return None
    seconds_left = data.get("expires_in", 0) - config.TOKEN_REFRESH_MARGIN_SECONDS
    cached_token["value"] = data["access_token"]
    cached_token["expires_at"] = time.monotonic() + seconds_left
    return cached_token["value"]


# The browser-safe token the v6 card fields start with (D16, for GET /api/client-token).
# It goes to the browser, so it isn't secret like the client secret, but it is still never logged.
def get_client_token():
    data = request_token({"grant_type": "client_credentials",
                          "response_type": "client_token",
                          "intent": "sdk_init"})
    if data is None:
        return None
    return data["access_token"]


# The one place PayPal API calls happen. Returns {"http_status": ..., "data": ..., "debug_id": ...}.
# Every write (POST) must carry the PayPal-Request-Id that lifecycle.py saved in the database first
# (rules 3 and 4), so a write without one is refused before anything is sent.
# http_status None means we have no answer from PayPal (a timeout, a dropped connection, or no token):
# the result is unknown, and lifecycle.py must never treat it as success (section 5).
def send_request(method, path, request_id=None, body=None):
    config.check_sandbox_url(config.PAYPAL_BASE_URL)
    if method == "POST" and request_id is None:
        raise ValueError("every PayPal write needs a saved PayPal-Request-Id (rule 4)")
    no_answer = {"http_status": None, "data": {}, "debug_id": ""}
    token = get_access_token()
    if token is None:
        return no_answer
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if request_id is not None:
        headers["PayPal-Request-Id"] = request_id
    try:
        response = requests.request(method, config.PAYPAL_BASE_URL + path, headers=headers,
                                    json=body, timeout=config.PAYPAL_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        logger.warning("%s %s  PayPal-Request-Id: %s -> no answer (%s)",
                       method, path, request_id, type(error).__name__)
        return no_answer
    debug_id = response.headers.get("PayPal-Debug-Id", "")
    logger.info("%s %s  PayPal-Request-Id: %s -> HTTP %d  PayPal-Debug-Id: %s",
                method, path, request_id, response.status_code, debug_id)
    return {"http_status": response.status_code, "data": read_json(response), "debug_id": debug_id}


# Create a hold order: intent AUTHORIZE, so PayPal holds money and charges nothing (D16).
# Only this server call sets the intent; the browser never does. reference_id and custom_id tie
# the order back to our pledge, like "pledge-123" (section 2a).
def create_order(amount_cents, reference_id, request_id):
    body = {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "reference_id": reference_id,
                "custom_id": reference_id,
                "amount": {"currency_code": "USD", "value": cents_to_paypal_string(amount_cents)},
            }
        ],
    }
    return send_request("POST", "/v2/checkout/orders", request_id, body)


# Turn an order the card fields approved into a hold. A declined card still comes back as HTTP 201,
# so the real answer is the authorization's status (rule 5), which first_authorization() digs out.
def authorize_order(order_id, request_id):
    check_paypal_id(order_id)
    return send_request("POST", "/v2/checkout/orders/" + order_id + "/authorize", request_id, {})


# PayPal puts the hold deep inside an authorize answer: purchase_units[0].payments.authorizations[0].
# Returns that dict (it has "id", "status" and "expiration_time"), or {} if it isn't there.
def first_authorization(order_data):
    try:
        return order_data["purchase_units"][0]["payments"]["authorizations"][0]
    except (KeyError, IndexError, TypeError):
        return {}


# Read a hold's real status from PayPal: CREATED, CAPTURED, VOIDED or DENIED.
# A read changes nothing, so it needs no PayPal-Request-Id.
def get_authorization(auth_id):
    check_paypal_id(auth_id)
    return send_request("GET", "/v2/payments/authorizations/" + auth_id)


# Charge one share from a hold. final_capture: true tells PayPal this is the last charge, so it
# closes the rest of the hold and rejects a second capture (section 2b, VERIFIED A2).
# Only lifecycle.lock_and_charge() may call this (rule 6).
def capture_authorization(auth_id, amount_cents, request_id):
    check_paypal_id(auth_id)
    body = {
        "amount": {"currency_code": "USD", "value": cents_to_paypal_string(amount_cents)},
        "final_capture": True,
    }
    return send_request("POST", "/v2/payments/authorizations/" + auth_id + "/capture", request_id, body)


# Read one charge, including PayPal's real fee and net (seller_receivable_breakdown).
def get_capture(capture_id):
    check_paypal_id(capture_id)
    return send_request("GET", "/v2/payments/captures/" + capture_id)


# Cancel a hold. PayPal answers 204 with no body, so lifecycle.py reads the hold back with
# get_authorization() to confirm it is VOIDED (section 4).
def void_authorization(auth_id, request_id):
    check_paypal_id(auth_id)
    return send_request("POST", "/v2/payments/authorizations/" + auth_id + "/void", request_id)
