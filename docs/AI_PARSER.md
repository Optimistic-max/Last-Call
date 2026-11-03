# AI pledge reader

Owner: **Malama**. Lives in `ai_parser.py`. Wired into the pledge page in milestone **M4**; the parser itself may be built earlier, as a parallel lane (D48). The model is chosen (D15).

> **D31 (APPROVED, Oct 26): own-words pledge flow.** This page describes it. Each friend types their own pledge on the event link page, and the AI reads that one message. The treasurer chat paste is deferred (`docs/LATER.md`).

## 1. Job

Turn one friend's own-words message into a **suggested** pledge: amount, cap and condition. The friend sees an editable confirm step, can fix any of the three, and **nothing is saved until they confirm**: the parse result stays only in the page, and the pledge row is created at confirm. The AI never creates a hold, never charges, never decides a share. After the friend confirms, the card step is the B1 flow, unchanged.

Amount is the minimum (`min_dollars`, shown only, D12) and cap is the maximum held (`max_dollars`). Approved with D31.

On screen: **"AI reads. You confirm. Plain code handles the money."**

## 2. Input

The text one friend types into the pledge box on the event link page. One message per request, for example:

```
down if Jay goes, max 40
im in if ana is lol
$20 i guess
actually im out sorry
maybe??
```

The friend's name (required) comes from the form field, never from the AI, so nobody is asked for the same thing twice. There is no email field before the freeze (D62). Quick-amount buttons (D31) fill in an amount without typing; the friend still confirms.

## 3. Output (the model must return exactly this JSON)

For "down if Jay goes, max 40":

```json
{
  "status": "in",
  "max_dollars": 40,
  "min_dollars": null,
  "conditions": ["Jay"],
  "follow_up_question": null
}
```

For "maybe??":

```json
{
  "status": "unclear",
  "max_dollars": null,
  "min_dollars": null,
  "conditions": [],
  "follow_up_question": "Are you in? What's the most you'd pay?"
}
```

| Field | Allowed values |
|---|---|
| `status` | `"in"`, `"out"`, `"unclear"` |
| `max_dollars`, `min_dollars` | a number or `null` |
| `conditions` | list of names that must also be in (can be empty) |
| `follow_up_question` | text when `status` is `"unclear"` or the max is missing, otherwise `null` |

## 4. Plain-code validation (after the model answers)

Never trust the model's JSON directly. `ai_parser.validate_pledge(raw, message_text)` takes the model's answer and the friend's own message, and returns amounts in **cents** (rule 1). It must:

1. Parse the JSON with numbers that have decimals kept as text (`json.loads(raw, parse_float=str)`), so no float is ever made (rule 1, D63). If it doesn't parse, return a "please retype" result.
2. Drop unknown fields. Reject wrong types ("please retype").
3. Convert dollars to cents with `money.dollars_text_to_cents` (whole numbers only, at most two decimals). A max must be from `config.MIN_MAX_CENTS` ($5) to `config.MAX_MAX_CENTS` ($2,000, D58), the range test C3 covers (D63).
4. Any max under $5 means the card becomes `unclear` with "The minimum is $5. What's your max?". A max over $2,000 becomes `unclear` with "The largest max is $2,000.00. What's your max?". An `in` with no max becomes `unclear` with "What's the most you'd pay?". A min above the max becomes "please retype".
5. **Nothing the friend didn't type (enforces G1).** Every amount (`max_dollars`, `min_dollars`) must be a number that appears in the friend's message (commas removed, so "1,000" reads as 1000; "$40," reads as 40). Every condition must appear in the message as a whole word, ignoring case and punctuation ("Jay" is found in "if Jay's in"). If any value fails, the **whole** suggestion becomes "please retype", not just that field, because quietly dropping a condition would turn "only if Jay's in" into an unconditional pledge. Trade-off: amounts written in words ("forty") always come back as "please retype", and the friend types the number.
6. Keep each condition as a name, tidied with `conditions.tidy_name`, with blanks and repeats removed. It doesn't have to match anyone yet: the circle rule decides who is counted (D06), and the board shows "Waiting on [name]".
7. An `out` answer keeps no amounts and no conditions.

If the model call fails or times out, show: **"Couldn't read that. Please retype it, or fill in the amount, cap and condition yourself."** The friend can always fill in the confirm step by hand.

## 5. Prompt rules (write in `ai_parser.py`)

- Say the output must be the JSON above and nothing else.
- Say: never guess an amount. If no number is stated, `max_dollars` is `null` and the card is `unclear`.
- Say: "I'm out", "can't make it", "nvm" mean `out`.
- Say: "if X goes", "only if X's in", "down if X" mean a condition on X.
- Say: "in for 20, up to 40 if we're short" means `min_dollars` 20, `max_dollars` 40.
- Say: if the message isn't about joining or paying, the status is `unclear`, with a follow-up question.
- Use a low temperature (or the model's most deterministic setting).

## 6. Privacy

Typing a pledge sends that text to a third-party AI service. The pledge page must say: **"What you type here is sent to [model provider] to read it. Don't type anything private."** For the demo, use only made-up pledges.

## 7. The 50-message accuracy test

- **Written and frozen by Grok Bot before Malama tunes the prompt**, so the person tuning isn't writing the exam. Saved as `tests/ai_test_messages.json` and never edited after it's frozen (record the freeze date in `docs/DECISIONS.md`).
- All messages are made up. The README says so.
- Under D31 each test message is read as one friend's own-words pledge. The categories and scoring stay the same; non-pledge chatter is expected back as `unclear` with a follow-up.

| Category | Count |
|---|---|
| Plain pledges ("I'm in, $30") | 10 |
| Slang ("bet, down for 25") | 8 |
| Named conditions ("only if Jay and Maya go") | 8 |
| Ranges ("in for 20, up to 40 if we're short") | 6 |
| Pull-outs ("actually I'm out") | 6 |
| Unclear, needs a follow-up ("maybe??") | 6 |
| Non-pledge chatter | 6 |
| **Total** | **50** |

**Scoring:** a message is right only if `status`, max, min and conditions all match exactly. For an unclear message, asking a follow-up counts as right. Report the score as **"X/50 on 50 made-up test messages"**.

**Honesty rule:** if the prompt changes after the first scored run, report **both** scores (before and after).

## 8. Model choice (decided: D15, Oct 27)

Groq, `openai/gpt-oss-20b`, with strict `json_schema` output. The privacy note in §6 names Groq. Free-plan limits are still `unverified` until someone reads them in the Groq console. Details, sources and the backup model are in `docs/DECISIONS.md` D15.
