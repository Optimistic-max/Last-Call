# Money rules

Read this before touching anything with money. All of it lives in `money.py` as pure functions: no database, no PayPal, no clock. Every number comes from `config.py`.

## 1. The numbers (all in `config.py`)

| Setting | Value | Status |
|---|---|---|
| `FEE_PERCENT_BASIS_POINTS` | `259` (2.59%) | VERIFIED in sandbox on $5, $10, $12, $15, $15.37, $25, $60. Live fees `unverified` |
| `FEE_FIXED_CENTS` | `49` | same as above |
| `MIN_SHARE_CENTS` | `500` ($5) | decided |
| `MIN_MAX_CENTS` | `500` (nobody can pledge a max under $5) | decided |
| `PLEDGING_WINDOW` | 48 hours (demo mode: e.g. 10 minutes) | decided (D04) |
| `LAST_CALL_WINDOW` | 1 hour (demo mode: e.g. 3 minutes) | decided |
| `QUICK_AMOUNTS_CENTS` | not chosen yet (the quick-amount buttons, D31) | OPEN (D31) |

## 2. Estimating PayPal's fee on one charge

PayPal charges 2.59% + $0.49 per capture in the sandbox, rounded to the nearest cent. In integer cents:

```python
def estimate_fee_cents(share_cents):
    # 2.59% of the share, rounded half-up to a whole cent, plus the fixed 49 cents
    percent_part = (share_cents * 259 + 5000) // 10000
    return percent_part + 49
```

This matches every sandbox charge we made: $5 → 62¢, $10 → 75¢, $12 → 80¢, $15 → 88¢, $15.37 → 89¢, $25 → $1.14, $60 → $2.04.

**This estimate is only for planning the goal.** The treasurer's real net always comes from PayPal's own numbers on each capture (`seller_receivable_breakdown`), never from this function.

## 3. The fee-adjusted goal (CHANGED from the plan, APPROVED Oct 25, see DECISIONS D11)

The club needs the full deposit **after** fees. Each person is charged once, so with `n` counted pledgers:

```
goal = (deposit + 0.495 × n) / 0.9741, rounded UP to the cent
```

In integer cents, with no floats:

```python
def fee_adjusted_goal_cents(deposit_cents, number_of_pledgers):
    # PayPal's fee is still 49 cents. The extra half cent per pledger is padding:
    # each fee is rounded to the nearest cent (half-up), so it can land up to half a cent high.
    top = (2 * deposit_cents + 99 * number_of_pledgers) * 10000
    bottom = 2 * 9741
    return -(-top // bottom)    # ceiling division: round UP to the next cent
```

**Why 0.495 and not the plan's 0.49:** PayPal's fee is still $0.49; the extra $0.005 is padding because each fee is rounded to the nearest cent (half-up). Rounding can make each fee up to half a cent more than the exact 2.59% + $0.49, and with `n` people those half cents add up to as much as `n` × $0.005. The padding covers exactly that, so with the fee estimate the club is never short (test C3 checks this, NOT RUN). None of the 7 sandbox amounts landed exactly on a half cent, so how PayPal rounds a tie is `unverified`. That doesn't affect the padding, which covers any round-to-nearest rule.

Check it by hand (SIMULATED: the fees come from the estimate in §2, not from real captures): a $300 deposit with 4 people. The plan's goal is $309.99, so the shares are $77.49, $77.50, $77.50, $77.50. Each fee is 2.59% (about $2.007, rounded to $2.01) + $0.49 = **$2.50**, so fees total $10.00 and the club receives **$299.99, a cent short**. With the approved formula the goal is $310.01 and the club receives $300.01.

**SIMULATED** on 200,000 random events (fee estimate, no real captures): the plan's formula left the club short in **37.7%** of them (worst: 19¢ short). The approved one: **0 short**. Script and saved output: `docs/evidence/goal_formula_check.py` and `goal_formula_check_output.txt`. Rerun it any time (an Oct 26 rerun gave the same output).

| Deposit | Pledgers | Plan's goal (old) | Goal now |
|---|---|---|---|
| $300 | 1 | $308.48 | $308.49 |
| $300 | 6 | $311.00 | $311.03 |
| $300 | 12 | $314.02 | $314.08 |
| $300 | 20 | $318.04 | $318.14 |

The goal changes as people join, so it is recomputed at every goal check and once more at lock, with the same function.

## 4. Is the goal reached?

```
counted   = pledges the circle rule counts (conditions.py)
goal      = fee_adjusted_goal_cents(deposit, len(counted))
reached   = len(counted) >= 1 and sum(max_cents of counted) >= goal
```

**Board totals (D31):** the board adds up only held money. A pledge that is only "pledged" or "hold pending" adds $0. This matches the goal check above, which uses only counted pledges, and a counted pledge always has a hold.

## 5. Shares: "split evenly, but never above anyone's max"

1. Start with everyone counted as "open".
2. Even share = remaining goal ÷ number of open people (whole cents, round down).
3. Anyone whose max is at or below the even share pays their **full max** and is no longer open. Subtract their max from the remaining goal. Repeat from step 2.
4. When nobody else hits their max, everyone still open pays the even share.
5. **Leftover cents** (from rounding down) go one cent each to the **last-joined** open pledgers. This is decision D13 (approved Oct 26), which follows Warden's suggestion.
6. Any share below $5 is raised to $5. This only happens in very large groups, and the club then gets slightly more than the goal.

Worked example from the plan: goal $100, maxes $15 / $40 / $40 / $40:
- even share = 100 ÷ 4 = $25.00, and the $15 person is at or below it, so they pay $15. Remaining $85, 3 open.
- even share = 8500 ÷ 3 = 2833¢, nobody else is capped. Leftover 1¢ goes to the last joiner.
- shares: **$15.00, $28.33, $28.33, $28.34** (sum $100.00).

Reference version (plain; `docs/evidence/goal_formula_check.py` runs this exact function; keep it this simple):

```python
def compute_shares_cents(goal_cents, max_cents_list):
    # max_cents_list is in join order (earliest first). Returns shares in the same order.
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
        if shares[position] < 500:
            shares[position] = 500
    return shares
```

Edge case for the leftover rule: an open person can't take an extra cent beyond their max. The loop above skips nobody, because open people are strictly above the even share, so `even_share + 1 <= max`.

## 6. The promises the tests must prove

1. The sum of shares equals the goal (unless the $5 floor raised it).
2. No share is above that person's max. No share is below $5.
3. Using the fee estimate, `sum(share − fee(share)) >= deposit` for every group size and every mix of maxes.
4. Goal check and lock use the same functions, so the goal can't disagree between them.
5. Same inputs always give the same shares (no randomness, no dependence on database order). Always sort by `created_at`, then `id`.

## 7. After the charges

- **Treasurer's net** = sum of `net_cents` from PayPal's capture data. Show it on the board as the real number.
- **Retries:** a refused capture moves no money and costs no fee. The retry that succeeds is billed as one capture (VERIFIED, refusal simulated). So the goal formula still holds after a retry.
- **Refunds keep the fee.** A full refund returns the whole share to the pledger, but PayPal keeps its fee (VERIFIED). The refund-all screen must say so before the treasurer clicks.

## 8. Failure policy at lock (decided)

Retry a failed capture once. If it still fails, mark the event **"needs attention"**, keep the charges that went through, and let the treasurer choose:
- **Refund everyone** (PayPal keeps its fees, so say so on screen), or
- **Send [name] a new pay link** (waits on D28).

No automatic refunds. Filling the gap from other people's leftover holds is a stretch goal only (each extra capture pays its own $0.49, and it breaks conditional pledges if someone was already charged).
