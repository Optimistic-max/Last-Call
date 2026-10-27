# Sandbox smoke test for paypal_client.py (step 2.2). Real calls to PayPal's sandbox, run by hand only:
#     .venv\Scripts\python -m tests.sandbox_smoke
# pytest never runs it, because its name doesn't start with "test_".
# It moves no money: the order it creates is never approved, so nothing is held.
# It prints IDs and statuses only, never a token or a key. There is no database in this step, so the
# request IDs are not saved anywhere; the log prints them so the run log can record them.

import logging
import uuid

import config
import paypal_client

# The authorization from test B1 (Oct 26, sandbox app last-call-test). It was voided that day.
B1_AUTHORIZATION_ID = "1FV797880C126320B"


# PayPal's error answers name the problem in details[0].issue, like "ORDER_NOT_APPROVED".
def first_issue(data):
    details = data.get("details", [])
    if len(details) == 0:
        return None
    return details[0].get("issue")


def main():
    logging.basicConfig(level=logging.INFO, format="   log: %(message)s")
    config.check_sandbox_url(config.PAYPAL_BASE_URL)

    print("1. Server access token, asked for twice (the log should show only one token request)")
    first = paypal_client.get_access_token()
    second = paypal_client.get_access_token()
    print("   got a token:", first is not None, "| same token both times:", first == second)

    print("2. Browser client token")
    print("   got a client token:", paypal_client.get_client_token() is not None)

    print("3. Create a $1.00 order with intent AUTHORIZE (nobody approves it, so nothing is held)")
    create = paypal_client.create_order(100, "smoke-test", str(uuid.uuid4()))
    order_id = create["data"].get("id")
    print("   HTTP", create["http_status"], "| order", order_id, "| status", create["data"].get("status"))

    print("4. Authorize that unapproved order (expect a refusal and no authorization)")
    if order_id is None:
        print("   skipped: no order was created")
    else:
        authorize = paypal_client.authorize_order(order_id, str(uuid.uuid4()))
        print("   HTTP", authorize["http_status"], "| error", authorize["data"].get("name"),
              "| issue", first_issue(authorize["data"]))
        print("   authorization in the answer:", paypal_client.first_authorization(authorize["data"]) != {})

    print("5. Read B1's authorization", B1_AUTHORIZATION_ID, "(expect VOIDED)")
    hold = paypal_client.get_authorization(B1_AUTHORIZATION_ID)
    print("   HTTP", hold["http_status"], "| status", hold["data"].get("status"),
          "| amount", hold["data"].get("amount"))


if __name__ == "__main__":
    main()
