# Tests for ai_parser.py: G1 and G2 from docs/TEST_PLAN.md, plus the helpers.
# No network: the model's answers are written by hand, and requests.post is swapped for a stand-in.
# Every message here is made up. G3 (the 50 frozen messages, with real AI calls) is not in this file.

import json
import logging

import requests

import ai_parser
import config

FAKE_KEY = "FAKE-AI-KEY-123"


# The JSON a model would send. Any field can be changed, e.g. answer(max_dollars=50).
def answer(**changes):
    fields = {"status": "in", "max_dollars": 40, "min_dollars": None, "conditions": [],
              "follow_up_question": None}
    for name, value in changes.items():
        fields[name] = value
    return json.dumps(fields)


# The "please retype" result, for comparing.
RETYPE = ai_parser.unclear_result(ai_parser.PLEASE_RETYPE_TEXT)


# G1: a good answer comes back in whole cents, with the condition tidied.
def test_g1_good_answer_in_cents():
    result = ai_parser.validate_pledge(answer(conditions=["  jay "]), "down if Jay goes, max 40")
    assert result == {"status": "in", "max_cents": 4000, "min_cents": None, "conditions": ["jay"],
                      "follow_up_question": None}


# G1: a range, and decimals. 40.5 arrives as the text "40.5" (parse_float=str), never as a float.
def test_g1_range_and_decimals_never_floats():
    result = ai_parser.validate_pledge('{"status": "in", "max_dollars": 40.5, "min_dollars": 20, '
                                       '"conditions": [], "follow_up_question": null}',
                                       "in for 20, up to 40.50 if we're short")
    assert result["max_cents"] == 4050
    assert result["min_cents"] == 2000
    assert isinstance(result["max_cents"], int)
    assert isinstance(result["min_cents"], int)


# G1: bad JSON, JSON that isn't an object, missing fields and wrong types all give "please retype".
def test_g1_bad_json_and_wrong_types():
    message = "im in, max 40"
    assert ai_parser.validate_pledge("not json", message) == RETYPE
    assert ai_parser.validate_pledge("[1, 2]", message) == RETYPE
    assert ai_parser.validate_pledge('{"status": "in"}', message) == RETYPE
    assert ai_parser.validate_pledge(answer(status="maybe"), message) == RETYPE
    assert ai_parser.validate_pledge(answer(max_dollars="lots"), message) == RETYPE
    assert ai_parser.validate_pledge(answer(max_dollars=True), message) == RETYPE
    assert ai_parser.validate_pledge(answer(max_dollars=-40), message) == RETYPE
    assert ai_parser.validate_pledge(answer(max_dollars=40.555), message) == RETYPE
    assert ai_parser.validate_pledge(answer(conditions="Jay"), message) == RETYPE
    assert ai_parser.validate_pledge(answer(conditions=[7]), message) == RETYPE
    assert ai_parser.validate_pledge(answer(follow_up_question="x" * 201), message) == RETYPE


# D73 (3): NaN, Infinity and -Infinity aren't real JSON, but Python's json module reads them.
# Wherever the model puts one, the answer is "please retype".
def test_d73_nan_and_infinity_refused():
    message = "im in, max 40"
    for bad in ("NaN", "Infinity", "-Infinity"):
        max_answer = answer().replace('"max_dollars": 40', '"max_dollars": ' + bad)
        min_answer = answer().replace('"min_dollars": null', '"min_dollars": ' + bad)
        assert ai_parser.validate_pledge(max_answer, message) == RETYPE, bad
        assert ai_parser.validate_pledge(min_answer, message) == RETYPE, bad


# D73 (3) and rule 1: NaN and Infinity are refused while the JSON is read, so they never become a
# float. The stand-in amount_to_cents records every value it gets; none may be a float.
def test_d73_nan_never_becomes_a_float(monkeypatch):
    seen = []

    def recording_amount_to_cents(value):
        seen.append(value)
        return None

    monkeypatch.setattr(ai_parser, "amount_to_cents", recording_amount_to_cents)
    ai_parser.read_answer(answer().replace('"max_dollars": 40', '"max_dollars": NaN'))
    for value in seen:
        assert not isinstance(value, float)


# G1: fields the model shouldn't send are dropped, not passed on.
def test_g1_unknown_fields_dropped():
    result = ai_parser.validate_pledge(answer(share_cents=999), "im in, max 40")
    assert "share_cents" not in result


# G1, the validator rule (D63): an amount the friend didn't type gives "please retype".
def test_g1_invented_max_or_min_refused():
    assert ai_parser.validate_pledge(answer(max_dollars=50), "im in, max 40") == RETYPE
    assert ai_parser.validate_pledge(answer(min_dollars=20), "im in, max 40") == RETYPE
    assert ai_parser.validate_pledge(answer(max_dollars=40), "im in, whatever you need") == RETYPE


# G1, the validator rule (D63): a condition the friend didn't type gives "please retype" for the whole
# suggestion, so a conditional pledge can never quietly become an unconditional one.
def test_g1_invented_condition_refused():
    assert ai_parser.validate_pledge(answer(conditions=["Maya"]), "down if Jay goes, max 40") == RETYPE
    assert ai_parser.validate_pledge(answer(conditions=["Jay"]), "Jayden's in, max 40") == RETYPE


# The amounts a message really contains: "$", commas and full stops are handled; words aren't numbers.
def test_numbers_in():
    assert ai_parser.numbers_in("max $40, or 1,000.50 tops.") == [4000, 100050]
    assert ai_parser.numbers_in("in for 20-40") == [2000, 4000]
    assert ai_parser.numbers_in("forty bucks") == []


# Names match as whole words, ignoring case and punctuation.
def test_name_appears_in():
    assert ai_parser.name_appears_in("Jay", "only if JAY's in")
    assert ai_parser.name_appears_in("Ana Lee", "if ana  lee goes")
    assert not ai_parser.name_appears_in("Jay", "Jayden is in")
    assert not ai_parser.name_appears_in("", "anything")


# "out" keeps no amounts and no conditions, whatever the model sent with it.
def test_out_keeps_nothing():
    result = ai_parser.validate_pledge(answer(status="out", max_dollars=None), "actually im out sorry")
    assert result == {"status": "out", "max_cents": None, "min_cents": None, "conditions": [],
                      "follow_up_question": None}


# "unclear" shows the model's question, or a default one if it sent none.
def test_unclear_uses_the_follow_up_question():
    asked = ai_parser.validate_pledge(answer(status="unclear", max_dollars=None,
                                             follow_up_question="Are you in?"), "maybe??")
    assert asked["status"] == "unclear"
    assert asked["follow_up_question"] == "Are you in?"
    default = ai_parser.validate_pledge(answer(status="unclear", max_dollars=None), "maybe??")
    assert default["follow_up_question"] == ai_parser.ASK_IN_TEXT


# The max limits (AI_PARSER.md section 4, D58, D63): no max, under $5 and over $2,000 each ask a
# question and keep no max. The texts match config.py's limits.
def test_max_limits_ask_a_question():
    no_max = ai_parser.validate_pledge(answer(max_dollars=None, conditions=["Jay"]), "in if Jay is")
    assert no_max["status"] == "unclear"
    assert no_max["follow_up_question"] == ai_parser.ASK_MAX_TEXT
    assert no_max["conditions"] == ["Jay"]
    too_small = ai_parser.validate_pledge(answer(max_dollars=3), "in for 3")
    assert too_small["follow_up_question"] == ai_parser.TOO_SMALL_TEXT
    assert too_small["max_cents"] is None
    too_big = ai_parser.validate_pledge(answer(max_dollars=2500), "in, up to 2500")
    assert too_big["follow_up_question"] == ai_parser.TOO_BIG_TEXT
    assert config.MIN_MAX_CENTS == 500 and config.MAX_MAX_CENTS == 200000
    assert ai_parser.validate_pledge(answer(max_dollars=2000), "in, up to 2000")["max_cents"] == 200000


# A min above the max makes no sense, so it gives "please retype".
def test_min_above_max_refused():
    assert ai_parser.validate_pledge(answer(min_dollars=50), "in for 50, max 40") == RETYPE


# Point the parser at made-up settings, and swap requests.post for a stand-in that records each call
# and either returns `response` or raises `error`.
def fake_ai(monkeypatch, response=None, error=None):
    sent = []

    def fake_post(url, **options):
        sent.append({"url": url, "options": options})
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(config, "AI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(config, "AI_MODEL", "openai/gpt-oss-20b")
    monkeypatch.setattr(ai_parser.requests, "post", fake_post)
    return sent


# A requests Response built by hand, as if Groq had sent it.
def groq_response(status_code, content):
    response = requests.Response()
    response.status_code = status_code
    response.encoding = "utf-8"
    response._content = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
    return response


# The whole path with a good answer, and what is sent: the model, strict JSON schema, temperature 0,
# the timeout, and the friend's message as the user's message.
def test_parse_pledge_happy_path_and_request(monkeypatch):
    sent = fake_ai(monkeypatch, response=groq_response(200, answer()))
    result = ai_parser.parse_pledge("im in, max 40")
    assert result["status"] == "in" and result["max_cents"] == 4000
    body = sent[0]["options"]["json"]
    assert sent[0]["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["temperature"] == 0
    assert body["messages"][1] == {"role": "user", "content": "im in, max 40"}
    assert sent[0]["options"]["timeout"] == config.AI_TIMEOUT_SECONDS


# G2: a timeout, an HTTP error and an answer with no content each give "please retype".
def test_g2_model_failure_shows_please_retype(monkeypatch):
    fake_ai(monkeypatch, error=requests.Timeout())
    assert ai_parser.parse_pledge("im in, max 40") == RETYPE
    fake_ai(monkeypatch, response=groq_response(500, None))
    assert ai_parser.parse_pledge("im in, max 40") == RETYPE
    fake_ai(monkeypatch, response=groq_response(200, None))
    assert ai_parser.parse_pledge("im in, max 40") == RETYPE


# G2: with no key set, nothing is sent at all.
def test_g2_no_key_sends_nothing(monkeypatch):
    sent = fake_ai(monkeypatch, response=groq_response(200, answer()))
    monkeypatch.setattr(config, "AI_API_KEY", "")
    assert ai_parser.parse_pledge("im in, max 40") == RETYPE
    assert sent == []


# Privacy: neither the key nor the friend's message ever reaches the log.
def test_log_has_no_key_and_no_message(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    fake_ai(monkeypatch, response=groq_response(200, answer()))
    ai_parser.parse_pledge("secret-ish message, max 40")
    fake_ai(monkeypatch, error=requests.ConnectionError("failed for " + FAKE_KEY))
    ai_parser.parse_pledge("secret-ish message, max 40")
    assert FAKE_KEY not in caplog.text
    assert "secret-ish" not in caplog.text
