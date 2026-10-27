# Throwaway spike for test B1: can PayPal's card fields place a HOLD (intent AUTHORIZE) in a real browser?
# Not app code. Nothing here is imported by the app. Delete the folder when B1 is recorded.
#
# Run from the repo root:   .venv\Scripts\python spikes\b1_card_fields\server.py
# Then open:                 http://localhost:5000

import json
import os
import pathlib
import sys
import uuid

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory

SANDBOX_URL = "https://api-m.sandbox.paypal.com"
SPIKE_FOLDER = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SPIKE_FOLDER.parent.parent

# Keys come only from the repo's .env file. They are never printed.
load_dotenv(REPO_ROOT / ".env")
CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")

app = Flask(__name__)


def check_settings_or_exit():
    # Refuse to start without keys, or with any PayPal address other than the sandbox.
    if CLIENT_ID == "" or CLIENT_SECRET == "":
        sys.exit("PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET is empty in .env. Fill both in and save the file.")
    base_url = os.environ.get("PAYPAL_BASE_URL", "")
    if base_url != "" and base_url != SANDBOX_URL:
        sys.exit("PAYPAL_BASE_URL is not the sandbox URL. This spike only talks to the sandbox.")


def log(message):
    # Print to the console right away, so the log shows up while the server runs.
    print(message, flush=True)


def get_token(response_type):
    # Ask PayPal for a token. "client_credentials" is the server's own token; "client_token" is the
    # browser-safe token the v6 card fields need. Neither token is ever printed.
    body = {"grant_type": "client_credentials"}
    if response_type == "client_token":
        body["response_type"] = "client_token"
        body["intent"] = "sdk_init"
    response = requests.post(SANDBOX_URL + "/v1/oauth2/token", data=body,
                             auth=(CLIENT_ID, CLIENT_SECRET), timeout=20)
    log("POST /v1/oauth2/token (%s) -> HTTP %d" % (response_type, response.status_code))
    data = read_json(response)
    if response.status_code != 200:
        # PayPal's error and error_description never contain the keys, so they are safe to log.
        log("  token request failed: %s %s" % (data.get("error"), data.get("error_description")))
        return None
    return data["access_token"]


def read_json(response):
    # PayPal answers with JSON, except a void (204, empty body) or an outage page. Never crash on those.
    if response.text == "":
        return {}
    try:
        return response.json()
    except ValueError:
        return {"message": "response was not JSON"}


def call_paypal(method, path, body=None):
    # One PayPal API call with a fresh PayPal-Request-Id. Logs the request (no Authorization header)
    # and the HTTP status, so the console is the evidence for test B1.
    token = get_token("server")
    if token is None:
        return 502, {"message": "could not get a server token, see the console"}
    request_id = str(uuid.uuid4())
    headers = {"Authorization": "Bearer " + token,
               "Content-Type": "application/json",
               "PayPal-Request-Id": request_id}
    log("%s %s  PayPal-Request-Id: %s" % (method, path, request_id))
    if body is not None:
        log("  request body: %s" % json.dumps(body))
    response = requests.request(method, SANDBOX_URL + path, headers=headers,
                                json=body, timeout=20)
    log("  -> HTTP %d  PayPal-Debug-Id: %s" % (response.status_code,
                                              response.headers.get("PayPal-Debug-Id", "-")))
    return response.status_code, read_json(response)


@app.route("/")
def page():
    return send_from_directory(SPIKE_FOLDER, "index.html")


@app.route("/api/client-token")
def client_token():
    # The browser needs a browser-safe client token to start the v6 SDK.
    token = get_token("client_token")
    if token is None:
        return jsonify({"error": "could not get a client token, see the server console"}), 502
    return jsonify({"clientToken": token})


@app.route("/api/orders", methods=["POST"])
def create_order():
    # Route 1: create a $1.00 order with intent AUTHORIZE (a hold, not a charge).
    body = {"intent": "AUTHORIZE",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}]}
    status_code, data = call_paypal("POST", "/v2/checkout/orders", body)
    log("  order ID: %s  order status: %s" % (data.get("id"), data.get("status")))
    return jsonify({"id": data.get("id"), "status": data.get("status")}), status_code


@app.route("/api/orders/<order_id>/authorize", methods=["POST"])
def authorize_order(order_id):
    # Route 2: authorize the approved order. Check the authorization's status, not just the HTTP code:
    # a declined card still comes back as HTTP 201, with status DENIED.
    status_code, data = call_paypal("POST", "/v2/checkout/orders/%s/authorize" % order_id, {})
    authorization = {}
    try:
        authorization = data["purchase_units"][0]["payments"]["authorizations"][0]
    except (KeyError, IndexError):
        log("  no authorization in the response. PayPal says: %s" % data.get("details", data.get("message")))
    log("  order ID: %s  order status: %s" % (order_id, data.get("status")))
    log("  authorization ID: %s  authorization status: %s" % (authorization.get("id"),
                                                              authorization.get("status")))
    return jsonify({"order_id": order_id,
                    "order_status": data.get("status"),
                    "authorization_id": authorization.get("id"),
                    "authorization_status": authorization.get("status")}), status_code


@app.route("/api/authorizations/<authorization_id>/void", methods=["POST"])
def void_authorization(authorization_id):
    # Route 3: cancel the hold. PayPal answers 204 with no body, so read the hold back to confirm VOIDED.
    void_code, _ = call_paypal("POST", "/v2/payments/authorizations/%s/void" % authorization_id)
    get_code, data = call_paypal("GET", "/v2/payments/authorizations/%s" % authorization_id)
    log("  authorization ID: %s  authorization status: %s" % (authorization_id, data.get("status")))
    return jsonify({"void_http_status": void_code,
                    "get_http_status": get_code,
                    "authorization_status": data.get("status")})


if __name__ == "__main__":
    check_settings_or_exit()
    log("B1 spike: sandbox only, %s. Open http://localhost:5000" % SANDBOX_URL)
    app.run(port=5000, debug=False)
