// The live board on S2 (admin.html) and S3 (board.html). Owner: Samuel (docs/TEAM.md).
// Both pages include templates/board_panel.html, and this file updates that panel:
// 1. Every 10 seconds it fetches /e/<id>/board.json and copies the new values into the page
//    (docs/UI_DESIGN.md sections 7 and 10).
// 2. While pledging is open it ticks the countdown card once a second, between fetches (D76).
//    It also ticks the time inside the OPEN and LAST_CALL banners, so the two never disagree.
// 3. It compares each answer with the last one and marks what changed, so the CSS can animate it:
//    who just pledged, who just became counted, and whose share changed (UI_DESIGN.md section 6).
// 4. It keeps the wallet at the top up to date (D100): the people row, the goal pill and the two bars.
//    Every wallet function checks the wallet is there first, so a page without one still works.
//
// Names are typed by users, so this file writes text with textContent and builds elements with
// createElement, never innerHTML. It does no money math and no money formatting: every amount
// arrives as finished text (UI_DESIGN.md section 7, rule 2). It only counts rows and formats the
// countdown time, with the same rules as countdown_text in app.py.

const REFRESH_EVERY_MS = 10000;   // fetch board.json every 10 seconds (UI_DESIGN.md section 7)
const TICK_EVERY_MS = 1000;       // tick the countdown once a second
const INVITE_NUDGE_MS = 8000;     // an empty board nudges Invite once, this long after it loads
const WALLET_FACES = 4;           // faces in the wallet's people row before "+N" (same as the template)

const board = document.querySelector("section.board");

let fetching = false;   // true while a board.json request is waiting, so requests never pile up
let liveSlots = [];     // the island's live slot, in the phone's top bar and in the laptop island (D103)
const liveState = { status: "", timeText: "", everyoneIn: false, kind: "" };
let lastRows = new Map();   // what each person's row said last time: name -> {counted, share}

// The countdown, set from the server's latest seconds_left. textBefore and textAfter are the
// banner's words around the time, so a tick changes only the time.
const countdown = {
  status: "",
  running: false,
  secondsAtStart: 0,
  startedAtMs: 0,
  shownSeconds: null,
  inBanner: false,
  textBefore: "",
  textAfter: "",
  windowSeconds: null,   // how long the whole window is, if the server says (window_seconds), for the Time bar
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
  // The test page has no document.querySelectorAll; a real page always does.
  if (typeof document.querySelectorAll === "function") {
    liveSlots = Array.from(document.querySelectorAll(".live-slot"));
  }
  liveState.everyoneIn = lastRows.size > 0 && Array.from(lastRows.values()).every(function (row) {
    return row.counted;
  });
  const wallet = board.querySelector(".wallet");
  if (wallet && wallet.dataset.windowSeconds !== undefined) {
    countdown.windowSeconds = Number(wallet.dataset.windowSeconds);
  }
  setCountdown(board.dataset.status, banner.textContent, seconds);
  const groups = board.querySelector(".board-rows");
  if (groups) {
    groups.addEventListener("click", toggleRow);
  }
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
  showWallet(answer);   // before showRows, which forgets who was here last time
  showRows(answer);
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


// D97: the caption under the charged total, after the lock. Server text only (textContent, never HTML).
function chargedCaptionText(answer) {
  if (answer.refunded_total_text) {
    return "Refunded " + answer.refunded_total_text;
  }
  return "Charged once.";
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
  // D97: from the lock on the first card says Charged and shows charged_total_text; before that, Held so far.
  // Bare version for Samuel to restyle: keep the choice, and use textContent only.
  const title = board.querySelector(".board-held-title");
  const total = board.querySelector(".board-held-total");
  const oldTotal = total.textContent;
  if (answer.charged_total_text) {
    title.textContent = "Charged";
    total.textContent = answer.charged_total_text;
    board.querySelector(".board-held-caption").textContent = chargedCaptionText(answer);
  } else {
    title.textContent = "Held so far";
    total.textContent = answer.held_total_text;
    board.querySelector(".board-held-caption").textContent = heldCaptionText(answer.status);
  }
  showWalletAmount(oldTotal, total.textContent);
  board.querySelector(".board-counted-total").textContent =
    answer.counted_total_text || peopleText(countedRows.length);
  board.querySelector(".board-people").textContent = answer.rows.length;
  board.querySelector(".board-waiting-count").textContent = waitingRows.length + " waiting on someone";
  board.querySelector(".board-goal-amount").textContent =
    answer.goal_amount_text || answer.progress_percent + "%";
}


// ---------- The wallet at the top of the board (D100) ----------

// Copy the new answer into the wallet. A page without a wallet (and the test page) skips all of it.
function showWallet(answer) {
  const wallet = board.querySelector(".wallet");
  if (!wallet) {
    return;
  }
  showGoalPill(wallet, answer.goal_amount_text);
  showCountedBar(wallet, answer);
  showWalletPeople(wallet, answer.rows);
  if (answer.window_seconds) {
    countdown.windowSeconds = answer.window_seconds;
  }
}


// "Goal $310.01" under the amount, only when the server sends goal_amount_text (finished text).
function showGoalPill(wallet, goalAmountText) {
  const pill = wallet.querySelector(".wallet-goal");
  pill.hidden = !goalAmountText;
  if (goalAmountText) {
    pill.textContent = "Goal " + goalAmountText;
  }
}


// The Counted bar is the server's progress_percent, and its words are the server's money text joined
// as it is. Dividing the percent by 100 only turns it into a fraction for the CSS, so this is not money.
function showCountedBar(wallet, answer) {
  wallet.querySelector(".bar-counted").style.setProperty("--bar", answer.progress_percent / 100);
  wallet.querySelector(".bar-counted-text").textContent = countedBarText(answer);
}


// "$15.01 of $310.01" when both texts arrive, else "39% of the goal", like the template.
function countedBarText(answer) {
  if (answer.counted_total_text && answer.goal_amount_text) {
    return answer.counted_total_text + " of " + answer.goal_amount_text;
  }
  return answer.progress_percent + "% of the goal";
}


// A counted hold, or a charge that went through. A failed charge is "counted" on the server (D79), but
// it must never get the amber ring or the words "is counted".
function hasCountedRing(row) {
  return row.counted && row.status !== "FAILED";
}


// The class of one face: a thin amber ring when counted, dimmed while waiting on someone.
function walletFaceClass(row) {
  if (hasCountedRing(row)) {
    return "wallet-avatar is-counted";
  }
  if (row.waiting_on_text !== "") {
    return "wallet-avatar is-waiting";
  }
  return "wallet-avatar";
}


// The first few faces and "+N" for the rest. A name that wasn't here last time pops in. lastRows still
// holds the previous answer here, because showRows runs after this.
function showWalletPeople(wallet, rows) {
  const faces = wallet.querySelector(".wallet-avatars");
  faces.replaceChildren();
  for (const row of rows.slice(0, WALLET_FACES)) {
    const face = makeSpan(walletFaceClass(row), avatarText(row.name));
    face.setAttribute("aria-hidden", "true");
    if (!lastRows.has(row.name)) {
      face.classList.add("avatar-new");
    }
    faces.appendChild(face);
  }
  if (rows.length > WALLET_FACES) {
    const more = makeSpan("wallet-more", "+" + (rows.length - WALLET_FACES));
    more.setAttribute("aria-hidden", "true");
    faces.appendChild(more);
  }
  faces.setAttribute("aria-label", "Who's in: " + peopleText(rows.length));
  faces.hidden = rows.length === 0;
}


// When the amount changes, replay the crossfade on its line. "USD" shows only beside an amount: after the
// lock the text can be "Total being checked". Looking at the first character is not money math.
function showWalletAmount(oldText, newText) {
  const line = board.querySelector(".wallet-amount");
  if (!line) {
    return;
  }
  line.querySelector(".wallet-unit").hidden = !newText.startsWith("$");
  if (oldText !== newText) {
    line.classList.remove("amount-changed");
    void line.offsetWidth;   // lets the browser see the class go, so the animation plays again
    line.classList.add("amount-changed");
  }
}


// The Time bar and its words follow the countdown. The bar only appears when the server says how long
// the window is (window_seconds), because guessing the length here would duplicate config.py.
function showWalletTime(seconds, timeText) {
  const words = board.querySelector(".bar-time-text");
  if (!words) {
    return;
  }
  words.textContent = timeText;
  const bar = board.querySelector(".bar-time");
  if (bar && countdown.windowSeconds && seconds !== null) {
    bar.style.setProperty("--bar", Math.min(1, seconds / countdown.windowSeconds));
  }
}


// ---------- Who's in (D102) ----------

// The groups, in the order the card shows them. The headings are also in board_panel.html. They live here
// too because "Waiting on someone" may only be on the page while someone waits (the tests check it), so
// it can't wait in a data- attribute.
const GROUP_ORDER = ["counted", "waiting", "pledged", "charged", "refunded", "attention", "out"];
const GROUP_TITLES = {
  counted: "Counted", waiting: "Waiting on someone", pledged: "Pledged", charged: "Charged",
  refunded: "Refunded", attention: "Needs attention", out: "Not in",
};
const CHIP_ICONS = {
  counted: "check", waiting: "clock", pledged: "hand-coins", charged: "check",
  refunded: "wallet", attention: "x", out: "x",
};
const AFTER_LOCK = ["LOCKING", "CHARGING", "SETTLED", "NEEDS_ATTENTION", "REFUNDING", "REFUNDED"];
const CLUSTER_FACES = 11;          // faces in the summary before "+N"
const SLIDE_MS = 350;              // how long a row takes to slide to its new place
const SLIDE_EASE = "cubic-bezier(0.23, 1, 0.32, 1)";
const SVG_NS = "http://www.w3.org/2000/svg";

let expandedNames = new Set();     // rows someone opened, kept open across refreshes
let rowIdCount = 0;                // gives each dependency panel its own id


// Which group a row belongs in, the same choice as group_of in board_panel.html.
function groupOf(row) {
  if (row.status === "CHARGED") {
    return "charged";
  }
  if (row.status === "REFUNDED") {
    return "refunded";
  }
  if (row.status === "FAILED") {
    return "attention";
  }
  if (row.status === "DECLINED") {
    return "out";
  }
  if (row.counted) {
    return "counted";
  }
  if (row.waiting_on_text !== "") {
    return "waiting";
  }
  if (row.status === "PENDING_PAY" || row.status === "HELD") {
    return "pledged";
  }
  return "out";
}


// "Jay", "Jay and Kim", "Jay, Kim and Mo". Names are the server's text, joined as they are.
function namesText(names) {
  if (names.length === 1) {
    return names[0];
  }
  return names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
}


// The people this person needs (D96), and how many people still wait on them.
function linksFrom(links, name) {
  return (links || []).filter(function (link) {
    return link.from === name;
  });
}

function waitingOnCount(links, name) {
  return (links || []).filter(function (link) {
    return link.to === name && !link.met;
  }).length;
}


// One icon from the sheet in icons.html, made like the icon macro in macros.html.
function makeIcon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", "#i-" + name);
  svg.appendChild(use);
  return svg;
}


// What the rows the server drew say, so the first refresh has something to compare with.
function rowsFromPage() {
  const rows = new Map();
  for (const item of board.querySelectorAll(".row-list > li")) {
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


// Rebuild the groups, because people can join and move between refreshes. Everything is built first and
// put on the page in one step, so rows that change together change at the same moment. Rows that moved
// then slide from where they were (slideRows).
function showRows(answer) {
  const groups = board.querySelector(".board-rows");
  const before = rowPlaces(groups);
  const page = document.createDocumentFragment();
  for (const key of GROUP_ORDER) {
    const members = answer.rows.filter(function (row) {
      return groupOf(row) === key;
    });
    if (members.length > 0) {
      page.appendChild(makeGroup(key, members, answer, groups.dataset));
    }
  }
  groups.replaceChildren(page);
  board.querySelector(".board-empty").hidden = answer.rows.length > 0;
  slideRows(groups, before);
  showSummary(answer);
  showLinkList(answer.links || []);
  liveState.everyoneIn = answer.rows.length > 0 && answer.rows.every(function (row) {
    return row.counted;
  });
  showLiveSlot();
  lastRows = rememberRows(answer.rows);
}


// D96's overview list: one line per link, "Ana → Jay ✓" or "Bo → Cy (waiting)", like the template. The
// template leaves it out when there are no links, so a page that has none waits for the next load.
function showLinkList(links) {
  const list = board.querySelector(".board-links");
  if (!list) {
    return;
  }
  const lines = [];
  for (const link of links) {
    const line = document.createElement("li");
    line.className = "board-link";
    line.dataset.met = link.met ? "true" : "false";
    line.textContent = link.from + " → " + link.to + " " + (link.met ? "✓" : "(waiting)");
    lines.push(line);
  }
  list.replaceChildren.apply(list, lines);
  list.closest(".board-links-block").hidden = links.length === 0;
}


// One group: its heading with the count, and a real list of its rows.
function makeGroup(key, members, answer, labels) {
  const group = document.createElement("div");
  group.className = "row-group";
  group.dataset.group = key;
  const title = document.createElement("h3");
  title.className = "row-group-title";
  title.textContent = GROUP_TITLES[key] + " (" + members.length + ")";
  group.appendChild(title);
  const list = document.createElement("ul");
  list.className = "row-list";
  for (const row of members) {
    const item = makeRow(row, key, answer.links, labels);
    markChanges(item, row, lastRows.get(row.name), labels);
    list.appendChild(item);
  }
  group.appendChild(list);
  return group;
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


// Where each row is on screen now, by name, before the page changes.
function rowPlaces(groups) {
  const places = new Map();
  for (const item of groups.querySelectorAll(".row-list > li")) {
    places.set(item.querySelector(".row-name").textContent, item.getBoundingClientRect());
  }
  return places;
}


// FLIP: each row that moved starts drawn at its old place and slides to its new one, all in the same
// frames, so rows that became Counted together arrive together. Only transform moves. With reduced
// motion the rows are simply in their new places.
function slideRows(groups, before) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }
  const moved = [];
  for (const item of groups.querySelectorAll(".row-list > li")) {
    const old = before.get(item.querySelector(".row-name").textContent);
    if (old === undefined) {
      continue;
    }
    const now = item.getBoundingClientRect();
    const dx = old.left - now.left;
    const dy = old.top - now.top;
    if (dx !== 0 || dy !== 0) {
      moved.push({ item: item, dx: dx, dy: dy });
    }
  }
  for (const move of moved) {
    move.item.style.transition = "none";
    move.item.style.transform = "translate(" + move.dx + "px, " + move.dy + "px)";
  }
  void groups.offsetHeight;   // the browser draws the rows at their old places before they slide
  for (const move of moved) {
    move.item.style.transition = "transform " + SLIDE_MS + "ms " + SLIDE_EASE;
    move.item.style.transform = "";
  }
}


// The summary card: how many are in, their faces, and the newest thing that happened, in words.
function showSummary(answer) {
  const summary = board.querySelector(".who-summary");
  if (!summary) {
    return;
  }
  const everyoneWasIn = lastRows.size > 0 && Array.from(lastRows.values()).every(function (row) {
    return row.counted;
  });
  summary.hidden = answer.rows.length === 0;
  summary.querySelector(".who-count").textContent = answer.rows.length + " in";
  showCluster(summary.querySelector(".who-cluster"), answer.rows);
  const line = summary.querySelector(".who-news");
  const news = newsText(answer, line.textContent);
  if (line.textContent !== news) {
    line.textContent = news;
  }
  if (news === "Everyone's in" && !everyoneWasIn) {
    replayClass(summary.querySelector(".who-cluster"), "cluster-glow");
  }
}


// The faces: the newest pledger first (the biggest, in the middle), up to eleven, then "+N".
function showCluster(cluster, rows) {
  const newestFirst = rows.slice().reverse();
  const faces = [];
  for (const row of newestFirst.slice(0, CLUSTER_FACES)) {
    let className = "bubble";
    if (hasCountedRing(row)) {
      className = className + " is-counted";
    }
    if (!lastRows.has(row.name)) {
      className = className + " bubble-new";
    }
    faces.push(makeSpan(className, avatarText(row.name)));
  }
  if (rows.length > CLUSTER_FACES) {
    faces.push(makeSpan("bubble bubble-more", "+" + (rows.length - CLUSTER_FACES)));
  }
  cluster.replaceChildren.apply(cluster, faces);
}


// The newest thing in plain words, from the rows only. If nothing new happened, the line stays.
function newsText(answer, currentText) {
  const rows = answer.rows;
  if (rows.length === 0) {
    return "";
  }
  if (AFTER_LOCK.includes(answer.status)) {
    return rows.filter(function (row) {
      return row.status === "CHARGED";
    }).length + " charged once";
  }
  if (rows.every(function (row) { return row.counted; })) {
    return "Everyone's in";
  }
  const newNames = rows.filter(function (row) {
    return !lastRows.has(row.name);
  }).map(function (row) {
    return row.name;
  });
  if (newNames.length > 0) {
    return namesText(newNames) + " just pledged";
  }
  const nowCounted = rows.filter(function (row) {
    const before = lastRows.get(row.name);
    return row.status === "HELD" && row.counted && before !== undefined && !before.counted;
  }).map(function (row) {
    return row.name;
  });
  if (nowCounted.length === 1) {
    return nowCounted[0] + " is counted";
  }
  if (nowCounted.length > 1) {
    return namesText(nowCounted) + " are counted";
  }
  return currentText;
}


// Take a class off and put it back, so its animation plays again.
function replayClass(element, className) {
  element.classList.remove(className);
  void element.offsetWidth;
  element.classList.add(className);
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


// The word in a row's chip: "Waiting", "Counted" for a hold the circle rule counts, else the server's word.
function chipText(row, labels) {
  if (row.waiting_on_text !== "") {
    return "Waiting";
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


// The grey line under the name: the max, then the share, then who they wait on or what they need.
function makeRowDetails(row, needs, labels) {
  const details = makeSpan("row-details", "");
  details.appendChild(makeSpan("row-max", labels.maxLabel + " " + row.max_text));
  if (row.estimated_share_text !== "") {
    const sharePart = makeSpan("row-share-part", labels.shareLabel + " ");
    sharePart.appendChild(makeSpan("row-share", row.estimated_share_text));
    details.appendChild(sharePart);
  }
  if (row.waiting_on_text !== "") {
    details.appendChild(makeSpan("row-waiting", row.waiting_on_text));
  } else if (needs.length === 1) {
    details.appendChild(makeSpan("row-if", "if " + needs[0].to + "'s in"));
  } else if (needs.length > 1) {
    details.appendChild(makeSpan("row-if", "if " + namesText(needs.map(function (link) { return link.to; })) + " are in"));
  }
  return details;
}


// The name with the grey line under it.
function makeRowText(row, needs, labels) {
  const text = makeSpan("row-text", "");
  text.setAttribute("aria-hidden", "true");
  const name = makeSpan("row-name", row.name);
  name.dir = "auto";
  text.appendChild(name);
  text.appendChild(makeRowDetails(row, needs, labels));
  return text;
}


// The chip on the right: an icon and the word, so the colour is never the only sign.
function makeChip(row, key, labels) {
  const chip = makeSpan("status row-chip", "");
  chip.setAttribute("aria-hidden", "true");
  chip.appendChild(makeIcon(CHIP_ICONS[key]));
  chip.appendChild(document.createTextNode(chipText(row, labels)));
  return chip;
}


// The lines a row opens to: who this person needs, and how many people need them.
function makeDeps(row, needs, waitingOnThem, panelId) {
  const panel = document.createElement("div");
  panel.className = "row-deps";
  panel.id = panelId;
  const list = document.createElement("ul");
  list.className = "row-deps-list";
  for (const link of needs) {
    const line = document.createElement("li");
    line.className = "row-dep";
    line.dataset.met = link.met ? "true" : "false";
    line.appendChild(makeIcon(link.met ? "check" : "circle"));
    line.appendChild(document.createTextNode(link.met ? link.to + "'s in" : "Waiting on " + link.to));
    list.appendChild(line);
  }
  if (waitingOnThem > 0) {
    const line = document.createElement("li");
    line.className = "row-dep row-dep-them";
    line.appendChild(makeIcon("users"));
    const who = waitingOnThem === 1 ? "1 person is" : waitingOnThem + " people are";
    line.appendChild(document.createTextNode(who + " waiting on " + row.name));
    list.appendChild(line);
  }
  panel.appendChild(list);
  return panel;
}


// One person's row, with the same markup board_panel.html draws. A row with dependencies is a button that
// opens in place; a row without them is a plain block. data-counted is "true" or "false", for styling.
function makeRow(row, key, links, labels) {
  const item = document.createElement("li");
  item.dataset.status = row.status;
  item.dataset.counted = row.counted ? "true" : "false";
  if (row.waiting_on_text !== "") {
    item.dataset.waiting = "true";
  }
  const needs = linksFrom(links, row.name);
  const waitingOnThem = waitingOnCount(links, row.name);
  const opens = needs.length > 0 || waitingOnThem > 0;
  const main = document.createElement(opens ? "button" : "div");
  main.className = "row-main";
  main.appendChild(makeSpan("row-summary visually-hidden", rowSummary(row, labels)));
  const avatar = makeSpan("avatar row-avatar", avatarText(row.name));
  avatar.setAttribute("aria-hidden", "true");
  main.appendChild(avatar);
  main.appendChild(makeRowText(row, needs, labels));
  main.appendChild(makeChip(row, key, labels));
  item.appendChild(main);
  if (opens) {
    rowIdCount = rowIdCount + 1;
    const panelId = "deps-live-" + rowIdCount;
    const isOpen = expandedNames.has(row.name);
    main.type = "button";
    main.setAttribute("aria-expanded", isOpen ? "true" : "false");
    main.setAttribute("aria-controls", panelId);
    const chevron = makeSpan("row-chevron", "");
    chevron.setAttribute("aria-hidden", "true");
    chevron.appendChild(makeIcon("chevron-down"));
    main.appendChild(chevron);
    const panel = makeDeps(row, needs, waitingOnThem, panelId);
    panel.hidden = !isOpen;
    item.appendChild(panel);
  }
  return item;
}


// A row opens and closes in place. One listener on the groups, so rebuilt rows keep working, and the
// open ones stay open across refreshes.
function toggleRow(event) {
  const main = event.target.closest("button.row-main");
  if (main === null) {
    return;
  }
  const isOpen = main.getAttribute("aria-expanded") !== "true";
  main.setAttribute("aria-expanded", isOpen ? "true" : "false");
  document.getElementById(main.getAttribute("aria-controls")).hidden = !isOpen;
  const name = main.querySelector(".row-name").textContent;
  if (isOpen) {
    expandedNames.add(name);
  } else {
    expandedNames.delete(name);
  }
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
  liveState.status = status;
  countdown.running = false;
  countdown.inBanner = false;
  if ((status !== "OPEN" && status !== "LAST_CALL") || seconds === null) {
    const closedText = board.querySelector(".countdown-card").dataset.closedText;
    board.querySelector(".board-time").textContent = closedText;
    showWalletTime(null, closedText);
    liveState.timeText = "";
    showLiveSlot();
    return;
  }
  countdown.status = status;
  findTimeInBanner(bannerText, seconds);
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
  const timeText = countdownText(seconds, countdown.status);
  const where = bannerText.indexOf(timeText);
  if (where === -1) {
    return;
  }
  countdown.textBefore = bannerText.slice(0, where);
  countdown.textAfter = bannerText.slice(where + timeText.length);
  countdown.inBanner = true;
  board.querySelector(".board-banner").setAttribute("aria-live", "off");
}


// Put the time on the card and in its banner. A second that is already showing
// is skipped.
function showCountdownTime(seconds) {
  if (seconds === countdown.shownSeconds) {
    return;
  }
  countdown.shownSeconds = seconds;
  const timeText = countdownText(seconds, countdown.status);
  board.querySelector(".board-time").textContent = timeText;
  showWalletTime(seconds, timeText + " left");
  liveState.timeText = timeText;
  showLiveSlot();
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


// OPEN always uses h:mm:ss. LAST_CALL keeps m:ss below an hour, matching app.py's formatters.
function countdownText(seconds, status) {
  const secondsPart = twoDigits(seconds % 60);
  if (seconds < 3600 && status !== "OPEN") {
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


// ---------- The island's live slot (D103) ----------

// What the island says now, from text this file already has. kind tells a real change, which morphs the
// island, from the clock ticking, which only changes the words.
function liveSlotContent() {
  if (liveState.status === "SETTLED") {
    return { kind: "charged", text: "Charged" };
  }
  if (liveState.status === "LAST_CALL" && liveState.timeText) {
    return { kind: "lastcall", text: "Last call " + liveState.timeText };
  }
  if (liveState.status === "OPEN" && liveState.everyoneIn) {
    return { kind: "everyone", text: "Everyone's in" };
  }
  if (liveState.status === "OPEN" && liveState.timeText) {
    return { kind: "open", text: liveState.timeText + " left" };
  }
  return { kind: "", text: "" };
}


// Write the slot. When its kind changes, the island morphs to the new width (a view transition, where the
// browser has them and motion is welcome), and the change is read out once.
function showLiveSlot() {
  if (liveSlots.length === 0) {
    return;
  }
  const content = liveSlotContent();
  const changed = content.kind !== liveState.kind;
  const firstTime = liveState.kind === "";
  const update = function () {
    for (const slot of liveSlots) {
      slot.textContent = content.text;
      slot.classList.toggle("is-last-call", content.kind === "lastcall");
    }
  };
  const motionWelcome = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (changed && !firstTime && document.startViewTransition && motionWelcome) {
    document.startViewTransition(update);
  } else {
    update();
  }
  if (changed && !firstTime) {
    announceLive(content.kind);
  }
  liveState.kind = content.kind;
}


// Only the big moments are read out: last call starting, and everyone being in. Not every second.
function announceLive(kind) {
  const news = document.querySelector(".live-news");
  if (kind === "lastcall") {
    news.textContent = "Last call has started";
  } else if (kind === "everyone") {
    news.textContent = "Everyone's in";
  }
}


startBoard();
