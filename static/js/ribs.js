// The ribbed picture moves two ways (Samuel, UI only, D103).
// 1. It drifts on its own: a slow CSS loop on the outer layer (.ribs-drift) of every ribbed card and the
//    landing hero. This file pauses that loop while a card is off screen, so the browser does no work for
//    a picture nobody can see.
// 2. It follows the pointer: when the mouse moves over a ribbed card, the inner layer (.ribs-follow)
//    slides the other way and a faint light follows the pointer, like looking through fluted glass while
//    moving your head. style.css does the moving; this file only tells it where the pointer is.
// Each layer owns one transform, so the drift and the pointer add up instead of cancelling each other.
// The pointer part runs only with a mouse or trackpad, never on touch, and never when reduced motion is
// on (the CSS also switches the drift off then).
// One listener on the whole page (event delegation), so cards that board.js updates keep working.

var RIBS_CARDS = ".ribbed, .board[data-status='LAST_CALL'] .status-card, .hero-ribs";
var RIBS_MAX_SHIFT_PX = 28;  // the full range: at most 14px either way (the CSS scales it per card)

var finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");


// Gives this card's own picture layers the shift. Setting it on the small layer, not on the card, means
// the browser restyles one layer instead of everything inside the card. A layer that belongs to a ribbed
// card nested inside this one is left alone.
function shiftPicture(card, shift) {
  for (var layer of card.querySelectorAll(".ribs-follow")) {
    if (layer.closest(RIBS_CARDS) === card) {
      layer.style.setProperty("--ribs-x", shift);
    }
  }
}


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
  shiftPicture(card, ((0.5 - across) * RIBS_MAX_SHIFT_PX).toFixed(1) + "px");
  card.style.setProperty("--ribs-mx", (across * 100).toFixed(1) + "%");
  card.style.setProperty("--ribs-my", (down * 100).toFixed(1) + "%");
}


// Slides the picture back to the middle when the pointer leaves the card.
function settleCard(event) {
  var card = event.target.closest(RIBS_CARDS);
  if (card && !card.contains(event.relatedTarget)) {
    shiftPicture(card, "0px");
  }
}


// Pauses the drift of every picture that is off screen, and starts it again when it scrolls back in.
function pauseOffscreenDrift() {
  if (!("IntersectionObserver" in window)) {
    return;
  }
  var watcher = new IntersectionObserver(function (entries) {
    for (var entry of entries) {
      entry.target.classList.toggle("ribs-paused", !entry.isIntersecting);
    }
  });
  for (var layer of document.querySelectorAll(".ribs-drift")) {
    watcher.observe(layer);
  }
}


document.addEventListener("pointermove", followPointer);
document.addEventListener("pointerout", settleCard);
pauseOffscreenDrift();
