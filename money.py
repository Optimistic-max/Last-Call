# All the money math, as pure functions (AGENTS.md rule 2, docs/MONEY_RULES.md). Owner: Malama.
# Pure means: whole cents in, whole cents out. No database, no PayPal, no clock, and never a float
# (rule 1). The fee and the minimums come from config.py, so they are written down in one place only.

import config

# Basis points are hundredths of a percent, so 10000 basis points is 100%.
BASIS_POINTS_IN_100_PERCENT = 10000


# True if text is one or more of the plain digits 0-9. isdigit() alone would also accept
# digits from other alphabets, like the full-width "４０", so isascii() is checked too.
def is_plain_digits(text):
    return text.isascii() and text.isdigit()


# "40" -> 4000, "40.5" -> 4050, "40.05" -> 4005. For amounts a person types.
# Spaces at the start and end are ignored. Anything else that isn't plain digits with an optional
# dot and 1 or 2 decimals is refused: negatives, commas, "$", "40.", ".50", "40.555", "1e3".
# The dollars and the cents are read as two separate whole numbers, so no float is ever made.
# Whether the amount is big enough (the $5 minimum) is checked elsewhere.
def dollars_text_to_cents(text):
    if not isinstance(text, str):
        raise ValueError("Type an amount like 40 or 40.50.")
    dollars_text, dot, cents_text = text.strip().partition(".")
    if not is_plain_digits(dollars_text):
        raise ValueError("Type an amount like 40 or 40.50.")
    if dot == "":
        return int(dollars_text) * 100
    if len(cents_text) == 1:
        cents_text = cents_text + "0"    # "40.5" means 40 dollars and 50 cents
    if len(cents_text) != 2 or not is_plain_digits(cents_text):
        raise ValueError("Type an amount like 40 or 40.50.")
    return int(dollars_text) * 100 + int(cents_text)


# PayPal's sandbox fee on one charge: 2.59% rounded to the nearest cent (half-up), plus 49 cents
# (MONEY_RULES.md section 2). Adding half of 10000 before dividing is what rounds half-up.
# Only for planning the goal: the treasurer's real net always comes from PayPal's own numbers.
def estimate_fee_cents(share_cents):
    top = share_cents * config.FEE_PERCENT_BASIS_POINTS + BASIS_POINTS_IN_100_PERCENT // 2
    percent_part = top // BASIS_POINTS_IN_100_PERCENT
    return percent_part + config.FEE_FIXED_CENTS


# How much to collect so the club still has the full deposit after every fee (D11):
#     goal = (deposit + 0.495 x pledgers) / 0.9741, rounded UP to the cent
# 0.495 is the 49-cent fee plus half a cent of padding, because each fee is rounded to the nearest cent.
# Everything is doubled to work in half cents, so 49.5 cents becomes the whole number 99.
# 0.9741 is the share of each charge the club keeps: 10000 - 259 = 9741 basis points.
# -(-top // bottom) divides and rounds UP (// on its own rounds down).
def fee_adjusted_goal_cents(deposit_cents, number_of_pledgers):
    padded_fixed_fee_half_cents = 2 * config.FEE_FIXED_CENTS + 1
    kept_basis_points = BASIS_POINTS_IN_100_PERCENT - config.FEE_PERCENT_BASIS_POINTS
    top = (2 * deposit_cents + padded_fixed_fee_half_cents * number_of_pledgers) * BASIS_POINTS_IN_100_PERCENT
    bottom = 2 * kept_basis_points
    return -(-top // bottom)


# Is the goal reached (MONEY_RULES.md section 4)? counted_max_cents_list holds the max of every
# pledge the circle rule counts. The goal check and the lock both use fee_adjusted_goal_cents,
# so they can never disagree about the goal (test C8).
def goal_is_reached(deposit_cents, counted_max_cents_list):
    if len(counted_max_cents_list) == 0:
        return False
    goal = fee_adjusted_goal_cents(deposit_cents, len(counted_max_cents_list))
    return sum(counted_max_cents_list) >= goal


# Split the goal evenly, but never above anyone's max (MONEY_RULES.md section 5, kept line for
# line the same as the reference there so it can be checked against the doc).
# max_cents_list must be in join order, earliest first: the caller sorts by created_at, then id
# (section 6). Leftover cents from rounding go to the last joiners (D13). Returns the shares in the
# same order. Anyone below $5 is raised to $5; nobody's max is under $5, so that never passes a max.
def compute_shares_cents(goal_cents, max_cents_list):
    count = len(max_cents_list)
    shares = [0] * count
    still_open = list(range(count))      # positions of people not capped yet
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
            for position in reversed(still_open):      # last joiners get the extra cents
                if leftover == 0:
                    break
                shares[position] = shares[position] + 1
                leftover = leftover - 1
            break

        for position in capped:
            shares[position] = max_cents_list[position]
            remaining = remaining - max_cents_list[position]
            still_open.remove(position)

    for position in range(count):                      # $5 minimum share
        if shares[position] < config.MIN_SHARE_CENTS:
            shares[position] = config.MIN_SHARE_CENTS
    return shares
