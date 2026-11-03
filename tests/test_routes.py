# Tests for the pledge and order routes (step 2.3), the pledge page (step 2.4), which requests
# settle (step 2.5), creating and opening an event and the board (step 5b) and the AI parse route (M4,
# TEST_PLAN G4) in app.py. Test numbers in comments are from the plan for each step, not TEST_PLAN IDs.
# Flask's test client sends requests to the app without starting a server.
# The first tests need no database. The rest use the Neon test branch (Malama's test_db and test_db_url
# fixtures) with tests/fake_paypal.py in place of PayPal, and are skipped while TEST_DATABASE_URL is empty.

import json
import logging
import re
from datetime import timedelta
from pathlib import Path

import pytest
from flask import render_template_string
from markupsafe import escape

import ai_parser
import app
import config
import db
import lifecycle
import paypal_client
from tests import fake_paypal
from tests.test_ai_parser import groq_response
from tests.test_lifecycle import (NOW, add_held_pledge, confirm, delete_event, make_open_event,
                                  pledge_and_authorize, set_event_status)

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


# D41, D46 and D72: requests for /static/ files, /health and /favicon.ico never settle; any other
# request does, once. db.connect is replaced so /health answers 503 at once instead of opening a real
# database. There is no favicon, so /favicon.ico is a 404, but it still must not settle.
def test_only_page_requests_settle(monkeypatch):
    def no_database(url):
        raise RuntimeError("no database in this test")

    monkeypatch.setattr(db, "connect", no_database)
    client = app.app.test_client()
    assert client.get("/static/js/pledge_paypal.js").status_code == 200
    assert client.get("/health").status_code == 503
    assert client.get("/favicon.ico").status_code == 404
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


# ---------- Step 5b C: the board (S3, board.json, and S2's panel) ----------

# The exact keys of docs/UI_DESIGN.md section 10. A key may be added there later, never renamed.
BOARD_KEYS = {"event_id", "title", "status", "banner_text", "seconds_left", "goal_text", "held_total_text",
              "progress_percent", "pledging_open", "rows"}
ROW_KEYS = {"name", "status", "status_word", "max_text", "estimated_share_text", "counted", "waiting_on_text"}


# Hand-made board facts for the text tests below, so they need no database.
def facts_for(status, any_hold_created=False, club_net_cents=None):
    event = {"id": 7, "title": "Cabin (made up)", "status": status, "deposit_cents": 30000,
             "hard_deadline": NOW + timedelta(minutes=9, seconds=30),
             "last_call_ends": NOW + timedelta(minutes=4, seconds=59)}
    return {"event": event, "rows": [], "held_total_cents": 0, "goal_cents": 31001, "progress_percent": 0,
            "estimated_shares": {}, "any_hold_created": any_hold_created, "club_net_cents": club_net_cents,
            "counted_ids": [], "waiting_on": {}}


# Every key of a JSON object, at any depth, so a test can look for a forbidden name anywhere.
def all_keys(value):
    keys = []
    if isinstance(value, dict):
        for key in value:
            keys.append(key)
            keys.extend(all_keys(value[key]))
    if isinstance(value, list):
        for item in value:
            keys.extend(all_keys(item))
    return keys


# The banner for every status (UI_DESIGN.md section 10), including D45's "Cancelling holds…" and the
# SETTLED fallback when a net is missing.
def test_board_banner_for_every_status():
    def banner(facts):
        return app.banner_text(facts, app.seconds_left(facts["event"], NOW))

    assert banner(facts_for("DRAFT")) == "This event isn't open yet."
    assert banner(facts_for("OPEN")) == "Pledging open: 9 min left"
    assert banner(facts_for("LAST_CALL")) == ("Last call! Goal reached. Join in the next 4:59 "
                                              "and everyone's share drops.")
    assert banner(facts_for("LOCKING")) == "Locking shares…"
    assert banner(facts_for("CHARGING")) == "Locking shares…"
    assert banner(facts_for("SETTLED", club_net_cents=131400)) == "Done! Club receives $1,314.00"
    assert banner(facts_for("SETTLED", club_net_cents=None)) == "Charged once. PayPal closes the rest of each hold."
    assert banner(facts_for("NEEDS_ATTENTION")) == "Needs the treasurer's attention"
    assert banner(facts_for("EXPIRED", any_hold_created=True)) == "Cancelling holds…"
    assert banner(facts_for("EXPIRED", any_hold_created=False)) == ("Goal not reached. Every hold was "
                                                                    "cancelled. Nobody paid.")


# D57's placeholder time formats, and seconds_left: whole seconds while OPEN or LAST_CALL, never below
# 0, 0 when the time is missing, and None (null in JSON) for every other status.
def test_board_times():
    assert app.time_left_text(3900) == "1 h 5 min"
    assert app.time_left_text(599) == "9 min"
    assert app.time_left_text(59) == "less than a minute"
    assert app.countdown_text(299) == "4:59"
    assert app.countdown_text(3723) == "1:02:03"
    assert app.seconds_left(facts_for("OPEN")["event"], NOW) == 570
    assert app.seconds_left(facts_for("LAST_CALL")["event"], NOW) == 299
    assert app.seconds_left(facts_for("OPEN")["event"], NOW + timedelta(hours=1)) == 0
    assert app.seconds_left({"status": "LAST_CALL", "last_call_ends": None}, NOW) == 0
    for status in ["DRAFT", "LOCKING", "CHARGING", "SETTLED", "NEEDS_ATTENTION", "EXPIRED"]:
        assert app.seconds_left(facts_for(status)["event"], NOW) is None


# board.json has exactly the section 10 keys, and so does each row. Money and times are finished text.
def test_board_json_keys_match_the_contract(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 4000)
        confirm(test_db, event_id, "Bo", 2500)
        response = app.app.test_client().get("/e/%d/board.json" % event_id)
        assert response.status_code == 200
        board = response.get_json()
        assert set(board.keys()) == BOARD_KEYS
        assert len(board["rows"]) == 2
        for row in board["rows"]:
            assert set(row.keys()) == ROW_KEYS
        assert board["rows"][0] == {"name": "Ana", "status": "HELD", "status_word": "Held",
                                    "max_text": "$40.00", "estimated_share_text": "", "counted": True,
                                    "waiting_on_text": ""}
        assert board["rows"][1]["status_word"] == "Pledged"
        assert board["rows"][1]["counted"] is False
        assert board["held_total_text"] == "$40.00"
        assert board["seconds_left"] == 600
        assert board["banner_text"] == "Pledging open: 10 min left"
        assert board["pledging_open"] is True
    finally:
        delete_event(test_db, event_id)


# No token and no email ever reach the board: not the admin_token, not any pledger_token, and no key
# with "token" or "email" in its name, in board.json or on S3. S2 shows the board without pledger tokens.
def test_board_never_shows_a_token_or_email(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    client = app.app.test_client()
    result = lifecycle.create_event(test_db, "Cabin (made up)", 30000, True)
    event_id = result["event_id"]
    try:
        assert client.post("/admin/" + result["admin_token"] + "/open").status_code == 303
        tokens = [pledge_and_authorize(test_db, event_id, "Ana", 4000)[0], confirm(test_db, event_id, "Bo", 2500)]
        response = client.get("/e/%d/board.json" % event_id)
        board_page = client.get("/e/%d" % event_id).get_data(as_text=True)
        admin_page = client.get("/admin/" + result["admin_token"]).get_data(as_text=True)
        for text in [response.get_data(as_text=True), board_page]:
            assert result["admin_token"] not in text
            for token in tokens:
                assert token not in text
        for token in tokens:
            assert token not in admin_page
        for key in all_keys(response.get_json()):
            assert "token" not in key and "email" not in key
    finally:
        delete_event(test_db, event_id)


# S3 shows the rows and the Pledge link only while pledging is open. S2 shows the same board.
# An unknown event is a 404 on both board routes.
def test_board_page_and_s2_panel(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    client = app.app.test_client()
    result = lifecycle.create_event(test_db, "Cabin (made up)", 30000, True)
    event_id = result["event_id"]
    admin_url = "/admin/" + result["admin_token"]
    pledge_link = 'href="/e/%d/pledge"' % event_id
    try:
        # The page escapes the apostrophe in "isn't" (Jinja's autoescape), so compare with escaped text.
        assert str(escape("This event isn't open yet.")) in client.get(admin_url).get_data(as_text=True)
        assert client.post(admin_url + "/open").status_code == 303
        pledge_and_authorize(test_db, event_id, "Ana", 4000)
        page = client.get("/e/%d" % event_id)
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert "Ana: Held, max $40.00" in text
        assert "Pledging open: 10 min left" in text
        assert pledge_link in text
        assert "Ana: Held, max $40.00" in client.get(admin_url).get_data(as_text=True)
        set_event_status(test_db, event_id, "EXPIRED")
        assert pledge_link not in client.get("/e/%d" % event_id).get_data(as_text=True)
        assert client.get("/e/999999999").status_code == 404
        unknown = client.get("/e/999999999/board.json")
        assert unknown.status_code == 404
        assert unknown.get_json() == {"message": app.ERROR_TEXT}
    finally:
        delete_event(test_db, event_id)


# With the database down, board.json answers 503 with the error message and S3 a 503 page. Both routes
# still asked settle-on-wake to run first, once per request.
def test_board_when_the_database_is_down(monkeypatch):
    def no_database(url):
        raise RuntimeError("no database in this test")

    monkeypatch.setattr(db, "connect", no_database)
    client = app.app.test_client()
    response = client.get("/e/7/board.json")
    assert response.status_code == 503
    assert response.get_json() == {"message": app.ERROR_TEXT}
    assert client.get("/e/7").status_code == 503
    assert len(settle_requests) == 2


# ---------- The AI parse route (M4, D31, D73) ----------

# A made-up pledge, as a friend might type it (AGENTS.md rule 17: synthetic, not a real message).
PLEDGE_TEXT = "down if Jay goes, max 40"

# The model's JSON answer for PLEDGE_TEXT (docs/AI_PARSER.md section 3).
GOOD_ANSWER = json.dumps({"status": "in", "max_dollars": 40, "min_dollars": None, "conditions": ["Jay"],
                          "follow_up_question": None})


# Put a stand-in where ai_parser.call_model was, so no request ever goes to the AI. It returns `raw`
# (the model's JSON text, or None for a failed call) and records each message it was given, so a test
# can check the AI was never asked. Malama's real validator still checks the answer, G1 included.
def stand_in_ai(monkeypatch, raw):
    messages = []

    def fake_call_model(message_text):
        messages.append(message_text)
        return raw

    monkeypatch.setattr(ai_parser, "call_model", fake_call_model)
    return messages


def pledge_count(conn, event_id):
    row = db.fetch_one(conn, "SELECT count(*) AS pledges FROM pledges WHERE event_id = %s", (event_id,))
    return row["pledges"]


# Test 1: a good suggestion comes back with its amounts as plain text, and nothing is saved (D31, D62).
# The spaces around the text are trimmed before the AI sees it.
def test_parse_route_returns_the_suggestion(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    messages = stand_in_ai(monkeypatch, GOOD_ANSWER)
    event_id = make_open_event(test_db)
    try:
        response = app.app.test_client().post("/api/pledges/parse",
                                              json={"event_id": event_id, "text": "  " + PLEDGE_TEXT + " "})
        assert response.status_code == 200
        assert response.get_json() == {"status": "in", "max": "40.00", "min": None, "conditions": ["Jay"],
                                       "follow_up_question": None}
        assert messages == [PLEDGE_TEXT]
        assert pledge_count(test_db, event_id) == 0
    finally:
        delete_event(test_db, event_id)


# Test 2: the AI fails (no answer, a timeout or a bad answer all reach the route as None from call_model).
# The answer is still a 200 carrying the "please retype" question, with every field empty, so the page
# keeps the boxes editable.
def test_parse_route_when_the_ai_fails(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    stand_in_ai(monkeypatch, None)
    event_id = make_open_event(test_db)
    try:
        response = app.app.test_client().post("/api/pledges/parse",
                                              json={"event_id": event_id, "text": PLEDGE_TEXT})
        assert response.status_code == 200
        assert response.get_json() == {"status": "unclear", "max": None, "min": None, "conditions": [],
                                       "follow_up_question": ai_parser.PLEASE_RETYPE_TEXT}
    finally:
        delete_event(test_db, event_id)


# Test 3: D73's limit. 281 characters is refused before the AI is called; exactly 280 is read.
def test_parse_route_text_length_limit(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    messages = stand_in_ai(monkeypatch, GOOD_ANSWER)
    event_id = make_open_event(test_db)
    longest = PLEDGE_TEXT + " " + "x" * (280 - len(PLEDGE_TEXT) - 1)
    client = app.app.test_client()
    try:
        assert len(longest) == 280
        too_long = client.post("/api/pledges/parse", json={"event_id": event_id, "text": longest + "x"})
        assert too_long.status_code == 400
        assert too_long.get_json() == {"message": "Keep it to 280 characters or fewer."}
        assert messages == []
        just_right = client.post("/api/pledges/parse", json={"event_id": event_id, "text": longest})
        assert just_right.status_code == 200
        assert messages == [longest]
    finally:
        delete_event(test_db, event_id)


# Test 4: empty text, text made only of spaces, and a body of the wrong shape are refused before the
# database is opened (db.connect would raise, giving a 503) and before the AI is called.
def test_parse_route_refuses_empty_or_bad_input(monkeypatch):
    def no_database(url):
        raise RuntimeError("no database in this test")

    monkeypatch.setattr(db, "connect", no_database)
    messages = stand_in_ai(monkeypatch, GOOD_ANSWER)
    client = app.app.test_client()
    for text in ["", "   "]:
        empty = client.post("/api/pledges/parse", json={"event_id": 7, "text": text})
        assert empty.status_code == 400
        assert empty.get_json() == {"message": "Type your pledge."}
    assert client.post("/api/pledges/parse").status_code == 400
    assert client.post("/api/pledges/parse", json={"event_id": "7", "text": PLEDGE_TEXT}).status_code == 400
    assert client.post("/api/pledges/parse", json={"event_id": 7, "text": 40}).status_code == 400
    assert messages == []


# Test 5: a closed event is a 409 with the closed text, and an unknown event a 404. Neither asks the AI.
# 2147483647 is the biggest id a SERIAL column can hold, so no test event has it.
def test_parse_route_closed_or_unknown_event(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    messages = stand_in_ai(monkeypatch, GOOD_ANSWER)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        set_event_status(test_db, event_id, "EXPIRED")
        closed = client.post("/api/pledges/parse", json={"event_id": event_id, "text": PLEDGE_TEXT})
        assert closed.status_code == 409
        assert closed.get_json() == {"message": app.CLOSED_TEXT}
        unknown = client.post("/api/pledges/parse", json={"event_id": 2147483647, "text": PLEDGE_TEXT})
        assert unknown.status_code == 404
        assert unknown.get_json() == {"message": app.ERROR_TEXT}
        assert messages == []
    finally:
        delete_event(test_db, event_id)


# Test 6: privacy. This time the real call_model runs, with a made-up key, and only requests.post is
# replaced, so the key really passes through the code. The log, at every level, must hold neither the
# friend's text nor the key. The "HTTP 200" line shows the log was really captured, so the test can fail.
# The key is fake, so even if this test fails and pytest prints the log, no real secret is shown.
def test_parse_route_logs_no_message_and_no_key(monkeypatch, caplog, test_db, test_db_url):
    fake_key = "FAKE-AI-KEY-not-real-456"

    def fake_post(url, **options):
        return groq_response(200, GOOD_ANSWER)

    use_test_setup(monkeypatch, test_db_url)
    monkeypatch.setattr(config, "AI_API_KEY", fake_key)
    monkeypatch.setattr(config, "AI_MODEL", "made-up-model")
    monkeypatch.setattr(ai_parser.requests, "post", fake_post)
    caplog.set_level(logging.DEBUG)
    event_id = make_open_event(test_db)
    try:
        response = app.app.test_client().post("/api/pledges/parse",
                                              json={"event_id": event_id, "text": PLEDGE_TEXT})
        assert response.status_code == 200
        assert response.get_json()["status"] == "in"
        assert "AI call -> HTTP 200" in caplog.text
        assert PLEDGE_TEXT not in caplog.text
        assert "max 40" not in caplog.text
        assert fake_key not in caplog.text
    finally:
        delete_event(test_db, event_id)


# Test 7: the two limits Emmanuel approved in D73 (Nov 3).
def test_parse_limits_match_d73():
    assert config.MAX_PLEDGE_TEXT_CHARS == 280
    assert config.AI_TIMEOUT_SECONDS == 8


# ---------- Min and conditions on POST /api/pledges (D77) ----------

# The two limits in D77.
def test_condition_limits_match_d77():
    assert config.MAX_CONDITIONS == 3
    assert config.MAX_NAME_CHARS == 40


# The page may send "min" and "conditions" with the confirm. They are saved tidied, and the answer
# carries the token as before. A pledge with an empty "min" and no "conditions" key saves neither.
def test_confirm_route_saves_min_and_conditions(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        response = client.post("/api/pledges", json={"event_id": event_id, "name": "Ana", "max": "40",
                                                     "min": "20", "conditions": ["Jay", " jay ", "Maya"]})
        assert response.status_code == 200
        assert "pledger_token" in response.get_json()
        ana = lifecycle.find_pledge_by_name(test_db, event_id, "Ana")
        assert ana["min_cents"] == 2000
        assert lifecycle.pledge_conditions_of(test_db, ana["id"]) == ["Jay", "Maya"]

        plain = client.post("/api/pledges", json={"event_id": event_id, "name": "Bo", "max": "40",
                                                  "min": "", "conditions": None})
        assert plain.status_code == 200
        bo = lifecycle.find_pledge_by_name(test_db, event_id, "Bo")
        assert bo["min_cents"] is None
        assert lifecycle.pledge_conditions_of(test_db, bo["id"]) == []
    finally:
        delete_event(test_db, event_id)


# A "min" that isn't an amount, and "conditions" that isn't a list of texts, are refused before the
# database is opened (db.connect would raise, giving a 503 instead).
def test_confirm_route_refuses_a_bad_min_or_bad_conditions(monkeypatch):
    def no_database(url):
        raise RuntimeError("no database in this test")

    monkeypatch.setattr(db, "connect", no_database)
    client = app.app.test_client()
    good = {"event_id": 7, "name": "Ana", "max": "40"}
    bad_min = client.post("/api/pledges", json=dict(good, min="abc"))
    assert bad_min.status_code == 400
    assert bad_min.get_json() == {"message": "Type an amount like 40 or 40.50."}
    assert client.post("/api/pledges", json=dict(good, min=20)).status_code == 400
    for bad_conditions in ("Jay", {"name": "Jay"}, 3, [5], ["Jay", None], [["Jay"]]):
        response = client.post("/api/pledges", json=dict(good, conditions=bad_conditions))
        assert response.status_code == 400
        assert response.get_json() == {"message": app.ERROR_TEXT}


# The four new refusals (D77) come back as 400 with their texts, and nothing is saved.
def test_confirm_route_limit_messages(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    good = {"event_id": event_id, "name": "Ana", "max": "40"}
    try:
        many = client.post("/api/pledges", json=dict(good, conditions=["Bo", "Cy", "Dee", "Eve"]))
        assert many.status_code == 400
        assert many.get_json() == {"message": "You can name up to 3 people."}
        long_condition = client.post("/api/pledges", json=dict(good, conditions=["x" * 41]))
        assert long_condition.status_code == 400
        assert long_condition.get_json() == {"message": "Keep each name to 40 characters or fewer."}
        long_name = client.post("/api/pledges", json=dict(good, name="x" * 41))
        assert long_name.status_code == 400
        assert long_name.get_json() == {"message": "Keep your name to 40 characters or fewer."}
        min_above_max = client.post("/api/pledges", json=dict(good, min="40.01"))
        assert min_above_max.status_code == 400
        assert min_above_max.get_json() == {"message": "Your amount can't be more than your max."}
        row = db.fetch_one(test_db, "SELECT count(*) AS total FROM pledges WHERE event_id = %s", (event_id,))
        assert row["total"] == 0
    finally:
        delete_event(test_db, event_id)


# ---------- "Waiting on Jay" on the board (D79) ----------

# The wording for one, two and three names, and nothing for nobody. A placeholder until Samuel approves it.
def test_waiting_on_text_for_one_two_and_three_names():
    assert app.waiting_on_text([]) == ""
    assert app.waiting_on_text(["Jay"]) == "Waiting on Jay"
    assert app.waiting_on_text(["Jay", "Maya"]) == "Waiting on Jay and Maya"
    assert app.waiting_on_text(["Jay", "Maya", "Kim"]) == "Waiting on Jay, Maya and Kim"


# board.json and the S3 page: Ana is held "only if Jay's in" so her row says "Waiting on Jay" and is not
# counted; Bo is counted and waits on nobody. When Jay holds, Ana's wait is gone and she is counted.
def test_board_shows_who_a_pledge_is_waiting_on(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        add_held_pledge(test_db, event_id, "Ana", 4000, ["Jay"])
        add_held_pledge(test_db, event_id, "Bo", 4000)
        rows = client.get("/e/%d/board.json" % event_id).get_json()["rows"]
        assert (rows[0]["name"], rows[0]["counted"], rows[0]["waiting_on_text"]) == ("Ana", False, "Waiting on Jay")
        assert (rows[1]["name"], rows[1]["counted"], rows[1]["waiting_on_text"]) == ("Bo", True, "")
        assert "Waiting on Jay" in client.get("/e/%d" % event_id).get_data(as_text=True)

        add_held_pledge(test_db, event_id, "Jay", 4000)
        rows = client.get("/e/%d/board.json" % event_id).get_json()["rows"]
        assert [row["counted"] for row in rows] == [True, True, True]
        assert [row["waiting_on_text"] for row in rows] == ["", "", ""]
        assert "Waiting on" not in client.get("/e/%d" % event_id).get_data(as_text=True)
    finally:
        delete_event(test_db, event_id)


# A condition name is typed by a friend, so the page must escape it (Jinja does, by default).
def test_board_escapes_a_waiting_on_name(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    try:
        add_held_pledge(test_db, event_id, "Ana", 4000, ["<i>Jay</i>"])
        page = app.app.test_client().get("/e/%d" % event_id).get_data(as_text=True)
        assert "Waiting on &lt;i&gt;Jay&lt;/i&gt;" in page
        assert "<i>Jay</i>" not in page
    finally:
        delete_event(test_db, event_id)


# Ana needs Jay and Jay needs Ana, and both hold: the circle counts them together (D06), so neither row
# says "Waiting on", on board.json or on the S3 page. When only Ana has held, she is waiting on Jay.
def test_board_a_held_circle_has_no_waiting_text(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    client = app.app.test_client()
    try:
        add_held_pledge(test_db, event_id, "Ana", 4000, ["Jay"])
        alone = client.get("/e/%d/board.json" % event_id).get_json()["rows"]
        assert (alone[0]["counted"], alone[0]["waiting_on_text"]) == (False, "Waiting on Jay")

        add_held_pledge(test_db, event_id, "Jay", 4000, ["Ana"])
        rows = client.get("/e/%d/board.json" % event_id).get_json()["rows"]
        assert [row["name"] for row in rows] == ["Ana", "Jay"]
        assert [row["counted"] for row in rows] == [True, True]
        assert [row["waiting_on_text"] for row in rows] == ["", ""]
        assert "Waiting on" not in client.get("/e/%d" % event_id).get_data(as_text=True)
    finally:
        delete_event(test_db, event_id)


# ---------- The pledge page and the Check button (M4) ----------

# The ids the pledge page had before the Check button, and the five added for it (docs/UI_DESIGN.md
# section 10). Samuel styles the page by these ids, so none may disappear.
OLD_PLEDGE_IDS = ["pledge", "pledge-name", "pledge-max", "confirm-button", "hold-text", "hold-button",
                  "message", "paypal-card-fields-name", "paypal-card-fields-number",
                  "paypal-card-fields-expiry", "paypal-card-fields-cvv"]
NEW_PLEDGE_IDS = ["pledge-message", "check-button", "check-message", "pledge-min", "pledge-conditions"]


# The open pledge page, as the server renders it, has every old id and every new one. The own-words box
# is limited to the same 280 characters the parse route accepts (D73), and the page still has the
# sandbox banner and the promise.
def test_pledge_page_has_the_old_ids_and_the_check_button_ids(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    event_id = make_open_event(test_db)
    try:
        page = app.app.test_client().get("/e/%d/pledge" % event_id)
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        for element_id in OLD_PLEDGE_IDS + NEW_PLEDGE_IDS:
            assert 'id="%s"' % element_id in html
        assert 'maxlength="%d"' % config.MAX_PLEDGE_TEXT_CHARS in html
        assert "SANDBOX DEMO: fake money, no real charges" in html
    finally:
        delete_event(test_db, event_id)


# There is no JavaScript test tool in this repo (AGENTS.md: no build step), so this reads the script as
# text. Every id it looks up with a plain getElementById("...") must exist in pledge.html, so a typo
# can't silently break the page. The ids in its list of suggestion boxes must exist too. And outside
# comments it never uses innerHTML: text from the server goes on the page with textContent only.
def test_pledge_script_only_uses_ids_that_the_template_has():
    root = Path(__file__).resolve().parent.parent
    script = (root / "static" / "js" / "pledge_paypal.js").read_text(encoding="utf-8")
    template = (root / "templates" / "pledge.html").read_text(encoding="utf-8")
    code_lines = [line for line in script.split("\n") if not line.strip().startswith("//")]
    code = "\n".join(code_lines)
    used = re.findall(r'getElementById\("([^"]+)"\)', code)
    listed = re.findall(r'"([a-z-]+)"', re.search(r"suggestionBoxIds = \[(.*?)\]", code, re.S).group(1))
    assert "check-button" in used and "pledge-min" in used and len(listed) == 4
    for element_id in used + listed:
        assert 'id="%s"' % element_id in template, element_id
    assert "innerHTML" not in code
