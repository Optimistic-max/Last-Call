# Tests for the pledge and order routes (step 2.3) and the pledge page (step 2.4) in app.py.
# Not docs/TEST_PLAN.md IDs.
# Flask's test client sends requests to the app without starting a server.
# The first tests need no database. The rest use the Neon test branch (Malama's test_db and test_db_url
# fixtures) with tests/fake_paypal.py in place of PayPal, and are skipped while TEST_DATABASE_URL is empty.

import app
import config
import db
import paypal_client
from tests import fake_paypal
from tests.test_lifecycle import NOW, delete_event, make_open_event, set_event_status


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


# Refusals from lifecycle become the right messages: a max under $5, a blank name, an unknown event,
# a closed event, and an order nobody saved.
def test_route_refusal_messages(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        small = client.post("/api/pledges", json={"event_id": event_id, "name": "Ana", "max": "4.99"})
        assert small.status_code == 400
        assert small.get_json() == {"message": "The smallest max is $5.00."}
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
