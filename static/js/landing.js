// The landing page at the top of S1 (create_event.html). Owner: Samuel (docs/TEAM.md).
// 1. A refused form is far down the page, so it is brought into view with its field shaken.
// 2. The "How it works" cards rise in once, as they scroll into view.
// 3. The scroll zoom is CSS (animation-timeline). Browsers without it get a small fallback here: one
//    number from 0 to 1 that the CSS uses for transform and opacity.
// With reduced motion on, the cards simply stay in place and nothing moves with the scroll.

// 4. Liquid glass on the sticky header (D99) only in Chrome-family browsers. navigator.userAgentData
//    exists only in those, and its brands list names "Chromium". Safari and Firefox can't use an SVG
//    filter in backdrop-filter, so they keep the plain frosted glass.
function markLiquidGlass() {
  const brands = navigator.userAgentData ? navigator.userAgentData.brands : [];
  const isChromium = brands.some(function (entry) { return entry.brand === "Chromium"; });
  if (isChromium) {
    document.documentElement.classList.add("liquid-glass");
  }
}

markLiquidGlass();

const SCROLL_ZOOM_PX = 600;   // the zoom plays over the first 600px of scrolling

const wantsMotion = window.matchMedia("(prefers-reduced-motion: no-preference)").matches;

let scrollProgress = 0;
let frameWaiting = false;


// The server refused the form and sent the whole page back, so the visitor would land at the top
// and miss the message. "instant" skips the smooth scroll, which would feel like a page loading twice.
function showRefusedForm() {
  const field = document.querySelector('#create [aria-invalid="true"]');
  if (field === null) {
    return;
  }
  document.getElementById("create").scrollIntoView({ behavior: "instant", block: "start" });
  field.classList.add("shake");
}


// Hide the cards just below their place, then let each one rise the first time it is on screen.
function startRiseIn() {
  const cards = document.querySelectorAll(".how-step");
  const watcher = new IntersectionObserver(function (entries) {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add("risen");
        watcher.unobserve(entry.target);
      }
    }
  }, { threshold: 0.2 });
  cards.forEach(function (card, position) {
    card.style.setProperty("--rise-order", position);
    card.classList.add("will-rise");
    watcher.observe(card);
  });
}


// Write the number once per frame. Only the CSS rules under .scroll-fallback read it.
function writeScrollProgress() {
  frameWaiting = false;
  document.documentElement.style.setProperty("--progress", scrollProgress);
}


// Read the scroll position here and wait for the next frame to write, so scrolling stays smooth.
function noteScroll() {
  scrollProgress = Math.min(window.scrollY / SCROLL_ZOOM_PX, 1);
  if (!frameWaiting) {
    frameWaiting = true;
    requestAnimationFrame(writeScrollProgress);
  }
}


// Only for browsers without CSS scroll timelines.
function startScrollFallback() {
  document.documentElement.classList.add("scroll-fallback");
  window.addEventListener("scroll", noteScroll, { passive: true });
  noteScroll();
}


function startLanding() {
  showRefusedForm();
  if (!wantsMotion) {
    return;
  }
  startRiseIn();
  if (!CSS.supports("animation-timeline: scroll()")) {
    startScrollFallback();
  }
}


startLanding();
