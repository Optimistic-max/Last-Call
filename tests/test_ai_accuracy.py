# Tests for tests/ai_accuracy.py, the G3 scorer. No network and no AI: the parser's results are written
# by hand. Every message here is made up, and none of them is from the frozen 50 (that file is Malama's,
# written before any tuning; docs/AI_PARSER.md section 7).

import copy
import os

import pytest

import ai_parser
from tests import ai_accuracy


# A parser result, as ai_parser.parse_pledge returns it. Any field can be changed, e.g. result(max_cents=5000).
def result(**changes):
    fields = {"status": "in", "max_cents": 4000, "min_cents": None, "conditions": [],
              "follow_up_question": None}
    for name, value in changes.items():
        fields[name] = value
    return fields


# An expected answer, as the messages file holds it.
def expected(status="in", max_cents=4000, min_cents=None, conditions=None):
    return {"status": status, "max_cents": max_cents, "min_cents": min_cents, "conditions": conditions or []}


# A made-up file with the right shape: 50 messages, the right count in each category.
# The texts are placeholders, not test messages.
def good_file():
    messages = []
    for category, count in ai_accuracy.CATEGORY_COUNTS.items():
        for number in range(count):
            status = "in"
            max_cents = 3000
            if category == "pull_out":
                status = "out"
                max_cents = None
            if category in ("unclear", "chatter"):
                status = "unclear"
                max_cents = None
            messages.append({"id": len(messages) + 1, "category": category,
                             "text": "placeholder %s %d" % (category, number),
                             "expected": expected(status, max_cents)})
    return {"written_by": "test", "messages": messages}


# "in": right only when status, max, min and conditions all match.
def test_in_needs_every_field_to_match():
    assert ai_accuracy.is_right(expected(), result())
    assert not ai_accuracy.is_right(expected(), result(max_cents=5000))
    assert not ai_accuracy.is_right(expected(min_cents=2000), result())
    assert not ai_accuracy.is_right(expected(), result(conditions=["Jay"]))
    assert not ai_accuracy.is_right(expected(conditions=["Jay"]), result())
    assert not ai_accuracy.is_right(expected(), result(status="out", max_cents=None))


# Conditions match like conditions.name_key: order, extra spaces and capital letters don't matter,
# but a different spelling or a missing name does.
def test_conditions_ignore_order_and_case():
    want = expected(conditions=["Jay", "Maya"])
    assert ai_accuracy.is_right(want, result(conditions=["maya", " JAY "]))
    assert not ai_accuracy.is_right(want, result(conditions=["Jay"]))
    assert not ai_accuracy.is_right(want, result(conditions=["Jay", "Mya"]))


# "out": the status is enough.
def test_out_needs_only_the_status():
    out_result = result(status="out", max_cents=None)
    assert ai_accuracy.is_right(expected("out", None), out_result)
    assert not ai_accuracy.is_right(expected("out", None), result())


# "unclear": right when the parser also says unclear and asks a question (section 7).
def test_unclear_is_right_with_a_follow_up_question():
    want = expected("unclear", None)
    assert ai_accuracy.is_right(want, result(status="unclear", max_cents=None,
                                              follow_up_question=ai_parser.ASK_IN_TEXT))
    assert not ai_accuracy.is_right(want, result(status="unclear", max_cents=None, follow_up_question=None))
    assert not ai_accuracy.is_right(want, result())


# "Please retype" is a failed AI call or a bad answer, so it's never right, even for an unclear message.
def test_please_retype_is_never_right():
    retype = ai_parser.unclear_result(ai_parser.PLEASE_RETYPE_TEXT)
    assert not ai_accuracy.is_right(expected("unclear", None), retype)
    assert not ai_accuracy.is_right(expected(), retype)


# The made-up good file has no problems, and the category counts add up to 50.
def test_a_good_file_has_no_problems():
    total = 0
    for count in ai_accuracy.CATEGORY_COUNTS.values():
        total = total + count
    assert total == 50
    assert ai_accuracy.shape_problems(good_file()) == []


# Each kind of mistake in the file is reported, so the script refuses to run on a broken exam.
def test_file_mistakes_are_reported():
    data = good_file()
    data["messages"].pop()
    assert "there are 49 messages, not 50" in ai_accuracy.shape_problems(data)

    data = good_file()
    data["messages"][1]["id"] = 1
    assert "two messages share an id" in ai_accuracy.shape_problems(data)

    data = good_file()
    data["messages"][0]["category"] = "slang"
    assert ai_accuracy.shape_problems(data) != []

    assert ai_accuracy.shape_problems([]) != []
    assert ai_accuracy.shape_problems({"messages": "not a list"}) != []


# Mistakes inside one message: the text, the amounts (whole cents only, rule 1) and the status rules.
# Each (field, bad value) pair is put into a good "in" message, one at a time.
BAD_FIELDS = [
    ("text", ""),
    ("text", "x" * 281),
    ("max_cents", 30.0),
    ("max_cents", "3000"),
    ("max_cents", True),
    ("min_cents", 5000),
    ("max_cents", None),
    ("conditions", "Jay"),
    ("status", "maybe"),
]


def test_message_mistakes_are_reported():
    for field, value in BAD_FIELDS:
        message = copy.deepcopy(good_file()["messages"][0])
        if field == "text":
            message["text"] = value
        else:
            message["expected"][field] = value
        assert ai_accuracy.message_problems(message) != [], (field, value)


# An "out" or "unclear" answer has no amounts and no conditions, and "expected" has no extra keys.
def test_out_and_unclear_have_no_amounts_or_names():
    message = copy.deepcopy(good_file()["messages"][-1])
    message["expected"]["conditions"] = ["Jay"]
    assert ai_accuracy.message_problems(message) != []

    message = copy.deepcopy(good_file()["messages"][-1])
    message["expected"]["follow_up_question"] = "Are you in?"
    assert ai_accuracy.message_problems(message) != []


# The real frozen file, once Malama has written it: it must pass every check above.
def test_the_frozen_messages_file_has_the_right_shape():
    if not os.path.exists(ai_accuracy.MESSAGES_FILE):
        pytest.skip("tests/ai_test_messages.json isn't written yet (D74)")
    data = ai_accuracy.load_messages(ai_accuracy.MESSAGES_FILE)
    assert ai_accuracy.shape_problems(data) == []
