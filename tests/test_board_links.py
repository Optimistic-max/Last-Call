# D96: board.json "links" (who depends on whom) and the bare fallback list on S2 and S3.
# Fake PayPal and the disposable local database. Synthetic data only.
import re

import pytest

import app
import db
import lifecycle
from tests import fake_paypal
from tests.test_lifecycle import NOW, add_held_pledge, confirm_with, delete_event, make_open_event, set_event_status
from tests.test_routes import use_test_setup


@pytest.fixture(autouse=True)
def do_not_settle(monkeypatch):
    monkeypatch.setattr(app, "settle_on_wake", lambda now: None)


@pytest.fixture
def event(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    yield {"conn": test_db, "id": event_id}
    delete_event(test_db, event_id)


def board_json(event):
    return app.app.test_client().get("/e/%d/board.json" % event["id"]).get_json()


def link(from_name, to_name, met):
    return {"from": from_name, "to": to_name, "met": met}


def set_pledge_status(event, name, status):
    db.run(event["conn"], "UPDATE pledges SET status = %s WHERE event_id = %s AND name = %s", (status, event["id"], name))


# The names D79's "Waiting on ..." would list, worked out from the links alone: follow links through held people
# who are not counted yet, skip counted people, and stop at a name nobody holds for.
def chain_ends(board, start):
    rows = {row["name"].lower(): row for row in board["rows"]}
    seen, queue, ends = [start.lower()], [start.lower()], []
    while queue:
        current = queue.pop(0)
        for one in board["links"]:
            if one["from"].lower() != current:
                continue
            target = rows.get(one["to"].lower())
            key = one["to"].lower()
            if key in seen or (target is not None and target["counted"]):
                continue
            seen.append(key)
            if target is not None and target["status"] == "HELD":
                queue.append(key)
            else:
                ends.append(one["to"])
    return ends


# ---------- the data ----------

def test_a_circle_gives_two_links_both_met_when_counted(event):
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["Jay"])
    add_held_pledge(event["conn"], event["id"], "Jay", 4000, ["Ana"])
    assert board_json(event)["links"] == [link("Ana", "Jay", True), link("Jay", "Ana", True)]


def test_a_circle_with_an_unpaid_member_is_not_met(event):
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["Jay"])
    assert confirm_with(event["conn"], event["id"], "Jay", 4000, condition_names=["Ana"])["outcome"] == "CONFIRMED"
    assert board_json(event)["links"] == [link("Ana", "Jay", False), link("Jay", "Ana", False)]


def test_a_chain_ends_where_waiting_on_says(event):
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["Bo"])
    add_held_pledge(event["conn"], event["id"], "Bo", 4000, ["Cy"])
    add_held_pledge(event["conn"], event["id"], "Dee", 4000)
    board = board_json(event)
    assert board["links"] == [link("Ana", "Bo", False), link("Bo", "Cy", False)]
    uncounted = [row for row in board["rows"] if row["status"] == "HELD" and not row["counted"]]
    assert [row["name"] for row in uncounted] == ["Ana", "Bo"]
    for row in uncounted:
        assert chain_ends(board, row["name"]) == ["Cy"]
        assert row["waiting_on_text"] == app.waiting_on_text(chain_ends(board, row["name"]))


def test_a_name_nobody_pledged_is_a_link_that_is_not_met_and_is_tidied(event):
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["  Zed   Q "])
    assert board_json(event)["links"] == [link("Ana", "Zed Q", False)]


def test_a_dropped_pledge_is_hidden_and_its_name_is_a_plain_unmet_target(event):
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["Bo"])
    add_held_pledge(event["conn"], event["id"], "Bo", 4000, ["Ana"])
    set_pledge_status(event, "Bo", "DROPPED")
    board = board_json(event)
    assert board["links"] == [link("Ana", "Bo", False)]
    assert all(one["from"] != "Bo" for one in board["links"])
    assert [row["name"] for row in board["rows"]] == ["Ana"]


def test_the_target_is_spelled_the_way_the_board_shows_it(event):
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["JAY"])
    add_held_pledge(event["conn"], event["id"], "Jay", 4000)
    assert board_json(event)["links"] == [link("Ana", "Jay", True)]


def test_only_names_and_a_flag_appear_no_ids_or_tokens(event):
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["Jay"])
    add_held_pledge(event["conn"], event["id"], "Jay", 4000, ["Ana"])
    board = board_json(event)
    for one in board["links"]:
        assert set(one.keys()) == {"from", "to", "met"}
        assert isinstance(one["from"], str) and isinstance(one["to"], str) and type(one["met"]) is bool
    pledge_ids = [str(row["id"]) for row in db.fetch_all(event["conn"], "SELECT id FROM pledges WHERE event_id = %s", (event["id"],))]
    tokens = [row["pledger_token"] for row in db.fetch_all(event["conn"], "SELECT pledger_token FROM pledges WHERE event_id = %s", (event["id"],))]
    text = app.app.test_client().get("/e/%d/board.json" % event["id"]).get_data(as_text=True)
    assert all(token not in text for token in tokens)
    assert all(pledge_id not in [str(v) for one in board["links"] for v in one.values()] for pledge_id in pledge_ids)


def test_up_to_max_conditions_links_per_pledge_in_saved_order_and_unpaid_pledges_count(event):
    assert confirm_with(event["conn"], event["id"], "Ana", 4000, condition_names=["Jay", "Bo", "Cy"])["outcome"] == "CONFIRMED"
    links = board_json(event)["links"]
    assert links == [link("Ana", "Jay", False), link("Ana", "Bo", False), link("Ana", "Cy", False)]
    assert len(links) <= 3 * 1                                       # MAX_CONDITIONS x pledgers


def test_after_the_lock_met_follows_the_rows_counted_flag_and_an_expired_event_has_none_met(event):
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["Jay"])
    add_held_pledge(event["conn"], event["id"], "Jay", 4000, ["Ana"])
    set_pledge_status(event, "Ana", "CHARGED")
    set_pledge_status(event, "Jay", "CHARGED")
    db.run(event["conn"], "UPDATE pledges SET share_cents = 4000 WHERE event_id = %s", (event["id"],))   # a charged row shows its share
    set_event_status(event["conn"], event["id"], "SETTLED")
    assert board_json(event)["links"] == [link("Ana", "Jay", True), link("Jay", "Ana", True)]
    db.run(event["conn"], "UPDATE pledges SET status = 'HELD' WHERE event_id = %s", (event["id"],))
    db.run(event["conn"], "UPDATE holds SET status = 'VOIDED' WHERE pledge_id IN (SELECT id FROM pledges WHERE event_id = %s)", (event["id"],))
    set_event_status(event["conn"], event["id"], "EXPIRED")
    assert board_json(event)["links"] == [link("Ana", "Jay", False), link("Jay", "Ana", False)]


def test_the_links_come_from_one_extra_query_however_many_pledgers(event, monkeypatch):
    seen = []
    original = db.fetch_all
    def watching(conn, sql, params=()):
        if "pledge_conditions" in sql and "JOIN pledges" in sql:
            seen.append(sql)
        return original(conn, sql, params)
    monkeypatch.setattr(db, "fetch_all", watching)
    for number in range(2):
        add_held_pledge(event["conn"], event["id"], "P%d" % number, 4000, ["Q%d" % number])
    lifecycle.board_facts(event["conn"], event["id"])
    assert len(seen) == 1
    for number in range(2, 6):
        add_held_pledge(event["conn"], event["id"], "P%d" % number, 4000, ["Q%d" % number])
    seen.clear()
    lifecycle.board_facts(event["conn"], event["id"])
    assert len(seen) == 1


# ---------- the bare fallback list on S2 and S3 ----------

def pages(event):
    client = app.app.test_client()
    token = lifecycle.find_event(event["conn"], event["id"])["admin_token"]
    return [client.get("/e/%d" % event["id"]).get_data(as_text=True), client.get("/admin/" + token).get_data(as_text=True)]


def test_the_fallback_list_has_one_line_per_link_and_only_when_there_are_links(event):
    for text in pages(event):
        assert 'class="board-links"' not in text
    add_held_pledge(event["conn"], event["id"], "Ana", 4000, ["Jay"])
    add_held_pledge(event["conn"], event["id"], "Jay", 4000, ["Ana"])
    add_held_pledge(event["conn"], event["id"], "Bo", 4000, ["Cy"])
    for text in pages(event):
        lines = [re.sub(r"\s+", " ", line).strip() for line in re.findall(r'<li class="board-link"[^>]*>(.*?)</li>', text, re.S)]
        assert lines == ["Ana → Jay ✓", "Jay → Ana ✓", "Bo → Cy (waiting)"]


def test_names_in_the_fallback_list_are_escaped(event):
    hostile = "<script>alert(1)</script>"
    add_held_pledge(event["conn"], event["id"], hostile, 4000, ["<i>Jay</i>"])
    for text in pages(event):
        assert "<script>alert(1)</script>" not in text and "<i>Jay</i>" not in text
        list_lines = re.findall(r'<li class="board-link"[^>]*>(.*?)</li>', text, re.S)
        assert len(list_lines) == 1
        line = re.sub(r"\s+", " ", list_lines[0]).strip()
        assert line == "&lt;script&gt;alert(1)&lt;/script&gt; → &lt;i&gt;Jay&lt;/i&gt; (waiting)"
