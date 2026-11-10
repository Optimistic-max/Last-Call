// The look and feel of the pledge page. Owner: Samuel (docs/TEAM.md).
// static/js/pledge_paypal.js (Emmanuel's) does all the real work: the AI check, saving the pledge and the
// hold. This file only watches what that script writes on the page, and never changes a value:
// 1. After Check, it marks the boxes the AI filled, so the friend looks at them. Editing a box clears it.
// 2. After Continue, it moves down to the card step.
// 3. After a hold finishes, the result replaces the card step.
// In step mode (static/js/pledge_steps.js adds "steps-on" to #pledge, D104) that file moves between the
// steps and shows the end, so 2 and 3 are left to it.

const pledgeForm = document.getElementById("pledge");
const checkMessageLine = document.getElementById("check-message");
const resultLine = document.getElementById("message");
const holdStep = document.getElementById("step-hold");
const suggestedBoxIds = ["pledge-max", "pledge-min", "pledge-conditions"];

let boxesBeforeCheck = {};   // what each box said when Check was pressed
let friendPressedSave = false;   // true once Continue or Hold was pressed, so a message that shows
                                 // while the page loads never moves the page on its own


// Remember the boxes, so the answer can be compared with them.
function rememberBoxes() {
  boxesBeforeCheck = {};
  for (const id of suggestedBoxIds) {
    boxesBeforeCheck[id] = document.getElementById(id).value;
  }
}


// Show or hide the "Filled by AI" mark on one box. The hint's id is the box's id plus "-ai".
function markBox(id, isFilled) {
  document.getElementById(id).classList.toggle("ai-filled", isFilled);
  document.getElementById(id + "-ai").hidden = !isFilled;
}


// Check's answer has arrived, so any box that changed was filled by the AI.
function markFilledBoxes() {
  if (checkMessageLine.textContent === "") {
    return;
  }
  for (const id of suggestedBoxIds) {
    const box = document.getElementById(id);
    if (box.value !== boxesBeforeCheck[id]) {
      markBox(id, box.value !== "");
    }
  }
}


// Continue has saved the pledge, so the card step is next. Phones would otherwise leave it below the fold.
function moveToHoldStep() {
  if (pledgeForm.classList.contains("steps-on")) {
    return;
  }
  if (document.getElementById("hold-text").textContent !== "") {
    holdStep.scrollIntoView({ block: "start" });
  }
}


// After "Held" or "Pledging closed" there is nothing left to do here, so the result replaces the card
// step. After "Card declined" the step stays, and everything typed stays with it (D31).
function showResultOfHold() {
  const isHeld = !document.getElementById("leave-link-line").hidden;
  const isClosed = resultLine.textContent.startsWith(pledgeForm.dataset.closedResult);
  if ((isHeld || isClosed) && !pledgeForm.classList.contains("steps-on")) {
    holdStep.hidden = true;
  }
  if (friendPressedSave && resultLine.textContent !== "") {
    resultLine.scrollIntoView({ block: "center" });
    if (document.getElementById("hold-text").textContent === "") {
      shakeRefusedBox();
    }
  }
}


// Continue was refused, so shake the first required box that is still empty, or else the message.
// animationend takes the class off again, so the next refusal can shake too.
function shakeRefusedBox() {
  const required = [document.getElementById("pledge-name"), document.getElementById("pledge-max")];
  let target = resultLine;
  for (const box of required) {
    if (box.value.trim() === "" && target === resultLine) {
      target = box;
    }
  }
  target.classList.add("shake");
  target.addEventListener("animationend", function () {
    target.classList.remove("shake");
  }, { once: true });
}


// Run a function each time a line's text changes.
function watchText(element, onChange) {
  new MutationObserver(onChange).observe(element, { childList: true });
}


// Remember that the friend pressed a button that can end in a message.
function noteSavePressed() {
  friendPressedSave = true;
}


function startPledgePage() {
  document.getElementById("check-button").addEventListener("click", rememberBoxes);
  document.getElementById("confirm-button").addEventListener("click", noteSavePressed);
  document.getElementById("hold-button").addEventListener("click", noteSavePressed);
  for (const id of suggestedBoxIds) {
    document.getElementById(id).addEventListener("input", function () {
      markBox(id, false);
    });
  }
  watchText(checkMessageLine, markFilledBoxes);
  watchText(document.getElementById("hold-text"), moveToHoldStep);
  watchText(resultLine, showResultOfHold);
}


startPledgePage();
