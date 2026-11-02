# Tests for money.py: C1-C8 from docs/TEST_PLAN.md, plus dollars_text_to_cents.
# Plain numbers only: no database, no PayPal, no clock.

import random

import pytest

import config
import money


# What the club keeps after PayPal's estimated fee on every share.
def club_receives_cents(shares):
    total = 0
    for share in shares:
        total = total + share - money.estimate_fee_cents(share)
    return total


# Made-up events for C3 and C6, built the same way as docs/evidence/goal_formula_check.py:
# a deposit from $20 to $2,000, 1 to 40 pledgers, each max from $5 up to the whole goal, and the
# last max topped up if needed so the goal is reached. A fixed seed gives the same events every run.
def random_events(count, seed):
    generator = random.Random(seed)
    events = []
    for _ in range(count):
        deposit = generator.randint(2000, 200000)
        pledgers = generator.randint(1, 40)
        goal = money.fee_adjusted_goal_cents(deposit, pledgers)
        maxes = []
        for _ in range(pledgers):
            maxes.append(generator.randint(config.MIN_MAX_CENTS, goal))
        if sum(maxes) < goal:
            maxes[-1] = maxes[-1] + goal - sum(maxes)
        events.append((deposit, goal, maxes))
    return events


# C1: the estimate matches all 7 fees PayPal's sandbox really charged (MONEY_RULES.md section 2).
def test_c1_fee_estimate_matches_the_7_sandbox_fees():
    sandbox_fees = {500: 62, 1000: 75, 1200: 80, 1500: 88, 1537: 89, 2500: 114, 6000: 204}
    for share_cents, fee_cents in sandbox_fees.items():
        assert money.estimate_fee_cents(share_cents) == fee_cents


# C2: the D11 goals for a $300 deposit (MONEY_RULES.md section 3 table).
def test_c2_goal_for_300_dollars():
    assert money.fee_adjusted_goal_cents(30000, 1) == 30849
    assert money.fee_adjusted_goal_cents(30000, 6) == 31103
    assert money.fee_adjusted_goal_cents(30000, 12) == 31408
    assert money.fee_adjusted_goal_cents(30000, 20) == 31814


# C2: the hand example from MONEY_RULES.md section 3: $300 with 4 people needs $310.01,
# and the club ends up with $300.01.
def test_c2_hand_example_four_people():
    goal = money.fee_adjusted_goal_cents(30000, 4)
    assert goal == 31001
    shares = money.compute_shares_cents(goal, [100000, 100000, 100000, 100000])
    assert club_receives_cents(shares) == 30001


# C3: across 10,000 random events, the club is never short after the estimated fees.
def test_c3_club_is_never_short():
    for deposit, goal, maxes in random_events(10000, seed=3):
        shares = money.compute_shares_cents(goal, maxes)
        assert club_receives_cents(shares) >= deposit


# C4: the plan's example: goal $100, maxes 15/40/40/40. The extra cent goes to the last joiner (D13).
def test_c4_plan_example():
    assert money.compute_shares_cents(10000, [1500, 4000, 4000, 4000]) == [1500, 2833, 2833, 2834]


# C5: estimated fees on odd amounts. $15.37 is a real sandbox charge (89 cents).
# $28.33 and $5.01 were worked out by hand from the formula, not charged in the sandbox:
# 2833 x 2.59% = 73.37 -> 73, + 49 = 122.   501 x 2.59% = 12.98 -> 13, + 49 = 62.
def test_c5_fees_on_odd_amounts():
    assert money.estimate_fee_cents(1537) == 89
    assert money.estimate_fee_cents(2833) == 122
    assert money.estimate_fee_cents(501) == 62


# C6: on the same kind of random events: whole cents only, no share above its max, none below $5,
# and never less than the goal in total. When nobody sits at exactly $5, the floor can't have
# raised anyone, so the shares must add up to exactly the goal.
def test_c6_shares_stay_between_5_dollars_and_each_max():
    for deposit, goal, maxes in random_events(10000, seed=6):
        shares = money.compute_shares_cents(goal, maxes)
        for position in range(len(shares)):
            assert isinstance(shares[position], int)
            assert shares[position] <= maxes[position]
            assert shares[position] >= config.MIN_SHARE_CENTS
        assert sum(shares) >= goal
        if config.MIN_SHARE_CENTS not in shares:
            assert sum(shares) == goal


# C6: a tiny example where the floor applies. $20 among 40 people is about $1 each, so everyone pays $5.
def test_c6_small_shares_are_raised_to_5_dollars():
    goal = money.fee_adjusted_goal_cents(2000, 40)
    shares = money.compute_shares_cents(goal, [1000] * 40)
    assert shares == [500] * 40


# C7: the same inputs give the same shares every time, and the list passed in isn't changed.
def test_c7_same_inputs_same_shares():
    maxes = [1500, 4000, 2600, 9000, 500]
    first = money.compute_shares_cents(12345, maxes)
    second = money.compute_shares_cents(12345, maxes)
    assert first == second
    assert maxes == [1500, 4000, 2600, 9000, 500]


# C8: the goal check uses fee_adjusted_goal_cents, the same function the lock uses to get the goal
# it splits. A stand-in records the call. (That lifecycle.py's lock calls it too is Emmanuel's side.)
def test_c8_goal_check_uses_the_lock_goal_function(monkeypatch):
    calls = []

    def recording_goal(deposit_cents, number_of_pledgers):
        calls.append((deposit_cents, number_of_pledgers))
        return 31001

    monkeypatch.setattr(money, "fee_adjusted_goal_cents", recording_goal)
    assert money.goal_is_reached(30000, [7750, 7750, 7750, 7751]) is True
    assert calls == [(30000, 4)]


# C8: one test through both paths. When the goal check says "reached", the lock's shares add up to
# exactly that goal. One cent less in maxes and the goal check says "not reached".
def test_c8_goal_check_and_lock_agree():
    goal = money.fee_adjusted_goal_cents(30000, 4)
    assert goal == 31001
    assert money.goal_is_reached(30000, [7750, 7750, 7750, 7751]) is True
    assert sum(money.compute_shares_cents(goal, [7750, 7750, 7750, 7751])) == goal
    assert money.goal_is_reached(30000, [7750, 7750, 7750, 7750]) is False


# Nobody counted means the goal is never reached, even though the goal formula alone would allow it.
def test_goal_is_not_reached_with_nobody_counted():
    assert money.goal_is_reached(30000, []) is False


# progress_percent (D54): halfway, one cent short, exactly the goal and over it.
# $300 with 4 people needs $310.01 (31001 cents).
def test_progress_percent_examples():
    assert money.progress_percent(30000, [7750, 7750]) == 50           # 15500 of 30900 (2 people's goal) = 50.16%
    assert money.progress_percent(30000, [7750, 7750, 7750, 7750]) == 99    # 31000 of 31001
    assert money.progress_percent(30000, [7750, 7750, 7750, 7751]) == 100   # exactly the goal
    assert money.progress_percent(30000, [50000, 50000, 50000, 50000]) == 100  # over: capped
    assert isinstance(money.progress_percent(30000, [7750, 7750]), int)


# progress_percent: nobody counted is 0, never a division by zero.
def test_progress_percent_nobody_counted():
    assert money.progress_percent(30000, []) == 0


# progress_percent shows 100 exactly when goal_is_reached is True (D54), on 10,000 random groups
# of 1 to 40 people. The maxes are random, so some groups reach the goal and some don't.
def test_progress_percent_is_100_exactly_when_goal_is_reached():
    generator = random.Random(54)
    reached_count = 0
    for _ in range(10000):
        deposit = generator.randint(2000, 200000)
        maxes = []
        for _ in range(generator.randint(1, 40)):
            maxes.append(generator.randint(config.MIN_MAX_CENTS, 20000))
        percent = money.progress_percent(deposit, maxes)
        assert 0 <= percent <= 100
        assert (percent == 100) == money.goal_is_reached(deposit, maxes)
        if percent == 100:
            reached_count = reached_count + 1
    assert 0 < reached_count < 10000    # both kinds of group really were tested


# club_net_cents (D54): the sum of PayPal's nets, or None when there is nothing real to show.
def test_club_net_cents():
    assert money.club_net_cents([7549, 7549, 7550]) == 22648
    assert money.club_net_cents([]) is None
    assert money.club_net_cents([7549, None, 7550]) is None
    assert money.club_net_cents([0, 0]) == 0


# dollars_text_to_cents: the examples from the task, plus spaces at the ends and a zero.
def test_dollars_text_to_cents_reads_good_amounts():
    assert money.dollars_text_to_cents("40") == 4000
    assert money.dollars_text_to_cents("40.5") == 4050
    assert money.dollars_text_to_cents("40.05") == 4005
    assert money.dollars_text_to_cents(" 40 ") == 4000
    assert money.dollars_text_to_cents("0") == 0
    assert isinstance(money.dollars_text_to_cents("40.05"), int)


# dollars_text_to_cents refuses anything that isn't plain digits with up to 2 decimals.
# "４０" is 40 in full-width digits: Python's isdigit() alone would accept it.
@pytest.mark.parametrize("text", ["-40", "40.555", "1,000", "$40", "forty", "", "  ", "40.", ".50",
                                  "1e3", "40.5.0", "４０", "40 .50", None, 40])
def test_dollars_text_to_cents_refuses_bad_amounts(text):
    with pytest.raises(ValueError):
        money.dollars_text_to_cents(text)
