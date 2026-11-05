// The live board on S2 (admin.html) and S3 (board.html). Owner: Samuel (docs/TEAM.md).
// Both pages include templates/board_panel.html, and this file updates that panel:
// 1. Every 10 seconds it fetches /e/<id>/board.json and copies the new values into the page
//    (docs/UI_DESIGN.md sections 7 and 10).
// 2. While pledging is open it ticks the countdown card once a second, between fetches (D76).
//    During LAST_CALL it also ticks the time inside the banner, so the two never disagree.
// 3. It compares each answer with the last one and marks what changed, so the CSS can animate it:
//    who just pledged, who just became counted, and whose share changed (UI_DESIGN.md section 6).
//
// Names are typed by users, so this file writes text with textContent and builds elements with
// createElement, never innerHTML. It does no money math and no money formatting: every amount
// arrives as finished text (UI_DESIGN.md section 7, rule 2). It only counts rows and formats the
// countdown time, with the same rules as countdown_text in app.py.

const REFRESH_EVERY_MS = 10000;   // fetch board.json every 10 seconds (UI_DESIGN.md section 7)
const TICK_EVERY_MS = 1000;       // tick the countdown once a second
const INVITE_NUDGE_MS = 8000;     // an empty board nudges Invite once, this long after it loads

const board = document.querySelector("section.board");

let fetching = false;   // true while a board.json request is waiting, so requests never pile up
let lastRows = new Map();   // what each person's row said last time: name -> {counted, share}

// The countdown, set from the server's latest seconds_left. textBefore and textAfter are the
// banner's words around the time, so a tick changes only the time.
const countdown = {
  running: false,
  secondsAtStart: 0,
  startedAtMs: 0,
  shownSeconds: null,
  inBanner: false,
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
  lastRows = rowsFromPage();
  let seconds = null;
  if (board.dataset.secondsLeft !== undefined) {   // the attribute is left out when seconds_left is null
    seconds = Number(board.dataset.secondsLeft);
  }
  setCountdown(board.dataset.status, banner.textContent, seconds);
  setInterval(refreshBoard, REFRESH_EVERY_MS);
  setInterval(tickCountdown, TICK_EVERY_MS);
  setTimeout(nudgeInvite, INVITE_NUDGE_MS);
}


// A gentle wiggle on Invite, only if nobody has pledged yet. It runs once per visit.
function nudgeInvite() {
  if (lastRows.size > 0) {
    return;
  }
  for (const invite of document.querySelectorAll(".board-invite")) {
    if (!invite.hidden) {
      invite.classList.add("wiggle");
    }
  }
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
  showProgress(answer.progress_percent);
  showStats(answer);
  showRows(answer.rows);
  showPledgeLinks(answer.pledging_open, answer.status);
  setCountdown(answer.status, answer.banner_text, answer.seconds_left);
}


// The half ring. The arc is 100 units long, so what is left to draw is 100 minus the percent.
// The hidden <progress> and the ring's aria-valuenow give screen readers the same number.
function showProgress(percent) {
  const bar = board.querySelector(".board-progress");
  const oldPercent = bar.value;
  bar.value = percent;
  bar.textContent = percent + "%";
  const arc = board.querySelector(".ring-counted");
  arc.style.strokeDashoffset = 100 - percent;
  arc.classList.toggle("ring-empty", percent === 0);
  board.querySelector(".board-ring").setAttribute("aria-valuenow", percent);
  if (percent !== oldPercent) {
    swapText(board.querySelector(".ring-percent"), oldPercent + "%", percent + "%");
  }
}


// Put the old and the new words in an element, so the CSS can move one out as the other comes in.
// Both are finished text, so nothing here counts or calculates. The old words end up invisible.
function swapText(element, oldText, newText) {
  element.textContent = "";
  element.classList.add("text-swap");
  element.appendChild(makeSpan("text-new", newText));
  element.appendChild(makeSpan("text-old", oldText));
}


// The caption under the held total. It is empty when it wouldn't be true: before pledging opens,
// and after a missed goal, when "Cancelling holds…" may still be running (D45).
function heldCaptionText(status) {
  if (status === "OPEN" || status === "LAST_CALL") {
    return "PayPal is holding this. Nobody is charged yet.";
  }
  if (status === "SETTLED") {
    return "Charged once.";
  }
  return "";
}


// "1 person" or "3 people". Only a count of rows, so this is not money.
function peopleText(count) {
  if (count === 1) {
    return "1 person";
  }
  return count + " people";
}


// The four stat cards. counted_total_text and goal_amount_text are new keys Emmanuel may add: when
// they arrive they are used as they are. Until then these two show a count and a percent.
function showStats(answer) {
  const countedRows = answer.rows.filter(function (row) {
    return row.counted;
  });
  const waitingRows = answer.rows.filter(function (row) {
    return row.waiting_on_text !== "";
  });
  board.querySelector(".board-held-total").textContent = answer.held_total_text;
  board.querySelector(".board-held-caption").textContent = heldCaptionText(answer.status);
  board.querySelector(".board-counted-total").textContent =
    answer.counted_total_text || peopleText(countedRows.length);
  board.querySelector(".board-people").textContent = answer.rows.length;
  board.querySelector(".board-waiting-count").textContent = waitingRows.length + " waiting on someone";
  board.querySelector(".board-goal-amount").textContent =
    answer.goal_amount_text || answer.progress_percent + "%";
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
// change together. The labels come from the template's data- attributes, so they are written once.
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
    item.querySelector(".row-details").appendChild(makeSpan("just-pledged", labels.justPledgedLabel));
    return;
  }
  if (row.counted && !before.counted) {
    item.classList.add("row-just-counted");
  }
  const share = row.estimated_share_text;
  if (before.share !== "" && share !== "" && before.share !== share) {
    swapText(item.querySelector(".row-share"), before.share, share);
  }
}


// A span with a class and plain text. textContent keeps a name typed by a user as text, never HTML.
function makeSpan(className, text) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  return span;
}


// The first two letters of a name, like the template. Array.from keeps an emoji in one piece.
function avatarText(name) {
  return Array.from(name).slice(0, 2).join("").toUpperCase();
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


// The small line under the name: the max, then the share, then who they are waiting on.
function makeRowDetails(row, labels) {
  const details = makeSpan("row-details", "");
  details.appendChild(makeSpan("row-max", labels.maxLabel + " " + row.max_text));
  if (row.estimated_share_text !== "") {
    const sharePart = makeSpan("row-share-part", labels.shareLabel + " ");
    sharePart.appendChild(makeSpan("row-share", row.estimated_share_text));
    details.appendChild(sharePart);
  }
  if (row.waiting_on_text !== "") {
    details.appendChild(makeSpan("row-waiting", row.waiting_on_text));
  }
  return details;
}


// The name with the small line under it.
function makeRowText(row, labels) {
  const text = makeSpan("row-text", "");
  text.setAttribute("aria-hidden", "true");
  const name = makeSpan("row-name", row.name);
  name.dir = "auto";
  text.appendChild(name);
  text.appendChild(makeRowDetails(row, labels));
  return text;
}


// One person's row, with the same markup board_panel.html draws. data-counted is "true" or "false",
// for styling (the circle turns black together).
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
  const avatar = makeSpan("avatar row-avatar", avatarText(row.name));
  avatar.setAttribute("aria-hidden", "true");
  item.appendChild(avatar);
  item.appendChild(makeRowText(row, labels));
  const chip = makeSpan("status row-chip", chipText(row, labels));
  chip.setAttribute("aria-hidden", "true");
  item.appendChild(chip);
  return item;
}


// Show every Pledge link and Invite button only while pledging is open. A closed link also loses
// its address. The labels come from the template, and during last call the buttons say "Join last call".
// Before pledging starts, a short line says Invite is coming. After it ends, that would be untrue.
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
  for (const invite of document.querySelectorAll(".board-invite")) {
    invite.hidden = !isOpen;
  }
  board.querySelector(".invite-hint").hidden = status !== "DRAFT";
}


// The words on a Pledge button for this status.
function pledgeLinkText(link, status) {
  if (status === "LAST_CALL") {
    return link.dataset.lastCallLabel;
  }
  return link.dataset.pledgeLabel;
}


// The countdown card's title: "Last call" during last call, otherwise "Time left".
function showTimeTitle(status) {
  const card = board.querySelector(".countdown-card");
  const title = board.querySelector(".board-time-title");
  if (status === "LAST_CALL") {
    title.textContent = card.dataset.lastCallTitle;
  } else {
    title.textContent = card.dataset.openTitle;
  }
}


// Show the server's banner, then start the countdown from its latest seconds_left, or show "Closed".
function setCountdown(status, bannerText, seconds) {
  const banner = board.querySelector(".board-banner");
  banner.textContent = bannerText;
  banner.removeAttribute("aria-live");
  showTimeTitle(status);
  countdown.running = false;
  countdown.inBanner = false;
  if ((status !== "OPEN" && status !== "LAST_CALL") || seconds === null) {
    board.querySelector(".board-time").textContent = board.querySelector(".countdown-card").dataset.closedText;
    return;
  }
  if (status === "LAST_CALL") {
    findTimeInBanner(bannerText, seconds);
  }
  countdown.secondsAtStart = seconds;
  countdown.startedAtMs = Date.now();
  countdown.running = true;
  countdown.shownSeconds = null;
  showCountdownTime(seconds);
}


// Find the server's time (like "4:59") in the banner and keep the words on each side of it. If it
// isn't there, the banner stays as it came. While it ticks, aria-live="off" stops screen readers
// reading the time out every second. setCountdown removes that again at each refresh, which puts
// the banner back to role="status", so the next status change is read out.
function findTimeInBanner(bannerText, seconds) {
  const timeText = countdownText(seconds);
  const where = bannerText.indexOf(timeText);
  if (where === -1) {
    return;
  }
  countdown.textBefore = bannerText.slice(0, where);
  countdown.textAfter = bannerText.slice(where + timeText.length);
  countdown.inBanner = true;
  board.querySelector(".board-banner").setAttribute("aria-live", "off");
}


// Put the time on the card, and in the banner during last call. A second that is already showing
// is skipped.
function showCountdownTime(seconds) {
  if (seconds === countdown.shownSeconds) {
    return;
  }
  countdown.shownSeconds = seconds;
  const timeText = countdownText(seconds);
  board.querySelector(".board-time").textContent = timeText;
  if (countdown.inBanner) {
    board.querySelector(".board-banner").textContent = countdown.textBefore + timeText + countdown.textAfter;
  }
}


// Once a second, work out the seconds left from the clock, not by taking 1 away each tick, because
// phones slow timers down in background tabs. It stops at 0:00 and waits: only the server decides
// that pledging is over.
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


// "4:59", or "47:59:12" from one hour up. The same rules as countdown_text in app.py, so the banner
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
