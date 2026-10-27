# Tests for lifecycle.py and the app's startup rules (docs/TEST_PLAN.md sections E and F).
# Step 2.1 has only E10. The lifecycle tests with the fake PayPal come in steps 2.3 and 2.5.

import pytest

import config


# E10: the live PayPal address must be refused.
def test_e10_live_url_is_refused():
    with pytest.raises(RuntimeError):
        config.check_sandbox_url("https://api-m.paypal.com")


# E10: an empty PAYPAL_BASE_URL (a missing .env line) must be refused, not treated as "fine".
def test_e10_empty_url_is_refused():
    with pytest.raises(RuntimeError):
        config.check_sandbox_url("")


# E10: an address that only starts like the sandbox's must be refused.
def test_e10_lookalike_url_is_refused():
    with pytest.raises(RuntimeError):
        config.check_sandbox_url("https://api-m.sandbox.paypal.com.example.com")


# E10: the exact sandbox address is accepted (no error raised).
def test_e10_sandbox_url_is_accepted():
    config.check_sandbox_url("https://api-m.sandbox.paypal.com")
