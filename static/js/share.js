// The share panel on S2 (admin.html) and S3 (board.html). Owner: Samuel (docs/TEAM.md).
// Every Share, Invite and Copy link button opens one panel, the <dialog> from macros.html.
// A .share-button's data-share-url is share_link on S2 and the public pledge path on S3. This file
// never reads the page's own address, because on S2 that address holds the treasurer's private
// admin_token (D18, D59). The words come from the template, and they go on the page with textContent.
//
// Copying never fails silently. It ends in "Copied ✓", or, if the browser won't copy at all, in a
// small field showing the link, to press and hold.

const COPIED_SHOW_MS = 2000;      // how long the button says "Copied ✓"
const CLOSE_MS = 200;             // how long the panel takes to close (the CSS uses the same time)
const DRAG_CLOSE_PX = 100;        // dragging the sheet this far down closes it
const DRAG_CLOSE_SPEED = 0.5;     // so does a quick flick, in pixels per millisecond
const LINK_END_CHARS = 12;        // the end of the link that always shows

const panel = document.getElementById("share-panel");
const sheet = document.querySelector(".share-sheet");
const copyButton = document.getElementById("share-panel-copy");
const moreButton = document.getElementById("share-panel-more");

let dragStartY = null;       // where a drag began, or null when nothing is being dragged
let dragStartTime = 0;
let dragDistance = 0;


// A finger on a touch screen, as opposed to a mouse.
function hasTouchScreen() {
  return window.matchMedia("(pointer: coarse)").matches;
}


// The full link for a button. On S3 data-share-url is a path, so it gets this site's origin in front.
function linkFor(button) {
  return new URL(button.dataset.shareUrl, window.location.origin).href;
}


// The text app link. iPhones want "sms:&body=", and everything else "sms:?&body=". This is the only
// place the browser's name is read.
function messagesAddress(message) {
  let start = "sms:?&body=";
  if (/iPhone|iPad|iPod/.test(navigator.userAgent)) {
    start = "sms:&body=";
  }
  return start + encodeURIComponent(message);
}


// The address behind each tile. encodeURIComponent keeps a title with & or ? from breaking the link.
function tileAddresses(link) {
  const intro = panel.dataset.intro;
  const message = intro + " " + link;
  return {
    messages: messagesAddress(message),
    whatsapp: "https://wa.me/?text=" + encodeURIComponent(message),
    telegram: "https://t.me/share/url?url=" + encodeURIComponent(link) + "&text=" + encodeURIComponent(intro),
    email: "mailto:?subject=" + encodeURIComponent(panel.dataset.subject) + "&body=" + encodeURIComponent(message),
  };
}


// Show the link with its end always visible, so the dots fall in the middle on a narrow phone.
function showLinkInField(link) {
  const split = link.length - LINK_END_CHARS;
  panel.querySelector(".share-link-start").textContent = link.slice(0, split);
  panel.querySelector(".share-link-end").textContent = link.slice(split);
}


// Fill the panel for this link. Messages is for phones, and More apps needs the share menu.
function fillPanel(link) {
  const addresses = tileAddresses(link);
  for (const tile of panel.querySelectorAll(".share-tile")) {
    tile.href = addresses[tile.dataset.target];
  }
  panel.querySelector('[data-target="messages"]').hidden = !hasTouchScreen();
  moreButton.hidden = navigator.share === undefined;
  copyButton.dataset.shareUrl = link;
  showLinkInField(link);
  const oldField = panel.querySelector(".manual-copy");
  if (oldField !== null) {
    oldField.remove();
  }
}


// The CSS removes the page's scrollbar while the panel is open, and needs to know how wide it was.
function openPanel(opener) {
  fillPanel(linkFor(opener));
  const page = document.documentElement;
  page.style.setProperty("--scrollbar-width", (window.innerWidth - page.clientWidth) + "px");
  panel.classList.remove("is-closing");
  sheet.style.transform = "";
  panel.showModal();
}


// Play the closing slide first, then really close, which sends focus back to the button.
function closePanel() {
  if (!panel.open || panel.classList.contains("is-closing")) {
    return;
  }
  panel.classList.add("is-closing");
  setTimeout(function () {
    panel.classList.remove("is-closing");
    panel.close();
  }, CLOSE_MS);
}


// Show "Copied ✓" for a moment, then the button's own words again. A second click while it says
// "Copied ✓" is ignored, or the button would remember those words as its own. Each change swaps the
// class, which replays the CSS fade.
function showCopied(button) {
  if (button.dataset.copying === "true") {
    return;
  }
  button.dataset.copying = "true";
  const label = button.querySelector(".button-label");
  const words = label.textContent;
  label.textContent = button.dataset.copiedLabel;
  label.className = "button-label label-copied";
  setTimeout(function () {
    label.textContent = words;
    label.className = "button-label label-back";
    button.dataset.copying = "false";
  }, COPIED_SHOW_MS);
}


// The modern way to copy. navigator.clipboard only exists on https and localhost, so a phone on
// http://<computer's address> doesn't have it. Answers true if the link was copied.
async function copyWithClipboard(link) {
  if (navigator.clipboard === undefined) {
    return false;
  }
  try {
    await navigator.clipboard.writeText(link);
    return true;
  } catch (error) {
    return false;
  }
}


// The older way, which also works on plain http: put the link in a hidden box, select it, and ask the
// browser to copy the selection. The box goes inside the panel, because an open dialog makes
// everything outside it unreachable. Answers true if the link was copied.
function copyWithHiddenBox(link) {
  const box = document.createElement("textarea");
  box.className = "copy-helper";
  box.value = link;
  box.readOnly = true;
  panel.appendChild(box);
  const lastFocused = document.activeElement;
  box.select();
  box.setSelectionRange(0, link.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch (error) {
    copied = false;
  }
  box.remove();
  lastFocused.focus();
  return copied;
}


// The last resort: show the whole link in a small field, already selected, with the template's words.
// A second click reuses the same field.
function showLinkToCopy(button, link) {
  const holder = button.parentElement;
  let area = holder.querySelector(".manual-copy");
  if (area === null) {
    area = document.createElement("div");
    area.className = "manual-copy";
    const words = document.createElement("p");
    words.textContent = button.dataset.manualLabel;
    const box = document.createElement("input");
    box.readOnly = true;
    box.setAttribute("aria-label", button.dataset.manualLabel);
    area.appendChild(words);
    area.appendChild(box);
    holder.appendChild(area);
  }
  const box = area.querySelector("input");
  box.value = link;
  box.focus();
  box.select();
}


// Try each way of copying in turn, and always end with something the person can see.
async function copyLink(button) {
  const link = linkFor(button);
  if (await copyWithClipboard(link) || copyWithHiddenBox(link)) {
    showCopied(button);
  } else {
    showLinkToCopy(button, link);
  }
}


// Open the phone's own share menu. Closing the menu counts as an error named AbortError: that person
// changed their mind, so do nothing. Any other failure falls back to copying.
async function shareWithMoreApps() {
  try {
    await navigator.share({
      title: panel.dataset.subject,
      text: panel.dataset.intro,
      url: linkFor(copyButton),
    });
  } catch (error) {
    if (error.name !== "AbortError") {
      await copyLink(copyButton);
    }
  }
}


// Dragging the sheet down follows the finger. Letting go past DRAG_CLOSE_PX, or with a quick flick,
// closes it. Otherwise it slides back up.
function startDrag(event) {
  dragStartY = event.clientY;
  dragStartTime = event.timeStamp;
  dragDistance = 0;
  event.currentTarget.setPointerCapture(event.pointerId);
  sheet.classList.add("is-dragging");
}


function moveDrag(event) {
  if (dragStartY === null) {
    return;
  }
  dragDistance = Math.max(0, event.clientY - dragStartY);
  sheet.style.transform = "translateY(" + dragDistance + "px)";
}


function endDrag(event) {
  if (dragStartY === null) {
    return;
  }
  const speed = dragDistance / Math.max(1, event.timeStamp - dragStartTime);
  dragStartY = null;
  sheet.classList.remove("is-dragging");
  if (dragDistance > DRAG_CLOSE_PX || speed > DRAG_CLOSE_SPEED) {
    closePanel();
  } else {
    sheet.style.transform = "";
  }
}


// A button that opens the panel. It says "Share" on a phone where the template gave that word.
function startShareButton(button) {
  if (hasTouchScreen() && button.dataset.phoneLabel !== undefined) {
    button.querySelector(".button-label").textContent = button.dataset.phoneLabel;
  }
  button.addEventListener("click", function () {
    openPanel(button);
  });
}


// Everything that closes the panel: the X, Esc, a tap on the dim area around it, or a drag down.
function startPanel() {
  document.getElementById("share-panel-close").addEventListener("click", closePanel);
  panel.addEventListener("cancel", function (event) {
    event.preventDefault();
    closePanel();
  });
  panel.addEventListener("click", function (event) {
    if (event.target === panel) {
      closePanel();
    }
  });
  const grab = panel.querySelector(".share-grab");
  grab.addEventListener("pointerdown", startDrag);
  grab.addEventListener("pointermove", moveDrag);
  grab.addEventListener("pointerup", endDrag);
  grab.addEventListener("pointercancel", endDrag);
  copyButton.addEventListener("click", function () {
    copyLink(copyButton);
  });
  moreButton.addEventListener("click", shareWithMoreApps);
}


startPanel();
for (const button of document.querySelectorAll(".share-button")) {
  startShareButton(button);
}
