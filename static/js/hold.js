// Hold to confirm (D102). Owner: Samuel (docs/TEAM.md). A money button with class "hold-btn" only acts
// after it has been held for 800ms, so a stray tap can't send a refund or place a hold.
//
// - Pointer: holding a finger or the mouse on the button fills the amber ring. Letting go early cancels.
// - Keyboard: holding Enter or Space does the same.
// - When the ring is full, the button shows a check, then its real action runs exactly once: a form
//   button submits its form, and any other button gets one confirmed click, which reaches its own
//   listeners unchanged (for Hold my max, Emmanuel's listener in pledge_paypal.js).
// - Any other click on the button is stopped before it reaches anything, so a quick tap does nothing.
// - Without this file the buttons work as normal buttons, and the ring and the hint stay hidden.

const HOLD_MS = 800;          // how long to hold (the CSS fills the ring over the same time)
const CHECK_SHOW_MS = 250;    // the check shows this long before the action runs
const READY_TEXT = "Press and hold to confirm";
const HOLDING_TEXT = "Hold to confirm";
const DONE_TEXT = "Confirmed";

const holdTimers = new Map();   // button -> its running timer


// The small line under the button, which a screen reader also reads (role="status").
function holdStatus(button) {
  return button.nextElementSibling;
}


// Start the hold, unless the button is switched off or has already fired.
function startHold(button) {
  if (button.disabled || button.getAttribute("aria-disabled") === "true" || holdTimers.has(button)) {
    return;
  }
  button.classList.add("holding");
  holdStatus(button).textContent = HOLDING_TEXT;
  holdTimers.set(button, setTimeout(function () {
    finishHold(button);
  }, HOLD_MS));
}


// Let go early: nothing happens, and the ring drains back.
function cancelHold(button) {
  if (!holdTimers.has(button)) {
    return;
  }
  clearTimeout(holdTimers.get(button));
  holdTimers.delete(button);
  button.classList.remove("holding");
  holdStatus(button).textContent = READY_TEXT;
}


// The ring is full: show the check, switch the button off so it can't fire twice, then act.
function finishHold(button) {
  holdTimers.delete(button);
  button.classList.add("done");
  button.setAttribute("aria-disabled", "true");
  holdStatus(button).textContent = DONE_TEXT;
  setTimeout(function () {
    runAction(button);
  }, CHECK_SHOW_MS);
}


// A submit button sends its form. Any other button gets one click marked as confirmed.
function runAction(button) {
  if (button.form && button.type === "submit") {
    button.form.requestSubmit(button);
    return;
  }
  const click = new MouseEvent("click", { bubbles: true, cancelable: true });
  click.holdConfirmed = true;
  button.dispatchEvent(click);
}


// When the page switches the button off and on again (Hold my max after a failed card), it can be
// held again. Until then it stays switched off, so it never fires twice.
function watchForRetry(button) {
  let wasOffAfterDone = false;
  const watcher = new MutationObserver(function () {
    if (!button.classList.contains("done")) {
      return;
    }
    if (button.disabled) {
      wasOffAfterDone = true;
    } else if (wasOffAfterDone) {
      wasOffAfterDone = false;
      button.classList.remove("done", "holding");
      button.removeAttribute("aria-disabled");
      holdStatus(button).textContent = READY_TEXT;
    }
  });
  watcher.observe(button, { attributes: true, attributeFilter: ["disabled"] });
}


// Stop every click that a hold didn't confirm: a quick tap, Enter pressed in a form, a keyboard click.
// Capture runs before the button's own listeners.
function stopUnconfirmedClicks(event) {
  const button = event.target.closest(".hold-btn");
  if (button !== null && !event.holdConfirmed) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}


// Holding Enter or Space works like holding the pointer. preventDefault stops the key's own click and,
// for Space, the page scrolling.
function onHoldKey(event) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  event.preventDefault();
  if (event.type === "keydown" && !event.repeat) {
    startHold(event.currentTarget);
  } else if (event.type === "keyup") {
    cancelHold(event.currentTarget);
  }
}


// Set up one button: its status line, and its pointer and key events.
function startHoldButton(button) {
  const status = document.createElement("p");
  status.className = "hold-status";
  status.setAttribute("role", "status");
  status.textContent = READY_TEXT;
  button.insertAdjacentElement("afterend", status);
  button.addEventListener("pointerdown", function (event) {
    if (event.button === 0) {
      startHold(button);
    }
  });
  for (const name of ["pointerup", "pointerleave", "pointercancel"]) {
    button.addEventListener(name, function () {
      cancelHold(button);
    });
  }
  button.addEventListener("keydown", onHoldKey);
  button.addEventListener("keyup", onHoldKey);
  button.addEventListener("contextmenu", function (event) {
    event.preventDefault();
  });
  watchForRetry(button);
}


document.documentElement.classList.add("hold-js");
document.addEventListener("click", stopUnconfirmedClicks, true);
for (const button of document.querySelectorAll(".hold-btn")) {
  startHoldButton(button);
}
