# Evidence for decision D11 (docs/DECISIONS.md).
#
# Question: does the fee-adjusted goal always leave the club with at least the full deposit
# after PayPal's fees?  Compares the plan's formula (0.49 per pledger) with the approved one
# (0.495 per pledger, D11, approved Oct 25) on random events. The results are SIMULATED:
# fees come from the estimate, not from real captures.
#
# Run it yourself:   python docs/evidence/goal_formula_check.py
# Output from Oct 25, 2026 is saved next to this file in goal_formula_check_output.txt.

import random


def estimate_fee_cents(share_cents):
    # Sandbox fee: 2.59% rounded half-up to a cent, plus 49 cents (matches 7 real sandbox charges)
    percent_part = (share_cents * 259 + 5000) // 10000
    return percent_part + 49


def goal_old_cents(deposit_cents, number_of_pledgers):
    # The plan's formula: (deposit + 0.49 n) / 0.9741, rounded up
    top = (deposit_cents + 49 * number_of_pledgers) * 10000
    return -(-top // 9741)


def goal_new_cents(deposit_cents, number_of_pledgers):
    # Approved formula (D11): (deposit + 0.495 n) / 0.9741, rounded up. PayPal's fee is still
    # 49 cents; the extra half cent is padding because each fee is rounded to the nearest cent.
    top = (2 * deposit_cents + 99 * number_of_pledgers) * 10000
    return -(-top // (2 * 9741))


def compute_shares_cents(goal_cents, max_cents_list):
    # Same rule as docs/MONEY_RULES.md section 5
    count = len(max_cents_list)
    shares = [0] * count
    still_open = list(range(count))
    remaining = goal_cents
    while len(still_open) > 0:
        even_share = remaining // len(still_open)
        capped = []
        for position in still_open:
            if max_cents_list[position] <= even_share:
                capped.append(position)
        if len(capped) == 0:
            for position in still_open:
                shares[position] = even_share
            leftover = remaining - even_share * len(still_open)
            for position in reversed(still_open):
                if leftover == 0:
                    break
                shares[position] = shares[position] + 1
                leftover = leftover - 1
            break
        for position in capped:
            shares[position] = max_cents_list[position]
            remaining = remaining - max_cents_list[position]
            still_open.remove(position)
    for position in range(count):
        if shares[position] < 500:
            shares[position] = 500
    return shares


def club_receives_cents(shares):
    total = 0
    for share in shares:
        total = total + share - estimate_fee_cents(share)
    return total


def run_trials(goal_function, trials, seed):
    random.seed(seed)
    short_count = 0
    worst_short = 0
    for _ in range(trials):
        deposit = random.randint(2000, 200000)          # $20 to $2,000
        pledgers = random.randint(1, 40)
        goal = goal_function(deposit, pledgers)
        maxes = []
        for _ in range(pledgers):
            maxes.append(random.randint(500, goal))     # every max is at least $5
        if sum(maxes) < goal:
            maxes[-1] = maxes[-1] + goal - sum(maxes)
        received = club_receives_cents(compute_shares_cents(goal, maxes))
        if received < deposit:
            short_count = short_count + 1
            worst_short = max(worst_short, deposit - received)
    return short_count, worst_short


# 1. A small example you can check by hand
deposit = 30000
people = 4
old_goal = goal_old_cents(deposit, people)
old_shares = compute_shares_cents(old_goal, [100000] * people)
print("Hand example: $300 deposit, 4 people, nobody capped")
print("  old goal $%.2f, shares %s" % (old_goal / 100, [s / 100 for s in old_shares]))
print("  fees %s, club receives $%.2f" % ([estimate_fee_cents(s) / 100 for s in old_shares],
                                          club_receives_cents(old_shares) / 100))
new_goal = goal_new_cents(deposit, people)
print("  new goal $%.2f, club receives $%.2f" % (new_goal / 100,
                                                 club_receives_cents(compute_shares_cents(new_goal, [100000] * people)) / 100))

# 2. Random events
TRIALS = 200000
old_short, old_worst = run_trials(goal_old_cents, TRIALS, seed=1)
new_short, new_worst = run_trials(goal_new_cents, TRIALS, seed=1)
print("Random events: %d each" % TRIALS)
print("  old formula: %d short (%.1f%%), worst short %d cents" % (old_short, 100 * old_short / TRIALS, old_worst))
print("  new formula: %d short, worst short %d cents" % (new_short, new_worst))
