// The ribbed black cards follow the pointer (Samuel, UI only).
// When the mouse moves over a black card, the ribbed picture behind it slides up to 14px the other
// way and a faint light follows the pointer, like looking through fluted glass while moving your
// head. style.css does the moving; this file only tells it where the pointer is.
// It runs only with a mouse or trackpad, never on touch, and never when reduced motion is on.
// One listener on the whole page (event delegation), so cards that board.js updates keep working.

var RIBS_CARDS = ".light-card, .board[data-status='LAST_CALL'] .status-card";
var RIBS_MAX_SHIFT_PX = 28;  // the full range, so the picture moves at most 14px either way

var finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

// Moves the picture and the light to match where the pointer is inside the card.
function followPointer(event) {
  if (!finePointer.matches || reducedMotion.matches) {
    return;
  }
  var card = event.target.closest(RIBS_CARDS);
  if (!card) {
    return;
  }
  var box = card.getBoundingClientRect();
  var across = (event.clientX - box.left) / box.width;   // 0 at the left edge, 1 at the right
  var down = (event.clientY - box.top) / box.height;     // 0 at the top, 1 at the bottom
  card.style.setProperty("--ribs-x", ((0.5 - across) * RIBS_MAX_SHIFT_PX).toFixed(1) + "px");
  card.style.setProperty("--ribs-mx", (across * 100).toFixed(1) + "%");
  card.style.setProperty("--ribs-my", (down * 100).toFixed(1) + "%");
}

// Slides the picture back to the middle when the pointer leaves the card.
function settleCard(event) {
  var card = event.target.closest(RIBS_CARDS);
  if (card && !card.contains(event.relatedTarget)) {
    card.style.setProperty("--ribs-x", "0px");
  }
}

document.addEventListener("pointermove", followPointer);
document.addEventListener("pointerout", settleCard);
