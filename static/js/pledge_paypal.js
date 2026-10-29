// The PayPal card fields on the pledge page (D16, SDK v6). Owner: Emmanuel (docs/TEAM.md).
// Adapted from the B1 spike, spikes/b1_card_fields/index.html.
//
// The flow (docs/SYSTEM_DESIGN.md section 5A):
// 1. "Continue": POST /api/pledges saves the typed name and max (D31) and sends back a private token.
// 2. "Hold my max": POST /api/orders creates the order (only the server sets intent AUTHORIZE), the card
//    goes to PayPal with session.submit, and only if that succeeded, POST /api/orders/<id>/authorize.
//
// The name on card, card number, expiry and CVV are typed into PayPal's own fields (iframes), so this
// file never sees them (docs/SECURITY.md). It does no money math either: every amount on screen is text
// the server already formatted (docs/UI_DESIGN.md section 7).
// The browser console shows each step's order ID and states, never a token.

const page = document.getElementById("pledge");

let cardSession = null;     // PayPal's card fields, once they have loaded
let pledgerToken = null;    // the pledge's private token from POST /api/pledges
let confirmed = false;      // true once the name and max were saved
let busy = false;           // true while a hold is being placed, so a second click does nothing
let finished = false;       // true after "Held" or "Pledging closed": nothing more to do


// Show one message to the friend, under the button.
function showMessage(text) {
  document.getElementById("message").textContent = text;
}


// "Hold my max" works only when the card fields are ready, the pledge is saved, and nothing is running.
function updateHoldButton() {
  const ready = cardSession !== null && confirmed && !busy && !finished;
  document.getElementById("hold-button").disabled = !ready;
}


// POST a JSON body to our server. Returns {ok, data}. An answer that isn't JSON (an outage page)
// becomes {} instead of stopping the page.
async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }
  return { ok: response.ok, data: data };
}


// The server's message if it sent one, otherwise the general error text from the page.
function messageFrom(answer) {
  if (answer.data.message) {
    return answer.data.message;
  }
  return page.dataset.errorText;
}


// Save the typed name and max as a pledge. The max goes as the typed text: the server turns it into
// whole cents (rule 1). Also used after "Card declined", with the same name and max, so the friend
// never types them twice: D26 reuses the pledge and D32 gives it a new token.
async function savePledge() {
  const answer = await postJson("/api/pledges", {
    event_id: Number(page.dataset.eventId),
    name: document.getElementById("pledge-name").value,
    max: document.getElementById("pledge-max").value,
  });
  if (answer.ok) {
    pledgerToken = answer.data.pledger_token;
  }
  return answer;
}


// "Continue": save the pledge, then lock the name and max, so the hold is for exactly what was saved.
async function confirmPledge() {
  const button = document.getElementById("confirm-button");
  button.disabled = true;
  try {
    const answer = await savePledge();
    if (!answer.ok) {
      showMessage(messageFrom(answer));
      button.disabled = false;
      return;
    }
    document.getElementById("pledge-name").disabled = true;
    document.getElementById("pledge-max").disabled = true;
    document.getElementById("hold-text").textContent = answer.data.hold_text;
    showMessage("");
    confirmed = true;
    updateHoldButton();
  } catch (error) {
    showMessage(page.dataset.errorText);
    button.disabled = false;
  }
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


// Ask our server to authorize the approved order, and show its answer: Held, Card declined, or
// Pledging closed. After a decline the token is dropped, so the next try saves the pledge again.
async function authorizeHold(orderId) {
  const answer = await postJson("/api/orders/" + orderId + "/authorize", { pledger_token: pledgerToken });
  console.log("Authorize answer: " + answer.data.status);
  showMessage(messageFrom(answer));
  if (answer.data.status === "HELD" || answer.data.status === "CLOSED") {
    finished = true;
  }
  if (answer.data.status === "DECLINED") {
    pledgerToken = null;
  }
}


document.getElementById("confirm-button").addEventListener("click", confirmPledge);
document.getElementById("hold-button").addEventListener("click", holdMyMax);
