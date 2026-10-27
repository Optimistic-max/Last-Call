# AI pledge reader

Owner: **Malama**. Lives in `ai_parser.py`. Milestone **M4** in the app, but Malama can build and test it from day 1 because it needs no PayPal and no database.

## 1. Job

Turn a pasted group chat into **suggested** pledge cards. The treasurer reviews, edits and confirms every card. The AI never creates a hold, never charges, never decides a share.

On screen: **"AI reads. You confirm. Plain code handles the money."**

## 2. Input

Plain text pasted by the treasurer, one message per line, for example:

```
Ana: down if Jay goes, max 40
Jay: im in if ana is lol
Sam: $20 i guess
Kim: actually im out sorry
Tobi: maybe??
Dee: whos bringing snacks
```

## 3. Output (the model must return exactly this JSON)

```json
{
  "cards": [
    {
      "name": "Ana",
      "status": "in",
      "max_dollars": 40,
      "min_dollars": null,
      "conditions": ["Jay"],
      "follow_up_question": null,
      "source_message": "Ana: down if Jay goes, max 40"
    },
    {
      "name": "Tobi",
      "status": "unclear",
      "max_dollars": null,
      "min_dollars": null,
      "conditions": [],
      "follow_up_question": "Tobi, are you in? What's the most you'd pay?",
      "source_message": "Tobi: maybe??"
    }
  ],
  "ignored": ["Dee: whos bringing snacks"]
}
```

| Field | Allowed values |
|---|---|
| `status` | `"in"`, `"out"`, `"unclear"` |
| `max_dollars`, `min_dollars` | a number or `null` |
| `conditions` | list of names that must also be in (can be empty) |
| `follow_up_question` | text when `status` is `"unclear"` or the max is missing, otherwise `null` |

## 4. Plain-code validation (after the model answers)

Never trust the model's JSON directly. `ai_parser.validate_cards(raw)` must:

1. Parse the JSON. If it doesn't parse, return a "please retype" result.
2. Drop unknown fields. Reject wrong types.
3. Convert dollars to cents with plain code and **no floats**: `int(Decimal(str(dollars)) * 100)`, only after checking the value is a number between 5 and 10,000 (TODO: source needed) with at most two decimals.
4. Any max under $5 means the card becomes `unclear` with "The minimum is $5. What's your max?".
5. Only keep conditions that name a person who appears in the chat. Otherwise make the card `unclear`.
6. Every `source_message` must be an exact line from the input, so the model can't invent messages.

If the model call fails or times out, show: **"Couldn't read that chat. Please retype the pledges or try again."** The treasurer can always add cards by hand.

## 5. Prompt rules (write in `ai_parser.py`)

- Say the output must be the JSON above and nothing else.
- Say: never guess an amount. If no number is stated, `max_dollars` is `null` and the card is `unclear`.
- Say: "I'm out", "can't make it", "nvm" mean `out`.
- Say: "if X goes", "only if X's in", "down if X" mean a condition on X.
- Say: "in for 20, up to 40 if we're short" means `min_dollars` 20, `max_dollars` 40.
- Say: ignore chatter that isn't about joining or paying.
- Use a low temperature (or the model's most deterministic setting).

## 6. Privacy

Pasting a chat sends it to a third-party AI service. The paste screen must say: **"This text is sent to [model provider] to read it. Don't paste anything private."** For the demo, use only the fictional chat.

## 7. The 50-message accuracy test

- **Written and frozen by Grok Bot before Malama tunes the prompt**, so the person tuning isn't writing the exam. Saved as `tests/ai_test_messages.json` and never edited after it's frozen (record the freeze date in `docs/DECISIONS.md`).
- All messages are made up. The README says so.

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

## 8. Model choice (OPEN, Malama decides)

Pick one free model. Record in `docs/DECISIONS.md`: model name, provider, free-tier limits (requests per minute and per day), whether pasted text is used for training, and the date you checked.
