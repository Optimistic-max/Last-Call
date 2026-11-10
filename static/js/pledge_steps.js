// The pledge page as three steps, one on screen at a time (D104). Owner: Samuel (docs/TEAM.md).
//
// static/js/pledge_paypal.js (Emmanuel's) does all the real work: the AI check, saving the pledge and the
// hold. This file never changes a value the friend typed, never sends anything to the server, and does no
// money math. It only shows one step at a time and moves on when pledge_paypal.js says it is safe to:
//   Step 1 "Say it your way"  Next presses the real Check button when there are words to read.
//   Step 2 "Check it"         opens when Check filled a box, or straight away when there were no words.
//   Step 3 "Hold it"          opens ONLY when #hold-text gets text, which pledge_paypal.js writes when the
//                             server has accepted the pledge. There is no other way in.
//   "You're in"               the end of step 3, when the friend's own leave link appears.
// Without this file the three steps show one under another, as before (pledge.html, D104).
//
// The page's scripts are plain scripts, so they share one set of top-level names. Names here are chosen so
// they never repeat one in pledge_paypal.js, pledge_page.js, hold.js, ribs.js or theme.js: a repeated
// const stops the whole file before it runs.

const STEP_MS = 340;                                 // how long a step takes to slide in
const STEP_EASE = "cubic-bezier(0.23, 1, 0.32, 1)";  // starts fast and settles gently
const STEP_SLIDE_PERCENT = 12;                       // how far a step slides, as a share of its width
const CHECK_GIVE_UP_MS = 25000;   // pledge_paypal.js stops a Check at 20s; this is a backstop after that
const FIELD_FOCUS_CHECK_MS = 150; // how often to see which PayPal field has focus (see watchCardFieldFocus)

// Words on the screen. Placeholders until Samuel approves them (D57).
const NEXT_TEXT = "Next";
const SKIP_TEXT = "Skip, I'll fill it in";
const READING_TEXT = "Reading your words…";
const DONE_TITLE = "You're in";
const DONE_COUNT = "All 3 steps done";

const pledge = document.getElementById("pledge");
const wordsBox = document.getElementById("pledge-message");
const checkButton = document.getElementById("check-button");
const checkLine = document.getElementById("check-message");
const stepResultLine = document.getElementById("message");
const holdText = document.getElementById("hold-text");
const leaveLine = document.getElementById("leave-link-line");
const stepsReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const boxesTheAiFills = ["pledge-max", "pledge-min", "pledge-conditions"];

let currentStep = 1;
let holdUnlocked = false;      // true once #hold-text has text: the server accepted the pledge
let ended = false;             // true after "Held" or "Pledging closed": the flow is over
let waitingForCheck = false;   // true while Next waits for the AI's answer
let giveUpTimer = null;
let wordsBeingChecked = "";    // the words Next sent to Check
let lastCheckedWords = null;   // the words the AI last answered, so Next never overwrites edited boxes
let lastCheckFilled = false;   // whether that answer filled any box
let boxesBeforeNext = {};     // each box's value when Next pressed Check
let fieldFocusTimer = null;


// The section for step 1, 2 or 3.
function stepSection(number) {
  return pledge.querySelector('.pledge-step[data-step="' + number + '"]');
}


// Step 3 only after the server accepted the pledge, and never back to 1 or 2 after that, because
// pledge_paypal.js has locked the boxes so the hold is for exactly what was saved.
function allowedStep(number) {
  if (holdUnlocked) {
    return 3;
  }
  return Math.min(Math.max(number, 1), 2);
}


// Show a step: it takes its place in the page, and screen readers and the keyboard can reach it again.
function showStep(section) {
  section.classList.remove("step-inactive", "step-leaving");
  section.inert = false;
  section.removeAttribute("aria-hidden");
}


// Put a step away without display:none, so PayPal's card fields in step 3 keep their size while they
// wait. inert takes it out of the keyboard order, and aria-hidden out of what a screen reader reads.
function hideStep(section) {
  section.classList.add("step-inactive");
  section.inert = true;
  section.setAttribute("aria-hidden", "true");
}


// Stop any slide still running, so a quick second press never leaves two steps on screen.
function stopSliding() {
  for (const section of pledge.querySelectorAll(".pledge-step")) {
    for (const animation of section.getAnimations()) {
      animation.cancel();
    }
    section.classList.remove("step-leaving");
  }
}


// The old step slides out one way while the new one slides in from the other (Back reverses it).
// Transform and opacity only, so the browser never has to lay the page out again. With reduced motion
// the swap is instant: both steps are already in their final state before this runs.
function slide(from, to, forward) {
  if (stepsReducedMotion.matches || typeof to.animate !== "function") {
    return;
  }
  const away = (forward ? -1 : 1) * STEP_SLIDE_PERCENT + "%";
  const toward = (forward ? 1 : -1) * STEP_SLIDE_PERCENT + "%";
  const timing = { duration: STEP_MS, easing: STEP_EASE };
  from.classList.add("step-leaving");
  const leaving = from.animate([
    { transform: "translateX(0)", opacity: 1 },
    { transform: "translateX(" + away + ")", opacity: 0 },
  ], timing);
  leaving.onfinish = function () {
    from.classList.remove("step-leaving");
  };
  to.animate([
    { transform: "translateX(" + toward + ")", opacity: 0 },
    { transform: "translateX(0)", opacity: 1 },
  ], timing);
}


// "Step 2 of 3" and the bar: done and current steps are amber. Words always, not only colour.
function showProgress() {
  pledge.querySelector(".step-count").textContent = ended ? DONE_COUNT : "Step " + currentStep + " of 3";
  const segments = pledge.querySelectorAll(".step-bar li");
  for (let i = 0; i < segments.length; i += 1) {
    segments[i].classList.toggle("is-reached", ended || i < currentStep);
  }
}


// #message shows Continue's refusals and the hold's result, so it goes into the step on screen.
// It keeps its id, so pledge_paypal.js still finds it.
function placeResultLine(number) {
  if (number === 2) {
    stepSection(2).querySelector(".step-actions").before(stepResultLine);
  } else if (number === 3) {
    stepSection(3).append(stepResultLine);
  }
}


// In step 2, repeat what the AI said, but only while it still describes these words.
function showAiNote() {
  const note = stepSection(2).querySelector(".step-ai-note");
  const fresh = lastCheckFilled && wordsBox.value.trim() === lastCheckedWords;
  note.textContent = fresh ? checkLine.textContent : "";
  note.hidden = !fresh || note.textContent === "";
}


// Move focus to the new step's heading, so a screen reader announces it. preventScroll keeps the page
// still; if the step's top is above the screen (a long step on a phone), the page scrolls up to it.
function focusStep(section) {
  section.querySelector(".step-title").focus({ preventScroll: true });
  const top = pledge.querySelector(".step-progress").getBoundingClientRect().top;
  if (top < 0) {
    pledge.querySelector(".step-progress").scrollIntoView({ block: "start", behavior: stepsReducedMotion.matches ? "auto" : "smooth" });
  }
}


// Go to a step. addToHistory is "push" for a move forward with a button, "replace" to correct the
// address, or "none" when the browser's own back or forward button brought us here.
function goToStep(wanted, addToHistory) {
  const number = allowedStep(wanted);
  const previous = currentStep;
  if (number !== wanted && addToHistory === "none") {
    addToHistory = "replace";   // the browser asked for a step that isn't open: put the address right
  }
  if (number !== previous) {
    const from = stepSection(previous);
    const to = stepSection(number);
    stopSliding();
    hideStep(from);
    showStep(to);
    placeResultLine(number);
    if (number === 2) {
      showAiNote();
    }
    currentStep = number;
    showProgress();
    slide(from, to, number > previous);
    focusStep(to);
  }
  if (addToHistory === "push" && number !== previous) {
    history.pushState({ pledgeStep: number, cameFrom: previous }, "", "#step-" + number);
  } else if (addToHistory === "replace") {
    history.replaceState({ pledgeStep: number }, "", "#step-" + number);
  }
}


// The words on Next: "Skip, I'll fill it in" when Next won't ask the AI, "Next" when it will, or when
// the AI already filled the boxes from these same words.
function updateNextButton() {
  const next = stepSection(1).querySelector(".step-next");
  if (waitingForCheck) {
    next.textContent = READING_TEXT;
    next.disabled = true;
    return;
  }
  next.disabled = false;
  const words = wordsBox.value.trim();
  const alreadyRead = words === lastCheckedWords;
  next.textContent = words === "" || (alreadyRead && !lastCheckFilled) ? SKIP_TEXT : NEXT_TEXT;
}


// Next on step 1. No words, or the same words the AI already read: go straight to step 2 (asking again
// would overwrite boxes the friend may have edited). New words: press the real Check button and wait.
function onNext() {
  const words = wordsBox.value.trim();
  if (words === "" || words === lastCheckedWords) {
    goToStep(2, "push");
    return;
  }
  if (checkButton.disabled) {
    return;   // pledge_paypal.js is busy; a press of Check now would do nothing
  }
  boxesBeforeNext = {};
  for (const id of boxesTheAiFills) {
    boxesBeforeNext[id] = document.getElementById(id).value;
  }
  wordsBeingChecked = words;
  waitingForCheck = true;
  updateNextButton();
  giveUpTimer = setTimeout(stopWaitingForCheck, CHECK_GIVE_UP_MS);
  checkButton.click();
}


// Stop waiting for the AI and give Next back to the friend.
function stopWaitingForCheck() {
  clearTimeout(giveUpTimer);
  waitingForCheck = false;
  updateNextButton();
}


// The AI's answer has arrived: pledge_paypal.js has written its line and switched Check back on. If it
// filled a box, step 2 shows what it filled. If not (a refusal, an error, "that sounds like a no"), the
// friend stays here and reads the line, and Next now says "Skip, I'll fill it in".
function onCheckAnswer() {
  if (!waitingForCheck || checkLine.textContent === "" || checkButton.disabled) {
    return;
  }
  let filledABox = false;
  for (const id of boxesTheAiFills) {
    if (document.getElementById(id).value !== boxesBeforeNext[id]) {
      filledABox = true;
    }
  }
  lastCheckedWords = wordsBeingChecked;
  lastCheckFilled = filledABox;
  stopWaitingForCheck();
  if (filledABox) {
    goToStep(2, "push");
  }
}


// Back on step 2. If this page added the step to the history, the browser's own back does the same
// thing, so use it and keep the two in step; otherwise just show step 1.
function onBack() {
  const state = history.state;
  if (state && state.pledgeStep === currentStep && state.cameFrom === currentStep - 1) {
    history.back();
  } else {
    goToStep(currentStep - 1, "replace");
  }
}


// The browser's back or forward button. goToStep keeps step 3 shut until it is unlocked.
function onHistoryStep(event) {
  const number = event.state && event.state.pledgeStep ? event.state.pledgeStep : stepFromAddress();
  goToStep(number, "none");
}


// "#step-2" in the address means step 2. Anything else means step 1.
function stepFromAddress() {
  const match = window.location.hash.match(/^#step-([123])$/);
  return match ? Number(match[1]) : 1;
}


// pledge_paypal.js filled #hold-text: the server accepted the pledge, so step 3 opens.
function onHoldText() {
  if (holdUnlocked || holdText.textContent === "") {
    return;
  }
  holdUnlocked = true;
  goToStep(3, "push");
}


// The end of the flow, inside step 3: "You're in" with the result line and the friend's own leave link,
// or "Pledging closed". The card fields and the hold button go away, because nothing is left to do.
function endFlow(title) {
  if (ended) {
    return;
  }
  ended = true;
  const section = stepSection(3);
  section.classList.add("step-ended");
  section.querySelector(".step-title-text").textContent = title;
  section.append(stepResultLine);
  section.append(leaveLine);
  showProgress();
  focusStep(section);
}


// "Held" shows the leave link; "Pledging closed" starts with the page's data-closed-result text.
// "Card declined" ends nothing: step 3 stays, so the friend can try another card.
function onHoldResult() {
  if (currentStep !== 3) {
    return;
  }
  if (!leaveLine.hidden) {
    endFlow(DONE_TITLE);
  } else if (stepResultLine.textContent.startsWith(pledge.dataset.closedResult)) {
    endFlow(pledge.dataset.closedResult);
  }
}


// Mark the PayPal box that has focus, so it gets the same black edge as our own fields. The focus is
// inside PayPal's frame, which CSS :focus-within can't see from here, and moving from one PayPal field
// to the next sends this page no event at all. So while the focus is away in a frame (the window says
// "blur"), look every 150ms; stop when it comes back.
function showFocusedCardField() {
  for (const box of pledge.querySelectorAll(".card-field")) {
    box.classList.toggle("is-focused", box.contains(document.activeElement));
  }
}


function watchCardFieldFocus() {
  window.addEventListener("blur", function () {
    showFocusedCardField();
    if (fieldFocusTimer === null) {
      fieldFocusTimer = setInterval(showFocusedCardField, FIELD_FOCUS_CHECK_MS);
    }
  });
  window.addEventListener("focus", function () {
    clearInterval(fieldFocusTimer);
    fieldFocusTimer = null;
    showFocusedCardField();
  });
  document.addEventListener("focusin", showFocusedCardField);
}


// Run a function each time an element's words or one of its attributes change.
function watch(element, onChange, options) {
  new MutationObserver(onChange).observe(element, options);
}


function startSteps() {
  pledge.classList.add("steps-on");
  currentStep = allowedStep(stepFromAddress());
  for (const section of pledge.querySelectorAll(".pledge-step")) {
    if (Number(section.dataset.step) === currentStep) {
      showStep(section);
    } else {
      hideStep(section);
    }
  }
  placeResultLine(2);   // a message while step 1 is on screen waits in step 2 (the card fields' load error)
  showProgress();
  updateNextButton();
  history.replaceState({ pledgeStep: currentStep }, "", "#step-" + currentStep);

  stepSection(1).querySelector(".step-next").addEventListener("click", onNext);
  stepSection(2).querySelector(".step-back").addEventListener("click", onBack);
  wordsBox.addEventListener("input", updateNextButton);
  window.addEventListener("popstate", onHistoryStep);
  watch(checkLine, onCheckAnswer, { childList: true, characterData: true, subtree: true });
  watch(checkButton, onCheckAnswer, { attributes: true, attributeFilter: ["disabled"] });
  watch(holdText, onHoldText, { childList: true, characterData: true, subtree: true });
  watch(leaveLine, onHoldResult, { attributes: true, attributeFilter: ["hidden"] });
  watch(stepResultLine, onHoldResult, { childList: true, characterData: true, subtree: true });
  watchCardFieldFocus();
}


startSteps();
