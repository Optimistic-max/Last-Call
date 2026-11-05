// The share button on S2 (admin.html). Owner: Samuel (docs/TEAM.md).
// It only ever shares #share-link, the friends' pledge page. It never reads the page's own address,
// because that address holds the treasurer's private admin_token (D18, D59).

const COPIED_SHOW_MS = 2000;   // how long the button says "Copied ✓"

const shareInput = document.getElementById("share-link");
const shareButton = document.getElementById("copy-link-button");
const copyLabel = shareButton.textContent;


// Phones get the share menu. The touch check is needed because desktop Chrome on Windows has
// navigator.share too, and a treasurer on a laptop wants a plain copy.
function hasPhoneShareMenu() {
  return navigator.share !== undefined && window.matchMedia("(pointer: coarse)").matches;
}


// Copy the link. navigator.clipboard is missing on a plain http page, so if the copy fails, select
// the text instead, and the treasurer can copy it by hand.
async function copyLink() {
  try {
    await navigator.clipboard.writeText(shareInput.value);
  } catch (error) {
    shareInput.select();
    return;
  }
  shareButton.textContent = shareButton.dataset.copiedLabel;
  setTimeout(function () {
    shareButton.textContent = copyLabel;
  }, COPIED_SHOW_MS);
}


// Open the phone's share menu. Closing the menu counts as an error named AbortError: that person
// changed their mind, so do nothing. Any other failure falls back to copying.
async function shareLink() {
  try {
    await navigator.share({ url: shareInput.value });
  } catch (error) {
    if (error.name !== "AbortError") {
      await copyLink();
    }
  }
}


// Choose once, when the page opens: the share menu on phones, a plain copy everywhere else.
function startShareButton() {
  if (hasPhoneShareMenu()) {
    shareButton.textContent = shareButton.dataset.shareLabel;
    shareButton.addEventListener("click", shareLink);
  } else {
    shareButton.addEventListener("click", copyLink);
  }
}


startShareButton();
