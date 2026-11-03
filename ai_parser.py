# The AI pledge reader (docs/AI_PARSER.md, D31). Owner: Malama.
# One friend types their pledge in their own words; the AI suggests a status, max, min and conditions;
# plain code checks every part of that suggestion; the friend fixes and confirms it on the page.
# The AI never decides money (rule 8): it only suggests, and nothing here saves anything.
#
# Privacy: the friend's message and the API key are never logged. The log shows only the HTTP code
# or the error's type.

import json
import logging

import requests

import conditions
import config
import money

logger = logging.getLogger(__name__)

# Screen texts from docs/AI_PARSER.md section 4. The wording is Samuel's to approve (D57).
# The $5 and $2,000.00 must match config.MIN_MAX_CENTS and config.MAX_MAX_CENTS; a test checks it.
PLEASE_RETYPE_TEXT = "Couldn't read that. Please retype it, or fill in the amount, cap and condition yourself."
ASK_MAX_TEXT = "What's the most you'd pay?"
ASK_IN_TEXT = "Are you in? What's the most you'd pay?"
TOO_SMALL_TEXT = "The minimum is $5. What's your max?"
TOO_BIG_TEXT = "The largest max is $2,000.00. What's your max?"

# The longest follow-up question or condition name we accept from the model.
MAX_TEXT_LENGTH = 200

# The rules the model gets with every message (docs/AI_PARSER.md section 5).
SYSTEM_PROMPT = """You read one short message in which a friend says whether they will chip in for a group payment.
Answer with JSON only, in the given schema.
- status: "in", "out" or "unclear".
- max_dollars: the most they will pay, only if they typed a number. Never guess an amount: if no number is stated, max_dollars is null and status is "unclear".
- min_dollars: only for a range. "in for 20, up to 40 if we're short" means min_dollars 20 and max_dollars 40. Otherwise null.
- conditions: names of people who must also be in. "if X goes", "only if X's in" and "down if X" mean a condition on X. Otherwise [].
- "I'm out", "can't make it" and "nvm" mean status "out".
- If the message isn't about joining or paying, status is "unclear".
- follow_up_question: a short question when status is "unclear" or the max is missing, otherwise null."""

# The JSON shape the model must return (docs/AI_PARSER.md section 3). Groq's strict mode needs every
# field listed in "required", "additionalProperties": false, and null allowed by a ["...", "null"] type
# (read in docs: https://console.groq.com/docs/structured-outputs, Nov 1).
PLEDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["in", "out", "unclear"]},
        "max_dollars": {"type": ["number", "null"]},
        "min_dollars": {"type": ["number", "null"]},
        "conditions": {"type": "array", "items": {"type": "string"}},
        "follow_up_question": {"type": ["string", "null"]},
    },
    "required": ["status", "max_dollars", "min_dollars", "conditions", "follow_up_question"],
    "additionalProperties": False,
}


# Read one friend's message and return a checked suggestion (see validate_pledge for its shape).
# Any failure along the way (no key, no answer, a bad answer) gives the "please retype" result (G2).
def parse_pledge(message_text):
    raw = call_model(message_text)
    if raw is None:
        return unclear_result(PLEASE_RETYPE_TEXT)
    return validate_pledge(raw, message_text)


# One call to the AI. Returns the model's raw JSON text, or None if anything went wrong.
# temperature 0 and reasoning_effort "low" make the answer as repeatable as the model allows, and
# include_reasoning false leaves the model's thinking out of the answer (Groq docs, read Nov 1).
def call_model(message_text):
    if config.AI_API_KEY == "" or config.AI_MODEL == "":
        logger.warning("AI call skipped: AI_API_KEY or AI_MODEL is not set")
        return None
    body = {
        "model": config.AI_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": message_text}],
        "temperature": 0,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "pledge", "strict": True, "schema": PLEDGE_SCHEMA}},
    }
    headers = {"Authorization": "Bearer " + config.AI_API_KEY}
    try:
        response = requests.post(config.AI_BASE_URL + "/chat/completions", json=body, headers=headers,
                                 timeout=config.AI_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        logger.warning("AI call -> no answer (%s)", type(error).__name__)
        return None
    logger.info("AI call -> HTTP %d", response.status_code)
    if response.status_code != 200:
        return None
    return answer_text(response)


# The model's JSON text from Groq's answer: choices[0].message.content. None if it isn't there.
def answer_text(response):
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str):
        return None
    return content


# The result the page shows when the friend has to answer a question or fill things in by hand.
def unclear_result(question):
    return {"status": "unclear", "max_cents": None, "min_cents": None, "conditions": [],
            "follow_up_question": question}


# Check the model's answer with plain code (docs/AI_PARSER.md section 4, D63) and return
# {"status", "max_cents", "min_cents", "conditions", "follow_up_question"}, amounts in whole cents.
# Anything malformed, or any amount or name the friend didn't type (G1), gives "please retype".
def validate_pledge(raw, message_text):
    data = read_answer(raw)
    if data is None:
        return unclear_result(PLEASE_RETYPE_TEXT)
    if data["status"] == "out":
        return {"status": "out", "max_cents": None, "min_cents": None, "conditions": [],
                "follow_up_question": None}
    if data["status"] == "unclear":
        return unclear_result(data["follow_up_question"] or ASK_IN_TEXT)
    return checked_in_result(data, message_text)


# Turn the raw text into a dict with exactly the five fields, or None if it is malformed.
# parse_float=str keeps a number like 40.5 as the text "40.5", so no float is ever made (rule 1, D63).
# Fields the model shouldn't send are simply never read, which is how unknown fields are dropped.
def read_answer(raw):
    try:
        data = json.loads(raw, parse_float=str)
        if not isinstance(data, dict):
            return None
        answer = {
            "status": data["status"],
            "max_cents": amount_to_cents(data["max_dollars"]),
            "min_cents": amount_to_cents(data["min_dollars"]),
            "conditions": clean_names(data["conditions"]),
            "follow_up_question": short_text_or_none(data["follow_up_question"]),
        }
    except (ValueError, KeyError, TypeError):
        return None
    if answer["status"] not in ("in", "out", "unclear"):
        return None
    return answer


# An amount from the model -> whole cents, or None for null. Whole numbers arrive as int, and numbers
# with decimals as text (parse_float=str). True and False are refused, even though Python counts them
# as numbers. Anything money.py refuses (negative, 3 decimals, "1e3") raises ValueError.
def amount_to_cents(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("not an amount")
    if isinstance(value, int):
        return money.dollars_text_to_cents(str(value))
    if isinstance(value, str):
        return money.dollars_text_to_cents(value)
    raise TypeError("not an amount")


# The model's condition names, tidied (conditions.tidy_name), with blanks and repeats removed.
# Raises TypeError if it isn't a list of short texts.
def clean_names(names):
    if not isinstance(names, list):
        raise TypeError("conditions must be a list")
    cleaned = []
    seen = []
    for name in names:
        tidy = conditions.tidy_name(short_text_or_none(name) or "")
        if tidy != "" and conditions.name_key(tidy) not in seen:
            cleaned.append(tidy)
            seen.append(conditions.name_key(tidy))
    return cleaned


# A text of at most MAX_TEXT_LENGTH characters, or None for null. Anything else raises TypeError.
def short_text_or_none(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
        raise TypeError("not a short text")
    return value


# An "in" answer: the G1 check first, then the limits on the max (D58) and the min.
def checked_in_result(data, message_text):
    if not typed_by_friend(data, message_text):
        return unclear_result(PLEASE_RETYPE_TEXT)
    max_cents = data["max_cents"]
    min_cents = data["min_cents"]
    if max_cents is not None and min_cents is not None and min_cents > max_cents:
        return unclear_result(PLEASE_RETYPE_TEXT)
    question = None
    if max_cents is None:
        question = ASK_MAX_TEXT
    elif max_cents < config.MIN_MAX_CENTS:
        question = TOO_SMALL_TEXT
    elif max_cents > config.MAX_MAX_CENTS:
        question = TOO_BIG_TEXT
    if question is not None:
        return {"status": "unclear", "max_cents": None, "min_cents": min_cents,
                "conditions": data["conditions"], "follow_up_question": question}
    return {"status": "in", "max_cents": max_cents, "min_cents": min_cents,
            "conditions": data["conditions"], "follow_up_question": None}


# G1: every amount must be a number in the friend's message, and every condition a name in it.
def typed_by_friend(data, message_text):
    typed_amounts = numbers_in(message_text)
    for amount in (data["max_cents"], data["min_cents"]):
        if amount is not None and amount not in typed_amounts:
            return False
    for name in data["conditions"]:
        if not name_appears_in(name, message_text):
            return False
    return True


# Every amount typed in a message, in cents: "max $40, or 1,000.50" -> [4000, 100050].
# Commas are removed first, then anything that isn't a digit or a dot splits the pieces.
# A dot at the end of a piece is a full stop ("max 40." -> 40). Pieces money.py refuses are skipped.
def numbers_in(message_text):
    characters = []
    for character in message_text.replace(",", ""):
        if (character.isascii() and character.isdigit()) or character == ".":
            characters.append(character)
        else:
            characters.append(" ")
    found = []
    for piece in "".join(characters).split():
        try:
            found.append(money.dollars_text_to_cents(piece.rstrip(".")))
        except ValueError:
            continue
    return found


# True if the name appears in the message as whole words, ignoring case and punctuation:
# "Jay" is in "only if Jay's in" (read as "only if jay s in"), but "Jay" is not in "Jayden's in".
def name_appears_in(name, message_text):
    name_words = words_only(name)
    if name_words == "":
        return False
    return (" " + name_words + " ") in (" " + words_only(message_text) + " ")


# Lowercase letters and digits only, every other character turned into a single space.
def words_only(text):
    characters = []
    for character in text.lower():
        if character.isalnum():
            characters.append(character)
        else:
            characters.append(" ")
    return " ".join("".join(characters).split())
