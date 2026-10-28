# A stand-in for paypal_client.py in the lifecycle tests (docs/TEST_PLAN.md, "How we test without real
# PayPal"). It has the same function names and gives answers in the same shape,
# {"http_status": ..., "data": ..., "debug_id": ...}, but nothing ever leaves the laptop.
#
# Every call is recorded in `calls`. By default each function gives the happy-path answer: order
# CREATED, hold CREATED, void 204, and the hold reads back VOIDED. A test that wants something else
# (a declined card, no answer) puts the answers it wants in `next_answers` first.
# Step 2.3 has only the calls the pledge and hold steps use. Capture comes in step 2.5.

import uuid

import paypal_client

calls = []
next_answers = {}

# A pure helper with no HTTP in it, so the real one is used: it finds the hold inside an authorize answer.
first_authorization = paypal_client.first_authorization


# Forget every call and every queued answer. Each test calls this first, because the lists above
# would otherwise carry over from the test before.
def reset():
    calls.clear()
    next_answers.clear()


# A made-up PayPal ID, like "AUTH3F9A0C1B2D4E5". Random, so IDs never clash with an earlier test's rows.
def new_id(prefix):
    return prefix + uuid.uuid4().hex[:13].upper()


def answer(http_status, data):
    return {"http_status": http_status, "data": data, "debug_id": "FAKE-DEBUG-ID"}


# What paypal_client returns when PayPal never answered (a timeout).
def no_answer():
    return {"http_status": None, "data": {}, "debug_id": ""}


def order_created(order_id):
    return answer(201, {"id": order_id, "status": "CREATED"})


# An authorize answer holding one authorization with this status (CREATED, DENIED, ...).
# A declined card still comes back as HTTP 201 (rule 5).
def authorized(status, auth_id):
    authorization = {"id": auth_id, "status": status, "expiration_time": "2026-11-25T21:04:51Z"}
    return answer(201, {"status": "COMPLETED", "purchase_units": [{"payments": {"authorizations": [authorization]}}]})


def hold_read_back(status, auth_id):
    return answer(200, {"id": auth_id, "status": status})


# Record the call, then give the test's next queued answer for this function, or the default one.
def record_and_answer(function_name, details, default_answer):
    details["function"] = function_name
    calls.append(details)
    queued = next_answers.get(function_name, [])
    if len(queued) > 0:
        return queued.pop(0)
    return default_answer


# The names of the functions called so far, in order, like ["create_order", "authorize_order"].
def called_functions():
    names = []
    for call in calls:
        names.append(call["function"])
    return names


def create_order(amount_cents, reference_id, request_id):
    details = {"amount_cents": amount_cents, "reference_id": reference_id, "request_id": request_id}
    return record_and_answer("create_order", details, order_created(new_id("ORDER")))


def authorize_order(order_id, request_id):
    details = {"order_id": order_id, "request_id": request_id}
    return record_and_answer("authorize_order", details, authorized("CREATED", new_id("AUTH")))


def get_authorization(auth_id):
    return record_and_answer("get_authorization", {"auth_id": auth_id}, hold_read_back("VOIDED", auth_id))


def void_authorization(auth_id, request_id):
    details = {"auth_id": auth_id, "request_id": request_id}
    return record_and_answer("void_authorization", details, answer(204, {}))
