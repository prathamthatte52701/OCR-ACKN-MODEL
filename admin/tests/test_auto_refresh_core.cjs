const assert = require('assert');
const core = require('../src/utils/autoRefreshCore.cjs');

function testTickSkipsWhenHidden() {
  const state = core.createAutoRefreshState();
  assert.strictEqual(core.shouldRefreshOnTick(state, false), false);
}

function testTickSkipsWhileRunning() {
  const state = core.createAutoRefreshState();
  assert.strictEqual(core.startRefresh(state), true);
  assert.strictEqual(core.shouldRefreshOnTick(state, true), false);
  core.endRefresh(state);
  assert.strictEqual(core.shouldRefreshOnTick(state, true), true);
}

function testTickSkipsWhenBusyOrModal() {
  const state = core.createAutoRefreshState();
  core.setBusy(state, true);
  assert.strictEqual(core.shouldRefreshOnTick(state, true), false);
  core.setBusy(state, false);
  core.setModalOpen(state, true);
  assert.strictEqual(core.shouldRefreshOnTick(state, true), false);
  core.setModalOpen(state, false);
  assert.strictEqual(core.shouldRefreshOnTick(state, true), true);
}

function testVisibleFocusThrottle() {
  const state = core.createAutoRefreshState({ minVisibleFocusIntervalMs: 5000 });
  const t0 = 1000;
  assert.strictEqual(core.shouldRefreshOnVisibleFocus(state, t0), true);
  assert.strictEqual(core.shouldRefreshOnVisibleFocus(state, t0 + 1000), false);
  assert.strictEqual(core.shouldRefreshOnVisibleFocus(state, t0 + 5000), true);
}

function testStaleIgnoredAfterLocalChange() {
  const state = core.createAutoRefreshState();
  const started = state.version;
  core.bumpVersion(state);
  assert.strictEqual(core.isStaleResponse(state, started), true);
}

function testComputeNextPage() {
  assert.strictEqual(core.computeNextPageAfterShrink(3, 2), 2);
  assert.strictEqual(core.computeNextPageAfterShrink(1, 2), 1);
  assert.strictEqual(core.computeNextPageAfterShrink(2, 0), 1);
}

testTickSkipsWhenHidden();
testTickSkipsWhileRunning();
testTickSkipsWhenBusyOrModal();
testVisibleFocusThrottle();
testStaleIgnoredAfterLocalChange();
testComputeNextPage();
console.log('ok');
