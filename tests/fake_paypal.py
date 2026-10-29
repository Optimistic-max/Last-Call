# A stand-in for paypal_client.py in the lifecycle tests (docs/TEST_PLAN.md, "How we test without real
# PayPal"). It has the same function names and gives answers in the same shape,
# {"http_status": ..., "data": ..., "debug_id": ...}, but nothing ever leaves the laptop.
#
# Every call is recorded in `calls`. By default each function gives the happy-path answer: order
# CREATED, hold CREATED, void 204, the hold reads back VOIDED, capture 201 COMPLETED, and the capture
# reads back with a fee of $0.62 and a net of $4.38. A test that wants something else (a declined card,
# a refused capture, no answer) puts the answers it wants in `next_answers` first.
# Step 2.3 added the pledge and hold calls, step 2.5 the capture calls (D42).

import uuid

import paypal_client

calls = []
next_answers = {}

# Pure helpers with no HTTP in them, so the real ones are used: one finds the hold inside an authorize
# answer, the other turns PayPal's "0.62" into 62 cents.
first_authorization = paypal_client.first_authorization
paypal_string_to_cents = paypal_client.paypal_string_to_cents


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


# A capture answer: HTTP 201 with the capture's ID and status. COMPLETED means charged.
def captured(capture_id, status):
    return answer(201, {"id": capture_id, "status": status})


# A capture PayPal refused: HTTP 422 with the reason in details[0].issue, like TRANSACTION_REFUSED
# (docs/PAYPAL_INTEGRATION.md section 4).
def capture_refused(issue):
    return answer(422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": issue}]})


# A capture read back with PayPal's fee and net, as text, the way PayPal sends them.
def capture_read_back(capture_id, fee_text, net_text):
    breakdown = {"paypal_fee": {"currency_code": "USD", "value": fee_text},
                 "net_amount": {"currency_code": "USD", "value": net_text}}
    return answer(200, {"id": capture_id, "status": "COMPLETED", "seller_receivable_breakdown": breakdown})


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


def capture_authorization(auth_id, amount_cents, request_id):
    details = {"auth_id": auth_id, "amount_cents": amount_cents, "request_id": request_id}
    return record_and_answer("capture_authorization", details, captured(new_id("CAPTURE"), "COMPLETED"))


def get_capture(capture_id):
    details = {"capture_id": capture_id}
    return record_and_answer("get_capture", details, capture_read_back(capture_id, "0.62", "4.38"))
