// The live board on S2 (admin.html) and S3 (board.html). Owner: Samuel (docs/TEAM.md).
// Both pages include templates/board_panel.html, and this file updates that panel:
// 1. Every 10 seconds it fetches /e/<id>/board.json and copies the new values into the page
//    (docs/UI_DESIGN.md sections 7 and 10).
// 2. During LAST_CALL it ticks the countdown in the banner once a second, between fetches (D76).
//
// Names are typed by users, so this file writes text with textContent and builds elements with
// createElement, never innerHTML. It does no money math and no money formatting: every amount
// arrives as finished text (UI_DESIGN.md section 7, rule 2). The only thing it formats is the
// countdown time, with the same rules as countdown_text in app.py.

const REFRESH_EVERY_MS = 10000;   // fetch board.json every 10 seconds (UI_DESIGN.md section 7)
const TICK_EVERY_MS = 1000;       // tick the countdown once a second

const board = document.querySelector("section.board");

let fetching = false;   // true while a board.json request is waiting, so requests never pile up

// The countdown, set from the server's latest seconds_left. textBefore and textAfter are the
// banner's words around the time, so a tick changes only the time.
const countdown = {
  running: false,
  secondsAtStart: 0,
  startedAtMs: 0,
  textBefore: "",
  textAfter: "",
};


// Start the board: show the countdown from the page the server drew, then start both timers.
// A page without a board does nothing.
function startBoard() {
  if (board === null) {
    return;
  }
  const banner = board.querySelector(".board-banner");
  let seconds = null;
  if (board.dataset.secondsLeft !== undefined) {   // the attribute is left out when seconds_left is null
    seconds = Number(board.dataset.secondsLeft);
  }
  setCountdown(board.dataset.status, banner.textContent, seconds);
  setInterval(refreshBoard, REFRESH_EVERY_MS);
  setInterval(tickCountdown, TICK_EVERY_MS);
}


// Ask the server for the latest board. If anything fails (no network, a 503 while the database is
// down, an answer that isn't JSON), keep the last good values on screen: the next tick tries again.
async function refreshBoard() {
  if (fetching) {
    return;
  }
  fetching = true;
  try {
    const response = await fetch("/e/" + board.dataset.eventId + "/board.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("board.json answered " + response.status);
    }
    showBoard(await response.json());
  } catch (error) {
    console.warn("Board refresh failed, trying again in 10 seconds:", error.message);
  } finally {
    fetching = false;
  }
}


// Copy one board.json answer into the page, key by key.
function showBoard(answer) {
  board.dataset.status = answer.status;
  board.querySelector(".board-goal").textContent = answer.goal_text;
  board.querySelector(".board-held-total").textContent = answer.held_total_text;
  showProgress(answer.progress_percent);
  showRows(answer.rows);
  showPledgeLink(answer.pledging_open);
  setCountdown(answer.status, answer.banner_text, answer.seconds_left);
}


// The progress bar: its value, and the text a browser shows if it can't draw the bar.
function showProgress(percent) {
  const bar = board.querySelector(".board-progress");
  bar.value = percent;
  bar.textContent = percent + "%";
}


// Rebuild the list of people, because people can join between refreshes. The labels ("max",
// "share now") come from the template's data- attributes, so they are written in one place only.
function showRows(rows) {
  const list = board.querySelector(".board-rows");
  list.replaceChildren();
  for (const row of rows) {
    list.appendChild(makeRow(row, list.dataset.maxLabel, list.dataset.shareLabel));
  }
}


// One person's row, with the same text the template draws: "Ana: Held, max $40.00", plus
// ", share now $8.21" during last call. Every amount is the server's text, joined as it is.
function makeRow(row, maxLabel, shareLabel) {
  const item = document.createElement("li");
  item.dataset.status = row.status;
  let text = row.name + ": " + row.status_word + ", " + maxLabel + " " + row.max_text;
  if (row.estimated_share_text !== "") {
    text = text + ", " + shareLabel + " " + row.estimated_share_text;
  }
  item.textContent = text;
  return item;
}


// Show the Pledge link only while pledging is open. The link's address and label come from the
// template's data- attributes.
function showPledgeLink(isOpen) {
  const holder = board.querySelector(".board-pledge");
  const link = holder.querySelector("a");
  if (isOpen && link === null) {
    const newLink = document.createElement("a");
    newLink.href = holder.dataset.pledgeUrl;
    newLink.textContent = holder.dataset.pledgeLabel;
    holder.appendChild(newLink);
  }
  if (!isOpen && link !== null) {
    link.remove();
  }
}


// Show the server's banner, then start the countdown if this is LAST_CALL, or stop it otherwise.
// While it ticks, aria-live="off" stops screen readers reading the time out every second; removing
// it puts the banner back to role="status", so the next status change is read out.
function setCountdown(status, bannerText, seconds) {
  const banner = board.querySelector(".board-banner");
  banner.textContent = bannerText;
  countdown.running = false;
  if (status !== "LAST_CALL" || seconds === null) {
    banner.removeAttribute("aria-live");
    return;
  }
  // Find the server's time (like "4:59") in the banner and keep the words on each side of it.
  const timeText = countdownText(seconds);
  const where = bannerText.indexOf(timeText);
  if (where === -1) {
    banner.removeAttribute("aria-live");   // the time isn't there, so show banner_text as it came
    return;
  }
  countdown.textBefore = bannerText.slice(0, where);
  countdown.textAfter = bannerText.slice(where + timeText.length);
  countdown.secondsAtStart = seconds;
  countdown.startedAtMs = Date.now();
  countdown.running = true;
  banner.setAttribute("aria-live", "off");
}


// Once a second during LAST_CALL, rewrite only the time in the banner. The seconds left are worked
// out from the clock, not by taking 1 away each tick, because phones slow timers down in background
// tabs. It stops at 0:00 and waits: only the server decides that last call is over.
function tickCountdown() {
  if (!countdown.running) {
    return;
  }
  const secondsPassed = Math.floor((Date.now() - countdown.startedAtMs) / 1000);
  let seconds = countdown.secondsAtStart - secondsPassed;
  if (seconds < 0) {
    seconds = 0;
  }
  const banner = board.querySelector(".board-banner");
  banner.textContent = countdown.textBefore + countdownText(seconds) + countdown.textAfter;
}


// "4:59", or "1:02:03" from one hour up. The same rules as countdown_text in app.py, so the banner
// doesn't jump when the next board.json arrives.
function countdownText(seconds) {
  const secondsPart = twoDigits(seconds % 60);
  if (seconds < 3600) {
    return Math.floor(seconds / 60) + ":" + secondsPart;
  }
  const hours = Math.floor(seconds / 3600);
  const minutesPart = twoDigits(Math.floor((seconds % 3600) / 60));
  return hours + ":" + minutesPart + ":" + secondsPart;
}


// 7 becomes "07" and 42 stays "42", like Python's %02d.
function twoDigits(number) {
  if (number < 10) {
    return "0" + number;
  }
  return String(number);
}


startBoard();
