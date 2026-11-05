// The pledge page script: the own-words "Check" button (M4, D31) and the PayPal card fields (D16, SDK v6).
// Owner: Emmanuel (docs/TEAM.md). The card fields are adapted from the B1 spike, spikes/b1_card_fields/index.html.
//
// The flow (docs/SYSTEM_DESIGN.md section 5A):
// 0. "Check" (optional): POST /api/pledges/parse sends the friend's own words to the AI, and the answer
//    fills the max, min and conditions boxes as a SUGGESTION. Nothing is saved (D31, D62). The friend can
//    skip it and type the boxes by hand.
// 1. "Continue": POST /api/pledges saves what is in the boxes (D31, D77) and sends back a private token.
//    It sends the boxes' values, never the AI's answer: the friend reviewed and may have changed them.
// 2. "Hold my max": POST /api/orders creates the order (only the server sets intent AUTHORIZE), the card
//    goes to PayPal with session.submit, and only if that succeeded, POST /api/orders/<id>/authorize.
//
// The name on card, card number, expiry and CVV are typed into PayPal's own fields (iframes), so this
// file never sees them (docs/SECURITY.md). It does no money math either: every amount on screen is text
// the server already formatted (docs/UI_DESIGN.md section 7), and the server checks every value again.
// Text from the server goes on the page with textContent, never innerHTML.
// The browser console shows each step's order ID and states, never a token and never the friend's words.

const page = document.getElementById("pledge");

// Placeholder texts until Samuel approves or replaces them (docs/UI_DESIGN.md section 10, D57).
const REVIEW_TEXT = "Check the boxes below. Nothing is saved until you press Continue.";
const OUT_TEXT = "That sounds like a no, so nothing was filled in.";

// The browser gives up on a Check after this long. The server's own AI limit is 8 seconds
// (config.AI_TIMEOUT_SECONDS, D73), so this leaves room for the database and a slow network.
const CHECK_TIMEOUT_MS = 20000;

let cardSession = null;     // PayPal's card fields, once they have loaded
let pledgerToken = null;    // the pledge's private token from POST /api/pledges
let confirmed = false;      // true once the name, max, min and conditions were saved
let busy = false;           // true while a hold is being placed, so a second click does nothing
let finished = false;       // true after "Held" or "Pledging closed": nothing more to do
let checking = false;       // true while a Check is running, so a double click sends one request
let saving = false;         // true while "Continue" is running, for the same reason

// The boxes the AI's suggestion goes into. They are off while a Check runs, and for good after Continue.
const suggestionBoxIds = ["pledge-message", "pledge-max", "pledge-min", "pledge-conditions"];


// Show one message to the friend, under the hold button.
function showMessage(text) {
  document.getElementById("message").textContent = text;
}


// Show one message to the friend, under the Check button.
function showCheckMessage(text) {
  document.getElementById("check-message").textContent = text;
}


// One place that decides which controls are on. After Continue the saved values are locked, so the hold
// is for exactly what was saved. While a Check or a save runs, both buttons are off, so a double click
// can't send two requests, and the boxes the AI fills are off so the answer can't overwrite a keystroke.
function updateControls() {
  const working = checking || saving;
  document.getElementById("confirm-button").disabled = confirmed || working;
  document.getElementById("check-button").disabled = confirmed || working;
  document.getElementById("pledge-name").disabled = confirmed;
  for (const id of suggestionBoxIds) {
    document.getElementById(id).disabled = confirmed || checking;
  }
}


// "Hold my max" works only when the card fields are ready, the pledge is saved, and nothing is running.
function updateHoldButton() {
  const ready = cardSession !== null && confirmed && !busy && !finished;
  document.getElementById("hold-button").disabled = !ready;
}


// POST a JSON body to our server. Returns {ok, status, data}. An answer that isn't JSON (an outage page)
// becomes {} instead of stopping the page. With timeoutMs, the request is cut off after that long and
// the call throws, which the caller shows as the general error text. Only Check passes a timeout:
// the money calls never do, so a hold is never cut off in the middle.
async function postJson(url, body, timeoutMs) {
  const controller = new AbortController();
  let timer = null;
  if (timeoutMs) {
    timer = setTimeout(function () { controller.abort(); }, timeoutMs);
  }
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    let data = {};
    try {
      data = await response.json();
    } catch (error) {
      data = {};
    }
    return { ok: response.ok, status: response.status, data: data };
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
    }
  }
}


// The server's message if it sent one, otherwise the general error text from the page.
function messageFrom(answer) {
  if (answer.data.message) {
    return answer.data.message;
  }
  return page.dataset.errorText;
}


// The names typed in the conditions box ("Jay, Maya") as a list. Blank pieces are dropped here; the
// server tidies, de-duplicates and limits the list (D77).
function typedConditionNames() {
  const pieces = document.getElementById("pledge-conditions").value.split(",");
  const names = [];
  for (const piece of pieces) {
    if (piece.trim() !== "") {
      names.push(piece.trim());
    }
  }
  return names;
}


// Put the AI's suggestion in the boxes (docs/UI_DESIGN.md section 10). A text field is set only from a
// text; anything else becomes empty. An "in" answer sets all three boxes, so an old suggestion doesn't
// linger. An "unclear" answer sets only what the AI did give, so nothing the friend typed is wiped.
// "out" fills nothing. Returns the line to show under the Check button.
function showSuggestion(data) {
  const maxText = typeof data.max === "string" ? data.max : "";
  const minText = typeof data.min === "string" ? data.min : "";
  const names = Array.isArray(data.conditions) ? data.conditions : [];
  const question = typeof data.follow_up_question === "string" ? data.follow_up_question : "";
  if (data.status === "in") {
    document.getElementById("pledge-max").value = maxText;
    document.getElementById("pledge-min").value = minText;
    document.getElementById("pledge-conditions").value = names.join(", ");
    return question !== "" ? question : REVIEW_TEXT;
  }
  if (data.status === "unclear") {
    if (maxText !== "") {
      document.getElementById("pledge-max").value = maxText;
    }
    if (minText !== "") {
      document.getElementById("pledge-min").value = minText;
    }
    if (names.length > 0) {
      document.getElementById("pledge-conditions").value = names.join(", ");
    }
    return question !== "" ? question : page.dataset.errorText;
  }
  if (data.status === "out") {
    return OUT_TEXT;
  }
  return page.dataset.errorText;
}


// "Check": send the friend's own words to the AI and show its suggestion. Any failure (a refusal, a
// network error, a timeout) shows a message and leaves every box editable: the friend can always fill
// the boxes by hand. The words themselves are never logged.
async function checkMessage() {
  if (checking || saving || confirmed) {
    return;
  }
  checking = true;
  updateControls();
  showCheckMessage("");
  try {
    const answer = await postJson("/api/pledges/parse", {
      event_id: Number(page.dataset.eventId),
      text: document.getElementById("pledge-message").value,
    }, CHECK_TIMEOUT_MS);
    console.log("Check: HTTP " + answer.status);
    if (answer.ok) {
      showCheckMessage(showSuggestion(answer.data));
    } else {
      showCheckMessage(messageFrom(answer));
    }
  } catch (error) {
    console.log("Check stopped: " + error.name);
    showCheckMessage(page.dataset.errorText);
  }
  checking = false;
  updateControls();
}


// Save the pledge from what is in the boxes. The max and min go as the typed text: the server turns them
// into whole cents (rule 1). Also used after "Card declined", with the same values, so the friend never
// types them twice: D26 reuses the pledge and D32 gives it a new token.
async function savePledge() {
  const answer = await postJson("/api/pledges", {
    event_id: Number(page.dataset.eventId),
    name: document.getElementById("pledge-name").value,
    max: document.getElementById("pledge-max").value,
    min: document.getElementById("pledge-min").value,
    conditions: typedConditionNames(),
  });
  if (answer.ok) {
    pledgerToken = answer.data.pledger_token;
  }
  return answer;
}


// "Continue": save the pledge, then lock the boxes, so the hold is for exactly what was saved.
async function confirmPledge() {
  if (checking || saving || confirmed) {
    return;
  }
  saving = true;
  updateControls();
  try {
    const answer = await savePledge();
    if (!answer.ok) {
      showMessage(messageFrom(answer));
    } else {
      document.getElementById("hold-text").textContent = answer.data.hold_text;
      showMessage("");
      confirmed = true;
    }
  } catch (error) {
    showMessage(page.dataset.errorText);
  }
  saving = false;
  updateControls();
  updateHoldButton();
}


// Runs when PayPal's v6 SDK script has loaded (the onload in pledge.html). Gets a client token from our
// server, starts the SDK with card fields, and puts each field into its box on the page.
async function onPayPalWebSdkLoaded() {
  try {
    const tokenResponse = await fetch("/api/client-token");
    if (!tokenResponse.ok) {
      console.log("Client token failed: HTTP " + tokenResponse.status);
      showMessage(page.dataset.errorText);
      return;
    }
    const tokenData = await tokenResponse.json();
    const sdk = await window.paypal.createInstance({
      clientToken: tokenData.clientToken,
      components: ["card-fields"],
      pageType: "checkout",
    });

    // PayPal's guide says this answer may not list cards yet, so it's only logged (as in the B1 spike).
    const methods = await sdk.findEligibleMethods({ currencyCode: "USD" });
    console.log("Eligible for advanced_cards: " + methods.isEligible("advanced_cards"));

    const session = sdk.createCardFieldsOneTimePaymentSession();
    const types = ["name", "number", "expiry", "cvv"];
    for (const type of types) {
      const field = session.createCardFieldsComponent({ type: type });
      document.getElementById("paypal-card-fields-" + type).appendChild(field);
    }
    console.log("Card fields rendered.");
    cardSession = session;
    updateHoldButton();
  } catch (error) {
    console.log("Card fields did not load: " + error);
    showMessage(page.dataset.errorText);
  }
}


// "Hold my max". The button is off while this runs, so a double click can't start two holds.
async function holdMyMax() {
  busy = true;
  updateHoldButton();
  showMessage("");
  try {
    await placeHold();
  } catch (error) {
    console.log("Hold stopped: " + error);
    showMessage(page.dataset.errorText);
  }
  busy = false;
  updateHoldButton();
}


// Create the order on our server, then send the card to PayPal. Only a "succeeded" submit goes on to
// authorize: anything else means PayPal didn't approve the card, so nothing was held.
async function placeHold() {
  if (pledgerToken === null) {
    // After "Card declined" the pledge is DECLINED, so save it again first (D26, D32).
    const again = await savePledge();
    if (!again.ok) {
      showMessage(messageFrom(again));
      return;
    }
  }
  const order = await postJson("/api/orders", { pledger_token: pledgerToken });
  if (!order.ok) {
    showMessage(messageFrom(order));
    return;
  }
  const orderId = order.data.order_id;
  console.log("Order " + orderId + " created.");

  // The billing ZIP is the sample value from PayPal's v6 card-fields guide, as in the B1 spike.
  const result = await cardSession.submit(orderId, { billingAddress: { postalCode: "95131" } });
  console.log("Card submit: " + result.state);
  if (result.state !== "succeeded") {
    console.log("Not approved: " + JSON.stringify(result.data));
    showMessage(page.dataset.errorText);
    return;
  }
  await authorizeHold(orderId);
}


// After "Held", show the friend's own "I'm out" link (S6, D82): their private page, with the token in the
// address. The address goes on the page with textContent, never innerHTML.
function showLeaveLink() {
  const address = window.location.origin + "/p/" + pledgerToken;
  const link = document.getElementById("leave-link");
  link.href = address;
  link.textContent = address;
  document.getElementById("leave-link-line").hidden = false;
}


// Ask our server to authorize the approved order, and show its answer: Held, Card declined, or
// Pledging closed. After a decline the token is dropped, so the next try saves the pledge again.
async function authorizeHold(orderId) {
  const answer = await postJson("/api/orders/" + orderId + "/authorize", { pledger_token: pledgerToken });
  console.log("Authorize answer: " + answer.data.status);
  showMessage(messageFrom(answer));
  if (answer.data.status === "HELD" || answer.data.status === "CLOSED") {
    finished = true;
  }
  if (answer.data.status === "HELD") {
    showLeaveLink();
  }
  if (answer.data.status === "DECLINED") {
    pledgerToken = null;
  }
}


document.getElementById("check-button").addEventListener("click", checkMessage);
document.getElementById("confirm-button").addEventListener("click", confirmPledge);
document.getElementById("hold-button").addEventListener("click", holdMyMax);
updateControls();
