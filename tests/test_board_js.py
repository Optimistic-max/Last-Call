# Execute the actual board script with a synthetic DOM and clock. No browser or network is used.
import shutil
import subprocess
from pathlib import Path

import pytest


# Node is already installed locally. Missing Node is an explicit skip, never a claimed browser pass.
def run_board_script(checks):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; the board JavaScript simulation was not run")
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let now = 10000;
const element = () => ({textContent: '', dataset: {}, setAttribute() {}, removeAttribute() {}});
const elements = {'.board-banner': element(), '.board-time': element(),
  '.board-time-title': element(), '.countdown-card': element()};
for (const name of ['held-title', 'held-total', 'held-caption', 'counted-total', 'people', 'waiting-count', 'goal-amount']) {
  elements['.board-' + name] = element();
}
elements['.countdown-card'].dataset = {closedText: 'Closed', openTitle: 'Time left', lastCallTitle: 'Last call'};
const board = {dataset: {status: 'OPEN', secondsLeft: '600'},
  querySelector: selector => elements[selector], querySelectorAll: () => []};
elements['.board-banner'].textContent = 'Pledging open: 0:10:00 left';
const context = vm.createContext({document: {querySelector: () => board},
  Date: {now: () => now}, setInterval() {}, setTimeout() {}});
vm.runInContext(fs.readFileSync('static/js/board.js', 'utf8'), context);
const run = code => vm.runInContext(code, context);
"""
    result = subprocess.run([node, "-e", script + checks], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


# OPEN always has hours; LAST_CALL keeps its existing shorter format.
def test_board_js_open_format_and_last_call_preservation():
    run_board_script(r"""
for (const [seconds, expected] of [[0, '0:00:00'], [59, '0:00:59'], [3599, '0:59:59'],
  [3600, '1:00:00'], [172799, '47:59:59']]) {
  run(`setCountdown('OPEN', 'Pledging open: ${expected} left', ${seconds})`);
  assert.equal(elements['.board-time'].textContent, expected);
}
run("setCountdown('LAST_CALL', 'Last call! 4:59 left', 299)");
assert.equal(elements['.board-time'].textContent, '4:59');
now += 1000;
run('tickCountdown()');
assert.equal(elements['.board-banner'].textContent, 'Last call! 4:58 left');
""")


# Delayed ticks use elapsed time, refreshes reset the anchor, and zero never closes the event locally.
def test_board_js_open_tick_refresh_and_zero_clamping():
    run_board_script(r"""
assert.equal(elements['.board-time'].textContent, '0:10:00');
now += 5500;
run('tickCountdown()');
assert.equal(elements['.board-time'].textContent, '0:09:55');
assert.equal(elements['.board-banner'].textContent, 'Pledging open: 0:09:55 left');
run("setCountdown('OPEN', 'Pledging open: 1:00:00 left', 3600)");
now += 1000;
run('tickCountdown()');
assert.equal(elements['.board-time'].textContent, '0:59:59');
assert.equal(elements['.board-banner'].textContent, 'Pledging open: 0:59:59 left');
run("setCountdown('OPEN', 'Pledging open: 0:00:02 left', 2)");
now += 9000;
run('tickCountdown()');
assert.equal(elements['.board-time'].textContent, '0:00:00');
assert.equal(elements['.board-banner'].textContent, 'Pledging open: 0:00:00 left');
assert.equal(board.dataset.status, 'OPEN');
run("setCountdown('SETTLED', 'Done!', null)");
now += 2000;
run('tickCountdown()');
assert.equal(elements['.board-time'].textContent, 'Closed');
assert.equal(elements['.board-banner'].textContent, 'Done!');
""")


# Server money text is copied exactly; an empty post-lock field keeps Samuel's people-count fallback.
def test_board_js_counted_money_and_post_lock_people():
    run_board_script(r"""
const answer = {status: 'OPEN', held_total_text: '$55.01', counted_total_text: '$15.01',
  progress_percent: 7, rows: [{counted: true, waiting_on_text: ''},
  {counted: false, waiting_on_text: 'Waiting on Jay'}]};
context.answer = answer;
run('showStats(answer)');
assert.equal(elements['.board-counted-total'].textContent, '$15.01');
assert.equal(elements['.board-held-total'].textContent, '$55.01');
answer.counted_total_text = '$0.00';
run('showStats(answer)');
assert.equal(elements['.board-counted-total'].textContent, '$0.00');
answer.status = 'SETTLED';
answer.counted_total_text = '';
answer.rows[1].counted = true;
run('showStats(answer)');
assert.equal(elements['.board-counted-total'].textContent, '2 people');
""")


# D97: once the server sends charged_total_text, the first card says "Charged", shows that text and says what was
# refunded; with no charged text it stays "Held so far" with the held total. textContent only, on every refresh.
def test_board_js_first_card_switches_to_charged_after_the_lock():
    run_board_script(r"""
const answer = {status: 'SETTLED', held_total_text: '$0.00', charged_total_text: '$32.33',
  refunded_total_text: '', counted_total_text: '', progress_percent: 100, rows: []};
context.answer = answer;
run('showStats(answer)');
assert.equal(elements['.board-held-title'].textContent, 'Charged');
assert.equal(elements['.board-held-total'].textContent, '$32.33');
assert.equal(elements['.board-held-caption'].textContent, 'Charged once.');
answer.status = 'REFUNDING';
answer.refunded_total_text = '$10.77';
run('showStats(answer)');
assert.equal(elements['.board-held-total'].textContent, '$32.33');
assert.equal(elements['.board-held-caption'].textContent, 'Refunded $10.77');
answer.charged_total_text = 'Total being checked';
answer.refunded_total_text = '';
run('showStats(answer)');
assert.equal(elements['.board-held-total'].textContent, 'Total being checked');
answer.status = 'OPEN';
answer.held_total_text = '$55.01';
answer.charged_total_text = '';
run('showStats(answer)');
assert.equal(elements['.board-held-title'].textContent, 'Held so far');
assert.equal(elements['.board-held-total'].textContent, '$55.01');
assert.equal(elements['.board-held-caption'].textContent, 'PayPal is holding this. Nobody is charged yet.');
delete answer.charged_total_text;
run('showStats(answer)');
assert.equal(elements['.board-held-total'].textContent, '$55.01');
""")


def test_board_js_never_writes_the_card_text_as_html():
    source = (Path(__file__).resolve().parents[1] / "static/js/board.js").read_text(encoding="utf-8")
    assert ".innerHTML" not in source and ".outerHTML" not in source and "insertAdjacentHTML" not in source
