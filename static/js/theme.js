// The theme switch (D103). Owner: Samuel (docs/TEAM.md). Dark is the default; light is a choice, and the
// choice is remembered in localStorage. A tiny script in base.html's <head> sets data-theme on <html>
// before the page paints, so there is never a flash of the wrong theme. This file keeps every switch on
// the page, the attribute and the browser's bar colour in step when someone flips a switch.

// Remember the choice. A private window or blocked storage can refuse, and that is fine: the page still
// switches, it just won't remember.
function saveTheme(theme) {
  try {
    localStorage.setItem("theme", theme);
  } catch (error) {
    // Nothing to do: the theme still changes for this visit.
  }
}


// The browser's bar takes the colour of the top of the page, the sandbox banner (--banner).
function showBarColour() {
  const colour = getComputedStyle(document.documentElement).getPropertyValue("--banner").trim();
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta && colour) {
    meta.content = colour;
  }
}


// Put every switch in the right position: checked means dark.
function syncSwitches(theme) {
  for (const input of document.querySelectorAll(".theme-input")) {
    input.checked = theme === "dark";
  }
}


function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  syncSwitches(theme);
  showBarColour();
  saveTheme(theme);
}


function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}


syncSwitches(currentTheme());
showBarColour();
for (const input of document.querySelectorAll(".theme-input")) {
  input.addEventListener("change", function () {
    applyTheme(input.checked ? "dark" : "light");
  });
}
