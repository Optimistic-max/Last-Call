// The share buttons on S2 (admin.html) and S3 (board.html). Owner: Samuel (docs/TEAM.md).
// Each .share-button shares the link in its data-share-url. That is share_link on S2 and the public
// pledge path on S3. This file never reads the page's own address, because on S2 that address holds
// the treasurer's private admin_token (D18, D59).
//
// A click never fails silently. It ends in the phone's share menu, in "Copied ✓", or, if the browser
// won't copy at all, in a small field showing the link, to press and hold.

const COPIED_SHOW_MS = 2000;   // how long a button says "Copied ✓"


// Phones get the share menu. The touch check is needed because desktop Chrome on Windows has
// navigator.share too, and a laptop user wants a plain copy.
function hasPhoneShareMenu() {
  return navigator.share !== undefined && window.matchMedia("(pointer: coarse)").matches;
}


// The full link for a button. On S3 data-share-url is a path, so it gets this site's origin in front.
function linkFor(button) {
  return new URL(button.dataset.shareUrl, window.location.origin).href;
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
// browser to copy the selection. Answers true if the link was copied.
function copyWithHiddenBox(link) {
  const box = document.createElement("textarea");
  box.className = "copy-helper";
  box.value = link;
  box.readOnly = true;
  document.body.appendChild(box);
  box.select();
  box.setSelectionRange(0, link.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch (error) {
    copied = false;
  }
  box.remove();
  return copied;
}


// The last resort: show the link in a small field under the button, already selected, with the words
// from the template. A second click reuses the same field.
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


// Open the phone's share menu. Closing the menu counts as an error named AbortError: that person
// changed their mind, so do nothing. Any other failure falls back to copying.
async function shareLink(button) {
  try {
    await navigator.share({ url: linkFor(button) });
  } catch (error) {
    if (error.name !== "AbortError") {
      await copyLink(button);
    }
  }
}


// Choose once, when the page opens: the share menu on phones, a plain copy everywhere else.
function startShareButton(button) {
  if (!hasPhoneShareMenu()) {
    button.addEventListener("click", function () {
      copyLink(button);
    });
    return;
  }
  if (button.dataset.phoneLabel !== undefined) {
    button.querySelector(".button-label").textContent = button.dataset.phoneLabel;
  }
  button.addEventListener("click", function () {
    shareLink(button);
  });
}


for (const button of document.querySelectorAll(".share-button")) {
  startShareButton(button);
}
