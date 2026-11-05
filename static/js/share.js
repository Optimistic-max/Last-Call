// The share buttons on S2 (admin.html) and S3 (board.html). Owner: Samuel (docs/TEAM.md).
// Each .share-button shares the link in its data-share-url. That is share_link on S2 and the public
// pledge path on S3. This file never reads the page's own address, because on S2 that address holds
// the treasurer's private admin_token (D18, D59).

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


// Copy the link. navigator.clipboard is missing on a plain http page, so if the copy fails on S2,
// select the link in its box, and the treasurer can copy it by hand.
async function copyLink(button) {
  try {
    await navigator.clipboard.writeText(linkFor(button));
  } catch (error) {
    const box = document.getElementById("share-link");
    if (box !== null) {
      box.select();
    }
    return;
  }
  showCopied(button);
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
