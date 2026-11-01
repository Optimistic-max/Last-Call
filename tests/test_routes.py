# Tests for the pledge and order routes (step 2.3), the pledge page (step 2.4) and which requests
# settle (step 2.5) in app.py. Not docs/TEST_PLAN.md IDs.
# Flask's test client sends requests to the app without starting a server.
# The first tests need no database. The rest use the Neon test branch (Malama's test_db and test_db_url
# fixtures) with tests/fake_paypal.py in place of PayPal, and are skipped while TEST_DATABASE_URL is empty.

from datetime import timedelta

import pytest
from flask import render_template_string

import app
import config
import db
import lifecycle
import paypal_client
from tests import fake_paypal
from tests.test_lifecycle import NOW, delete_event, make_open_event, set_event_status

# The moments app.settle_on_wake was asked to settle, in the current test.
settle_requests = []


# Settle-on-wake runs before most requests (app.py). These tests aren't about settling, and some use no
# test database, so here it only records that it was asked: otherwise a request could settle events
# on the dev database with the real PayPal. autouse=True runs this for every test in this file.
# The E7 tests in test_lifecycle.py test real settling.
@pytest.fixture(autouse=True)
def record_instead_of_settling(monkeypatch):
    settle_requests.clear()

    def record(now):
        settle_requests.append(now)

    monkeypatch.setattr(app, "settle_on_wake", record)


# Point the app at the test branch, the fake PayPal and the fixed clock, for one test.
# monkeypatch undoes all three afterwards.
def use_test_setup(monkeypatch, test_db_url):
    def fixed_now():
        return NOW

    monkeypatch.setattr(config, "DATABASE_URL", test_db_url)
    monkeypatch.setattr(app, "paypal_client", fake_paypal)
    monkeypatch.setattr(app, "utc_now", fixed_now)


def test_dollars_formats_cents_for_the_screen():
    assert app.dollars(4000) == "$40.00"
    assert app.dollars(5) == "$0.05"
    assert app.dollars(123456) == "$1,234.56"
    assert app.dollars(100000000) == "$1,000,000.00"


# D41 and D46: requests for /static/ files and /health never settle; any other request does, once.
# db.connect is replaced so /health answers 503 at once instead of opening a real database.
def test_only_page_requests_settle(monkeypatch):
    def no_database(url):
        raise RuntimeError("no database in this test")

    monkeypatch.setattr(db, "connect", no_database)
    client = app.app.test_client()
    assert client.get("/static/js/pledge_paypal.js").status_code == 200
    assert client.get("/health").status_code == 503
    assert settle_requests == []
    assert client.get("/e/abc/pledge").status_code == 404
    assert len(settle_requests) == 1


# The client token goes to the page, and a failed token request is a 502 with the error text.
def test_client_token_route(monkeypatch):
    def fake_client_token():
        return "FAKE-CLIENT-TOKEN"

    monkeypatch.setattr(paypal_client, "get_client_token", fake_client_token)
    response = app.app.test_client().get("/api/client-token")
    assert response.status_code == 200
    assert response.get_json() == {"clientToken": "FAKE-CLIENT-TOKEN"}


def test_client_token_route_when_paypal_fails(monkeypatch):
    def no_client_token():
        return None

    monkeypatch.setattr(paypal_client, "get_client_token", no_client_token)
    response = app.app.test_client().get("/api/client-token")
    assert response.status_code == 502
    assert response.get_json() == {"message": app.ERROR_TEXT}


# Bad input is refused before the database is opened: no body, an event ID that isn't a number,
# a max that isn't an amount, and an order request with no token.
def test_routes_refuse_bad_input():
    client = app.app.test_client()
    assert client.post("/api/pledges").status_code == 400
    wrong_id = client.post("/api/pledges", json={"event_id": "7", "name": "Ana", "max": "40"})
    assert wrong_id.status_code == 400
    bad_max = client.post("/api/pledges", json={"event_id": 7, "name": "Ana", "max": "forty"})
    assert bad_max.status_code == 400
    assert bad_max.get_json() == {"message": "Type an amount like 40 or 40.50."}
    assert client.post("/api/orders", json={}).status_code == 400
    assert client.post("/api/orders/ORDER1/authorize", json={}).status_code == 400


# The whole M1 pledge, the way the page will do it: confirm, create the order, authorize. Then the same
# name is refused, with the D26 wording.
def test_pledge_order_and_authorize_through_the_routes(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        pledge = client.post("/api/pledges", json={"event_id": event_id, "name": "Ana", "max": "40"})
        assert pledge.status_code == 200
        token = pledge.get_json()["pledger_token"]
        assert pledge.get_json()["hold_text"] == ("If the goal is met, you're in. We'll hold up to $40.00 "
                                                  "now and charge only your share.")

        order = client.post("/api/orders", json={"pledger_token": token})
        assert order.status_code == 200
        order_id = order.get_json()["order_id"]

        held = client.post("/api/orders/" + order_id + "/authorize", json={"pledger_token": token})
        assert held.status_code == 200
        assert held.get_json() == {"status": "HELD", "message": "Held. You'll pay only your share, "
                                   "at most $40.00, and only if the goal is reached."}

        again = client.post("/api/pledges", json={"event_id": event_id, "name": "ana", "max": "25"})
        assert again.status_code == 409
        assert again.get_json() == {"message": "Ana has already pledged."}
    finally:
        delete_event(test_db, event_id)


# A declined card through the routes: the exact S5 decline text.
def test_declined_card_through_the_routes(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        fake_paypal.next_answers["authorize_order"] = [fake_paypal.authorized("DENIED", fake_paypal.new_id("AUTH"))]
        token = client.post("/api/pledges", json={"event_id": event_id, "name": "Ana", "max": "40"}).get_json()["pledger_token"]
        order_id = client.post("/api/orders", json={"pledger_token": token}).get_json()["order_id"]
        declined = client.post("/api/orders/" + order_id + "/authorize", json={"pledger_token": token})
        assert declined.status_code == 200
        assert declined.get_json() == {"status": "DECLINED",
                                       "message": "Card declined. Nothing was held. Try another card."}
    finally:
        delete_event(test_db, event_id)


# Step 2.4: the pledge page of an open event has the form, the promise and the PayPal script. The
# title is escaped, so HTML typed into a title shows as text and never runs.
def test_pledge_page_for_an_open_event(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    try:
        db.run(test_db, "UPDATE events SET title = %s WHERE id = %s", ("Cabin <b>trip</b>", event_id))
        page = app.app.test_client().get("/e/%d/pledge" % event_id)
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "SANDBOX DEMO: fake money, no real charges" in html
        assert "Nobody pays unless the goal is reached." in html
        assert 'data-event-id="%d"' % event_id in html
        assert '<script src="/static/js/pledge_paypal.js">' in html
        assert "Cabin &lt;b&gt;trip&lt;/b&gt;" in html
        assert "<b>trip" not in html
    finally:
        delete_event(test_db, event_id)


# A closed event shows the closed text and no card fields. An unknown event is a 404.
# 2147483647 is the biggest id a SERIAL column can hold, so no test event has it.
def test_pledge_page_for_a_closed_or_unknown_event(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        set_event_status(test_db, event_id, "EXPIRED")
        closed = client.get("/e/%d/pledge" % event_id)
        assert closed.status_code == 200
        assert "Pledging is closed for this event. Nothing was held." in closed.get_data(as_text=True)
        assert '<script src="/static/js/pledge_paypal.js">' not in closed.get_data(as_text=True)
        assert client.get("/e/2147483647/pledge").status_code == 404
    finally:
        delete_event(test_db, event_id)


# Refusals from lifecycle become the right messages: a max under $5 or over $2,000 (D58), a blank name,
# an unknown event, a closed event, and an order nobody saved.
def test_route_refusal_messages(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        small = client.post("/api/pledges", json={"event_id": event_id, "name": "Ana", "max": "4.99"})
        assert small.status_code == 400
        assert small.get_json() == {"message": "The smallest max is $5.00."}
        big = client.post("/api/pledges", json={"event_id": event_id, "name": "Ana", "max": "2000.01"})
        assert big.status_code == 400
        assert big.get_json() == {"message": "The largest max is $2,000.00."}
        blank = client.post("/api/pledges", json={"event_id": event_id, "name": "  ", "max": "40"})
        assert blank.get_json() == {"message": "Type your name."}
        unknown = client.post("/api/pledges", json={"event_id": -1, "name": "Ana", "max": "40"})
        assert unknown.status_code == 404
        no_order = client.post("/api/orders/NOSUCHORDER/authorize", json={"pledger_token": "x"})
        assert no_order.status_code == 404
        set_event_status(test_db, event_id, "EXPIRED")
        closed = client.post("/api/pledges", json={"event_id": event_id, "name": "Bo", "max": "40"})
        assert closed.status_code == 409
        assert closed.get_json() == {"message": "Pledging is closed for this event. Nothing was held."}
    finally:
        delete_event(test_db, event_id)


# ---------- Creating and opening an event (step 5b) ----------

BANNER_TEXT = "SANDBOX DEMO: fake money, no real charges"


# The token at the end of S2's address, read from a 303 answer that points there.
def admin_token_from(response):
    return response.headers["Location"].split("/admin/")[1]


# The dollars filter formats cents in a template exactly like dollars() (docs/UI_DESIGN.md section 7).
def test_dollars_filter_in_a_template():
    with app.app.app_context():
        assert render_template_string("{{ 4000|dollars }}") == "$40.00"
        assert render_template_string("{{ 123456|dollars }}") == "$1,234.56"


# S1 extends base.html, so it shows the sandbox banner, and it has the three fields app.py reads.
def test_create_page_shows_the_form():
    response = app.app.test_client().get("/")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert BANNER_TEXT in page
    for field in ['name="title"', 'name="deposit"', 'name="demo_mode"']:
        assert field in page


# A deposit that isn't an amount is refused with money.py's message before the database is touched,
# and S1 comes back with what was typed.
def test_create_refuses_a_deposit_that_isnt_an_amount():
    response = app.app.test_client().post("/events", data={"title": "Cabin", "deposit": "lots"})
    page = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Type an amount like 40 or 40.50." in page
    assert 'value="Cabin"' in page
    assert 'value="lots"' in page


# S1's other refusals: a blank title, a deposit under $20 (D61) and a deposit over $2,000 (D58).
# What was typed is kept, including the ticked demo mode box.
def test_create_refusal_messages(monkeypatch, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    client = app.app.test_client()
    blank = client.post("/events", data={"title": "  ", "deposit": "300"})
    assert blank.status_code == 400
    assert "Type a title." in blank.get_data(as_text=True)
    small = client.post("/events", data={"title": "Cabin", "deposit": "19.99", "demo_mode": "yes"})
    assert small.status_code == 400
    assert "The smallest deposit is $20.00." in small.get_data(as_text=True)
    assert 'value="19.99"' in small.get_data(as_text=True)
    assert " checked" in small.get_data(as_text=True)
    big = client.post("/events", data={"title": "Cabin", "deposit": "2000.01"})
    assert big.status_code == 400
    assert "The largest deposit is $2,000.00." in big.get_data(as_text=True)
    assert 'value="2000.01"' in big.get_data(as_text=True)


# "Create" answers 303 to S2 and saves a DRAFT in demo mode. S2 extends base.html and shows the
# pledge page as the share link (D55) and the "Open pledging" button. With APP_BASE_URL empty, the
# link uses the address the request came in on (the test client's is http://localhost/).
def test_create_event_through_the_routes(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    monkeypatch.setattr(config, "APP_BASE_URL", "")
    client = app.app.test_client()
    created = client.post("/events", data={"title": "Cabin (made up)", "deposit": "300", "demo_mode": "yes"})
    assert created.status_code == 303
    event = lifecycle.find_event_by_admin_token(test_db, admin_token_from(created))
    assert event is not None
    try:
        assert event["status"] == "DRAFT"
        assert event["deposit_cents"] == 30000
        assert event["demo_mode"] is True
        page = client.get(created.headers["Location"]).get_data(as_text=True)
        assert BANNER_TEXT in page
        assert "http://localhost/e/%d/pledge" % event["id"] in page
        assert "Open pledging" in page
    finally:
        delete_event(test_db, event["id"])


# With APP_BASE_URL set, as on Render, the share link starts with it (D55).
def test_share_link_uses_app_base_url(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    monkeypatch.setattr(config, "APP_BASE_URL", "https://example.test/")
    result = lifecycle.create_event(test_db, "Cabin (made up)", 30000, True)
    try:
        page = app.app.test_client().get("/admin/" + result["admin_token"]).get_data(as_text=True)
        assert "https://example.test/e/%d/pledge" % result["event_id"] in page
    finally:
        delete_event(test_db, result["event_id"])


# "Open pledging": a 303 back to S2, the event is OPEN for demo mode's 10 minutes, and the button is
# gone. A second click changes nothing. An unknown token is a 404 on both S2 routes.
def test_open_pledging_through_the_routes(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    client = app.app.test_client()
    result = lifecycle.create_event(test_db, "Cabin (made up)", 30000, True)
    admin_url = "/admin/" + result["admin_token"]
    try:
        opened = client.post(admin_url + "/open")
        assert opened.status_code == 303
        assert opened.headers["Location"].endswith(admin_url)
        event = lifecycle.find_event(test_db, result["event_id"])
        assert event["status"] == "OPEN"
        assert event["hard_deadline"] == NOW + timedelta(minutes=10)
        assert "Open pledging" not in client.get(admin_url).get_data(as_text=True)
        assert client.post(admin_url + "/open").status_code == 303
        assert lifecycle.find_event(test_db, result["event_id"])["opens_at"] == NOW
        assert client.get("/admin/no-such-token").status_code == 404
        assert client.post("/admin/no-such-token/open").status_code == 404
    finally:
        delete_event(test_db, result["event_id"])


# S2 shows the "Open pledging" form only while the event is DRAFT: there before opening, gone after,
# and gone for every later status too (Nov 1 bug check: an S2 with no button was an OPEN event).
def test_s2_shows_the_open_button_only_for_a_draft(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    client = app.app.test_client()
    result = lifecycle.create_event(test_db, "Cabin (made up)", 30000, True)
    admin_url = "/admin/" + result["admin_token"]
    open_form = '<form method="post" action="%s/open">' % admin_url
    try:
        page = client.get(admin_url).get_data(as_text=True)
        assert open_form in page
        assert "Open pledging" in page
        assert client.post(admin_url + "/open").status_code == 303
        page = client.get(admin_url).get_data(as_text=True)
        assert open_form not in page
        assert "Open pledging" not in page
        for status in ["LAST_CALL", "LOCKING", "CHARGING", "SETTLED", "NEEDS_ATTENTION", "EXPIRED"]:
            set_event_status(test_db, result["event_id"], status)
            assert "Open pledging" not in client.get(admin_url).get_data(as_text=True)
    finally:
        delete_event(test_db, result["event_id"])
