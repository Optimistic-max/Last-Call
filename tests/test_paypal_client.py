# Unit tests for paypal_client.py. No network: requests is swapped for stand-ins, so nothing here
# talks to PayPal. These check our own code and are not TEST_PLAN IDs. The real sandbox check is
# tests/sandbox_smoke.py, run by hand.

import json
import logging

import pytest
import requests

import config
import paypal_client

FAKE_TOKEN = "FAKE-ACCESS-TOKEN-123"
FAKE_SECRET = "FAKE-CLIENT-SECRET-456"


# Point paypal_client at made-up settings for one test. monkeypatch undoes every change afterwards.
def use_fake_settings(monkeypatch):
    monkeypatch.setattr(config, "PAYPAL_BASE_URL", config.SANDBOX_BASE_URL)
    monkeypatch.setattr(config, "PAYPAL_CLIENT_ID", "FAKE-CLIENT-ID")
    monkeypatch.setattr(config, "PAYPAL_CLIENT_SECRET", FAKE_SECRET)
    monkeypatch.setitem(paypal_client.cached_token, "value", "")
    monkeypatch.setitem(paypal_client.cached_token, "expires_at", 0)


# Build a real requests Response by hand, as if PayPal had sent it. _content is where requests
# keeps the raw body; tests commonly set it directly like this.
def make_response(status_code, data=None):
    response = requests.Response()
    response.status_code = status_code
    response.encoding = "utf-8"
    response.headers["PayPal-Debug-Id"] = "FAKE-DEBUG-ID"
    if data is None:
        response._content = b""
    else:
        response._content = json.dumps(data).encode("utf-8")
    return response


# Swap the token step and requests.request for stand-ins, so API calls go nowhere.
# Every call is recorded in the returned list and gets back the same response.
# **options collects the named arguments (headers, json, timeout) into one dict.
def fake_api(monkeypatch, response):
    sent = []

    def fake_token():
        return FAKE_TOKEN

    def fake_request(method, url, **options):
        sent.append({"method": method, "url": url, "options": options})
        return response

    monkeypatch.setattr(paypal_client, "get_access_token", fake_token)
    monkeypatch.setattr(paypal_client.requests, "request", fake_request)
    return sent


# create_order sends intent AUTHORIZE, the amount as "40.00" text, the saved request ID and a 20 s timeout.
def test_create_order_body_and_headers(monkeypatch):
    use_fake_settings(monkeypatch)
    sent = fake_api(monkeypatch, make_response(201, {"id": "ORDER1", "status": "CREATED"}))

    result = paypal_client.create_order(4000, "pledge-7", "request-id-1")

    call = sent[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api-m.sandbox.paypal.com/v2/checkout/orders"
    assert call["options"]["json"]["intent"] == "AUTHORIZE"
    unit = call["options"]["json"]["purchase_units"][0]
    assert unit["amount"] == {"currency_code": "USD", "value": "40.00"}
    assert unit["reference_id"] == "pledge-7"
    assert unit["custom_id"] == "pledge-7"
    assert call["options"]["headers"]["PayPal-Request-Id"] == "request-id-1"
    assert call["options"]["timeout"] == 20
    assert result == {"http_status": 201,
                      "data": {"id": "ORDER1", "status": "CREATED"},
                      "debug_id": "FAKE-DEBUG-ID"}


# Every write sends the PayPal-Request-Id it was given (rule 4): create, authorize, capture and void.
def test_every_write_sends_its_request_id(monkeypatch):
    use_fake_settings(monkeypatch)
    sent = fake_api(monkeypatch, make_response(201, {}))

    paypal_client.create_order(500, "pledge-1", "id-create")
    paypal_client.authorize_order("ORDER1", "id-authorize")
    paypal_client.capture_authorization("AUTH1", 500, "id-capture")
    paypal_client.void_authorization("AUTH1", "id-void")

    request_ids = []
    for call in sent:
        request_ids.append(call["options"]["headers"]["PayPal-Request-Id"])
    assert request_ids == ["id-create", "id-authorize", "id-capture", "id-void"]


# A write with no request ID is refused before anything is sent.
def test_write_without_request_id_is_refused(monkeypatch):
    use_fake_settings(monkeypatch)
    sent = fake_api(monkeypatch, make_response(201, {}))

    with pytest.raises(ValueError):
        paypal_client.capture_authorization("AUTH1", 500, None)
    assert sent == []


# Capture charges the share with final_capture: true, so PayPal closes the rest of the hold.
def test_capture_sends_final_capture(monkeypatch):
    use_fake_settings(monkeypatch)
    sent = fake_api(monkeypatch, make_response(201, {"id": "CAPTURE1", "status": "COMPLETED"}))

    paypal_client.capture_authorization("AUTH1", 2500, "id-capture")

    call = sent[0]
    assert call["url"] == "https://api-m.sandbox.paypal.com/v2/payments/authorizations/AUTH1/capture"
    assert call["options"]["json"] == {"amount": {"currency_code": "USD", "value": "25.00"},
                                       "final_capture": True}


# A void answers 204 with an empty body. That must not crash, and the void itself sends no body.
def test_void_204_with_empty_body(monkeypatch):
    use_fake_settings(monkeypatch)
    sent = fake_api(monkeypatch, make_response(204))

    result = paypal_client.void_authorization("AUTH1", "id-void")

    assert result["http_status"] == 204
    assert result["data"] == {}
    assert sent[0]["options"]["json"] is None


# A timeout means "no answer": http_status None, never a success.
def test_timeout_gives_no_answer(monkeypatch):
    use_fake_settings(monkeypatch)
    fake_api(monkeypatch, make_response(201, {}))

    def timing_out_request(method, url, **options):
        raise requests.Timeout()

    monkeypatch.setattr(paypal_client.requests, "request", timing_out_request)

    result = paypal_client.capture_authorization("AUTH1", 2500, "id-capture")

    assert result["http_status"] is None
    assert result["data"] == {}


# The access token is reused, not fetched again on every call.
def test_access_token_is_cached(monkeypatch):
    use_fake_settings(monkeypatch)
    token_requests = []

    def fake_post(url, **options):
        token_requests.append(url)
        return make_response(200, {"access_token": FAKE_TOKEN, "expires_in": 32400})

    monkeypatch.setattr(paypal_client.requests, "post", fake_post)

    assert paypal_client.get_access_token() == FAKE_TOKEN
    assert paypal_client.get_access_token() == FAKE_TOKEN
    assert len(token_requests) == 1


# The log never shows the token, the client secret or an Authorization header (rule 11).
def test_logs_never_show_secrets(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    use_fake_settings(monkeypatch)

    def fake_post(url, **options):
        return make_response(200, {"access_token": FAKE_TOKEN, "expires_in": 32400})

    def fake_request(method, url, **options):
        return make_response(201, {"id": "ORDER1", "status": "CREATED"})

    monkeypatch.setattr(paypal_client.requests, "post", fake_post)
    monkeypatch.setattr(paypal_client.requests, "request", fake_request)

    paypal_client.get_client_token()
    paypal_client.create_order(4000, "pledge-7", "request-id-1")

    assert "POST /v2/checkout/orders" in caplog.text    # proves the log really ran
    assert FAKE_TOKEN not in caplog.text
    assert FAKE_SECRET not in caplog.text
    assert "Bearer" not in caplog.text
    assert "Authorization" not in caplog.text


# The sandbox guard runs on every call, so even a script that never starts app.py can't reach live PayPal.
def test_live_url_is_refused_before_sending(monkeypatch):
    use_fake_settings(monkeypatch)
    sent = fake_api(monkeypatch, make_response(200, {}))
    monkeypatch.setattr(config, "PAYPAL_BASE_URL", "https://api-m.paypal.com")

    with pytest.raises(RuntimeError):
        paypal_client.get_authorization("AUTH1")
    with pytest.raises(RuntimeError):
        paypal_client.request_token({"grant_type": "client_credentials"})
    assert sent == []


# An "ID" with anything but letters and digits is refused before it goes into a URL.
def test_bad_paypal_id_is_refused(monkeypatch):
    use_fake_settings(monkeypatch)
    sent = fake_api(monkeypatch, make_response(200, {}))

    with pytest.raises(ValueError):
        paypal_client.get_authorization("AUTH1/void")
    with pytest.raises(ValueError):
        paypal_client.get_capture("")
    assert sent == []


def test_cents_to_paypal_string():
    assert paypal_client.cents_to_paypal_string(4000) == "40.00"
    assert paypal_client.cents_to_paypal_string(1537) == "15.37"
    assert paypal_client.cents_to_paypal_string(5) == "0.05"
    assert paypal_client.cents_to_paypal_string(0) == "0.00"


# A float or a negative amount never reaches PayPal (rule 1).
def test_cents_to_paypal_string_refuses_floats_and_negatives():
    with pytest.raises(ValueError):
        paypal_client.cents_to_paypal_string(25.0)
    with pytest.raises(ValueError):
        paypal_client.cents_to_paypal_string(-100)


def test_paypal_string_to_cents():
    assert paypal_client.paypal_string_to_cents("2.01") == 201
    assert paypal_client.paypal_string_to_cents("15.37") == 1537
    assert paypal_client.paypal_string_to_cents("0.62") == 62
    assert paypal_client.paypal_string_to_cents("2.5") == 250
    assert paypal_client.paypal_string_to_cents("2") == 200


def test_paypal_string_to_cents_refuses_bad_text():
    for text in ["", "abc", "-2.01", "2.001", "1,234.56"]:
        with pytest.raises(ValueError):
            paypal_client.paypal_string_to_cents(text)


# first_authorization finds the hold inside an authorize answer, or returns {} when there is none.
def test_first_authorization():
    answer = {"status": "COMPLETED",
              "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH1", "status": "DENIED"}]}}]}
    assert paypal_client.first_authorization(answer) == {"id": "AUTH1", "status": "DENIED"}
    assert paypal_client.first_authorization({"name": "UNPROCESSABLE_ENTITY"}) == {}
