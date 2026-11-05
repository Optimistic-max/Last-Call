// The live board on S2 (admin.html) and S3 (board.html). Owner: Samuel (docs/TEAM.md).
// Both pages include templates/board_panel.html, and this file updates that panel:
// 1. Every 10 seconds it fetches /e/<id>/board.json and copies the new values into the page
//    (docs/UI_DESIGN.md sections 7 and 10).
// 2. During LAST_CALL it ticks the countdown in the banner once a second, between fetches (D76).
// 3. It compares each answer with the last one and marks what changed, so the CSS can animate it:
//    who just pledged, who just became counted, and whose share changed (UI_DESIGN.md section 6).
//
// Names are typed by users, so this file writes text with textContent and builds elements with
// createElement, never innerHTML. It does no money math and no money formatting: every amount
// arrives as finished text (UI_DESIGN.md section 7, rule 2). The only thing it formats is the
// countdown time, with the same rules as countdown_text in app.py.

const REFRESH_EVERY_MS = 10000;   // fetch board.json every 10 seconds (UI_DESIGN.md section 7)
const TICK_EVERY_MS = 1000;       // tick the countdown once a second

const board = document.querySelector("section.board");

let fetching = false;   // true while a board.json request is waiting, so requests never pile up
let lastRows = new Map();   // what each person's row said last time: name -> {counted, share}

// The countdown, set from the server's latest seconds_left. textBefore and textAfter are the
// banner's words around the time, so a tick changes only the time.
const countdown = {
  running: false,
  secondsAtStart: 0,
  startedAtMs: 0,
  textBefore: "",
  textAfter: "",
  shownSeconds: null,
};


// Start the board: show the countdown from the page the server drew, then start both timers.
// A page without a board does nothing.
function startBoard() {
  if (board === null) {
    return;
  }
  const banner = board.querySelector(".board-banner");
  lastRows = rowsFromPage();
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
  document.querySelector(".board-goal").textContent = answer.goal_text;
  board.querySelector(".board-held-total").textContent = answer.held_total_text;
  showProgress(answer.progress_percent);
  showRows(answer.rows);
  showPledgeLinks(answer.pledging_open, answer.status);
  setCountdown(answer.status, answer.banner_text, answer.seconds_left);
}


// The progress bar: its value, and the text a browser shows if it can't draw the bar.
function showProgress(percent) {
  const bar = board.querySelector(".board-progress");
  bar.value = percent;
  bar.textContent = percent + "%";
  board.querySelector(".board-bar-fill").style.width = percent + "%";
}


// What the rows the server drew say, so the first refresh has something to compare with.
function rowsFromPage() {
  const rows = new Map();
  for (const item of board.querySelectorAll(".board-rows li")) {
    const share = item.querySelector(".row-share");
    let shareText = "";
    if (share !== null) {
      shareText = share.textContent;
    }
    rows.set(item.querySelector(".row-name").textContent, {
      counted: item.dataset.counted === "true",
      share: shareText,
    });
  }
  return rows;
}


// Remember this answer's rows for the next comparison.
function rememberRows(rows) {
  const remembered = new Map();
  for (const row of rows) {
    remembered.set(row.name, { counted: row.counted, share: row.estimated_share_text });
  }
  return remembered;
}


// Rebuild the list of people, because people can join between refreshes. Rows that changed get
// their marks while they are built, so they all appear in one step: that is what makes two rows
// flash together. The labels come from the template's data- attributes, so they are written once.
function showRows(rows) {
  const list = board.querySelector(".board-rows");
  list.replaceChildren();
  for (const row of rows) {
    const item = makeRow(row, list.dataset);
    markChanges(item, row, lastRows.get(row.name), list.dataset);
    list.appendChild(item);
  }
  board.querySelector(".board-empty").hidden = rows.length > 0;
  lastRows = rememberRows(rows);
}


// Compare one row with what it said last time. before is undefined for a new name.
function markChanges(item, row, before, labels) {
  if (before === undefined) {
    item.classList.add("row-new");
    item.appendChild(makeSpan("row-note", row.name + " " + labels.justPledgedLabel));
    return;
  }
  if (row.counted && !before.counted) {
    item.classList.add("row-just-counted");
  }
  const share = row.estimated_share_text;
  if (before.share !== "" && share !== "" && before.share !== share) {
    markShareChange(item, before.share);
  }
}


// Show the old share struck through next to the new one. Both are the server's finished text: this
// only puts them side by side, so there is no money math here (rule 2).
function markShareChange(item, oldShareText) {
  const share = item.querySelector(".row-share");
  const oldShare = document.createElement("s");
  oldShare.className = "row-old-share";
  oldShare.textContent = oldShareText;
  share.classList.add("row-share-changed");
  share.before(oldShare, " ");
}


// A span with a class and plain text. textContent keeps a name typed by a user as text, never HTML.
function makeSpan(className, text) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  return span;
}


// The word in a row's chip, chosen like the template does: who they are waiting on, else "Counted"
// for a hold the circle rule counts, else the server's status word.
function chipText(row, labels) {
  if (row.waiting_on_text !== "") {
    return row.waiting_on_text;
  }
  if (row.status === "HELD" && row.counted) {
    return labels.countedLabel;
  }
  return row.status_word;
}


// The one plain sentence a screen reader gets: "Ana: Held, max $40.00", plus the share, the waiting
// text and "Counted" when they apply. Every amount is the server's text, joined as it is.
function rowSummary(row, labels) {
  let text = row.name + ": " + row.status_word + ", " + labels.summaryMaxLabel + " " + row.max_text;
  if (row.estimated_share_text !== "") {
    text = text + ", " + labels.shareLabel + " " + row.estimated_share_text;
  }
  if (row.waiting_on_text !== "") {
    text = text + ", " + row.waiting_on_text;
  }
  if (row.status === "HELD" && row.counted) {
    text = text + ", " + labels.countedLabel;
  }
  return text;
}


// The name and the chip, on one line.
function makeRowLine(row, labels) {
  const line = makeSpan("row-line", "");
  line.setAttribute("aria-hidden", "true");
  const name = makeSpan("row-name", row.name);
  name.dir = "auto";
  line.appendChild(name);
  line.appendChild(makeSpan("status row-chip", chipText(row, labels)));
  return line;
}


// The line under the name: the max, and what they would pay during last call.
function makeRowDetails(row, labels) {
  const details = makeSpan("row-details", "");
  details.setAttribute("aria-hidden", "true");
  details.appendChild(makeSpan("row-max", labels.maxLabel + " " + row.max_text));
  if (row.estimated_share_text !== "") {
    const sharePart = makeSpan("row-share-part", labels.shareLabel + " ");
    sharePart.appendChild(makeSpan("row-share", row.estimated_share_text));
    details.appendChild(sharePart);
  }
  return details;
}


// One person's row, with the same markup board_panel.html draws. data-counted is "true" or "false",
// for styling (the circle turns green together).
function makeRow(row, labels) {
  const item = document.createElement("li");
  item.dataset.status = row.status;
  if (row.counted) {
    item.dataset.counted = "true";
  } else {
    item.dataset.counted = "false";
  }
  if (row.waiting_on_text !== "") {
    item.dataset.waiting = "true";
  }
  item.appendChild(makeSpan("row-summary visually-hidden", rowSummary(row, labels)));
  item.appendChild(makeRowLine(row, labels));
  item.appendChild(makeRowDetails(row, labels));
  return item;
}


// Show every Pledge link and the Invite button only while pledging is open. A closed link also loses
// its address. The labels come from the template, and during last call the buttons say "Join last call".
function showPledgeLinks(isOpen, status) {
  for (const link of document.querySelectorAll(".board-pledge")) {
    link.hidden = !isOpen;
    if (isOpen) {
      link.href = link.dataset.pledgeUrl;
    } else {
      link.removeAttribute("href");
    }
    if (link.dataset.pledgeLabel !== undefined) {
      link.textContent = pledgeLinkText(link, status);
    }
  }
  const invite = document.querySelector(".board-invite");
  if (invite !== null) {
    invite.hidden = !isOpen;
  }
}


// The words on a Pledge button for this status.
function pledgeLinkText(link, status) {
  if (status === "LAST_CALL") {
    return link.dataset.lastCallLabel;
  }
  return link.dataset.pledgeLabel;
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
  countdown.shownSeconds = null;
  banner.setAttribute("aria-live", "off");
  showCountdownTime(seconds);
}


// Put the time in the banner in its own span. A new span each second replays the CSS pulse. A second
// that is already showing is skipped, so the pulse stops at 0:00. replaceChildren treats the two
// strings as plain text.
function showCountdownTime(seconds) {
  if (seconds === countdown.shownSeconds) {
    return;
  }
  countdown.shownSeconds = seconds;
  const time = makeSpan("board-countdown", countdownText(seconds));
  board.querySelector(".board-banner").replaceChildren(countdown.textBefore, time, countdown.textAfter);
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
  showCountdownTime(seconds);
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
