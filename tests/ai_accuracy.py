# G3: the AI reader's accuracy on the 50 frozen made-up messages (docs/AI_PARSER.md section 7).
# Real AI calls, run by hand only:
#     .venv\Scripts\python -m tests.ai_accuracy
# pytest never runs it, because its name doesn't start with "test_". tests/test_ai_accuracy.py checks
# the scoring rules and the messages file without any network.
# It sends only the made-up messages in tests/ai_test_messages.json. It prints the model's name, never
# the key. Owner: Malama.

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import ai_parser
import conditions
import config

MESSAGES_FILE = Path(__file__).resolve().parent / "ai_test_messages.json"

# How many messages each category has (docs/AI_PARSER.md section 7). They add up to 50.
CATEGORY_COUNTS = {
    "plain": 10,
    "slang": 8,
    "conditions": 8,
    "range": 6,
    "pull_out": 6,
    "unclear": 6,
    "chatter": 6,
}

# The fields every message's "expected" answer has, and nothing else.
EXPECTED_KEYS = ["conditions", "max_cents", "min_cents", "status"]

# Seconds to wait between AI calls, so 50 calls in a row stay under the provider's per-minute limit.
# Groq's free-tier limit for our model is unverified, TODO (source needed); 3 s means 20 calls a minute.
PAUSE_SECONDS = 3


# Read the messages file. Returns the whole object: {"written_by": ..., "messages": [...]}.
def load_messages(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


# The file's SHA-256 fingerprint. Recorded in D74 when the file is frozen: if one character changes
# later, the fingerprint changes, so anyone can check the exam wasn't edited after the first run.
def file_fingerprint(path):
    with open(path, "rb") as file:
        return hashlib.sha256(file.read()).hexdigest()


# Everything wrong with the file as a whole, as a list of sentences. An empty list means it's fine.
def shape_problems(data):
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        return ['the file must be an object with a "messages" list']
    messages = data["messages"]
    problems = []
    if len(messages) != 50:
        problems.append("there are %d messages, not 50" % len(messages))
    ids = []
    found_counts = {}
    for message in messages:
        problems.extend(message_problems(message))
        if isinstance(message, dict):
            ids.append(message.get("id"))
            category = message.get("category")
            found_counts[category] = found_counts.get(category, 0) + 1
    if len(set(ids)) != len(ids):
        problems.append("two messages share an id")
    for category, count in CATEGORY_COUNTS.items():
        if found_counts.get(category, 0) != count:
            problems.append("%s has %d messages, not %d" % (category, found_counts.get(category, 0), count))
    return problems


# Everything wrong with one message, as a list of sentences.
def message_problems(message):
    if not isinstance(message, dict):
        return ["a message isn't an object"]
    label = "message %s" % message.get("id")
    problems = []
    if not isinstance(message.get("id"), int) or isinstance(message.get("id"), bool):
        problems.append(label + ": id must be a whole number")
    if message.get("category") not in CATEGORY_COUNTS:
        problems.append(label + ": unknown category %r" % message.get("category"))
    text = message.get("text")
    if not isinstance(text, str) or text.strip() == "":
        problems.append(label + ": text must be a non-empty string")
    elif len(text.strip()) > config.MAX_PLEDGE_TEXT_CHARS:
        problems.append(label + ": text is over %d characters" % config.MAX_PLEDGE_TEXT_CHARS)
    expected = message.get("expected")
    if not isinstance(expected, dict) or sorted(expected.keys()) != EXPECTED_KEYS:
        problems.append(label + ': expected must have exactly ' + ", ".join(EXPECTED_KEYS))
        return problems
    for problem in expected_problems(expected):
        problems.append(label + ": " + problem)
    return problems


# Everything wrong with one expected answer. Amounts are whole cents (rule 1): 3000 means $30.00.
def expected_problems(expected):
    problems = []
    if expected["status"] not in ("in", "out", "unclear"):
        return ['status must be "in", "out" or "unclear"']
    for key in ("max_cents", "min_cents"):
        value = expected[key]
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            problems.append(key + " must be whole cents or null (3000, not 30.00)")
    conditions_list = expected["conditions"]
    if not is_list_of_names(conditions_list):
        problems.append("conditions must be a list of names")
    if problems:
        return problems
    if expected["status"] == "in":
        if expected["max_cents"] is None:
            problems.append('an "in" answer needs a max_cents')
        elif expected["min_cents"] is not None and expected["min_cents"] > expected["max_cents"]:
            problems.append("min_cents is bigger than max_cents")
    elif expected["max_cents"] is not None or expected["min_cents"] is not None or conditions_list != []:
        problems.append('an "%s" answer has null amounts and no conditions' % expected["status"])
    return problems


# True if the value is a list and every item in it is a text.
def is_list_of_names(value):
    if not isinstance(value, list):
        return False
    for name in value:
        if not isinstance(name, str):
            return False
    return True


# Is the parser's result right? (docs/AI_PARSER.md section 7, scoring)
# "in": status, max, min and conditions must all match exactly. Conditions match ignoring order and
# capital letters, the same way conditions.name_key matches people. "out": the status is enough.
# "unclear": right if the parser also says unclear and asks a follow-up question.
# "Please retype" is never right: it means the AI call or its answer failed, not a real follow-up.
def is_right(expected, result):
    if result["follow_up_question"] == ai_parser.PLEASE_RETYPE_TEXT:
        return False
    if expected["status"] == "unclear":
        return result["status"] == "unclear" and result["follow_up_question"] is not None
    if result["status"] != expected["status"]:
        return False
    if expected["status"] == "out":
        return True
    return (result["max_cents"] == expected["max_cents"]
            and result["min_cents"] == expected["min_cents"]
            and same_names(result["conditions"], expected["conditions"]))


# True if both lists hold the same names, ignoring order, extra spaces and capital letters.
def same_names(first, second):
    return sorted_keys(first) == sorted_keys(second)


# The names as conditions.name_key forms ("  Jay " -> "jay"), in alphabetical order.
def sorted_keys(names):
    keys = []
    for name in names:
        keys.append(conditions.name_key(name))
    return sorted(keys)


# One line for a wrong answer, so the run output shows what the parser got wrong.
def describe_miss(message, result):
    expected = message["expected"]
    return ("   expected %s max=%s min=%s conditions=%s | got %s max=%s min=%s conditions=%s question=%r"
            % (expected["status"], expected["max_cents"], expected["min_cents"], expected["conditions"],
               result["status"], result["max_cents"], result["min_cents"], result["conditions"],
               result["follow_up_question"]))


def main():
    logging.basicConfig(level=logging.INFO, format="   log: %(message)s")
    if not MESSAGES_FILE.exists():
        print("tests/ai_test_messages.json isn't written yet (D74), so nothing was sent to the AI.")
        return
    try:
        data = load_messages(MESSAGES_FILE)
    except ValueError as error:
        print("tests/ai_test_messages.json isn't valid JSON (%s), so nothing was sent to the AI." % error)
        return
    problems = shape_problems(data)
    if problems:
        print("The messages file has problems, so nothing was sent to the AI:")
        for problem in problems:
            print(" -", problem)
        return
    print("G3 run on", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    print("model:", config.AI_MODEL, "| provider:", config.AI_BASE_URL)
    print("messages written by:", data.get("written_by"), "| file SHA-256:", file_fingerprint(MESSAGES_FILE))
    right = 0
    retyped = 0
    right_by_category = {}
    for message in data["messages"]:
        result = ai_parser.parse_pledge(message["text"])
        if result["follow_up_question"] == ai_parser.PLEASE_RETYPE_TEXT:
            retyped = retyped + 1
        if is_right(message["expected"], result):
            right = right + 1
            right_by_category[message["category"]] = right_by_category.get(message["category"], 0) + 1
            print("RIGHT %2d %-10s %s" % (message["id"], message["category"], message["text"]))
        else:
            print("WRONG %2d %-10s %s" % (message["id"], message["category"], message["text"]))
            print(describe_miss(message, result))
        time.sleep(PAUSE_SECONDS)
    print()
    for category, count in CATEGORY_COUNTS.items():
        print("   %-10s %d/%d" % (category, right_by_category.get(category, 0), count))
    print("G3: %d/50 on 50 made-up test messages" % right)
    if retyped > 0:
        print("Warning: %d answers were 'please retype'. Check the log lines above for an HTTP 429 (too many "
              "requests) or a timeout before trusting this score." % retyped)


if __name__ == "__main__":
    main()
