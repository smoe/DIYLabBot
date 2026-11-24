'use strict';
// Exercise the initialization boundary without a simulated engine or GPU.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');
const parseLine = "    const data=JSON.parse(document.getElementById('walkthrough-data').textContent);";
const beforeDecode = source.indexOf(parseLine);
assert(beforeDecode >= 0);
const prefix = source.slice(0, beforeDecode + parseLine.length) +
  'globalThis.decoded=true;}catch(error){fail(error);}})();';
const flush = () => new Promise(resolve => setImmediate(resolve));

async function run(kind, schedule = 'hidden') {
  let resolve, parses = 0, nextId = 0;
  const errors = [], nodes = new Map(), frames = new Map(), timers = new Map();
  const enqueue = (queue, callback) => {queue.set(++nextId, callback); return nextId;};
  const advance = queue => {
    assert.equal(queue.size, 1);
    const [[id, callback]] = queue;
    queue.delete(id);
    callback();
  };
  const context = {
    console: {error: error => errors.push(String(error))},
    JSON: {parse: text => {parses++; return JSON.parse(text);}},
    document: {
      hidden: schedule === 'hidden',
      getElementById(id) {
        if (!nodes.has(id)) nodes.set(id, {
          dataset: {}, hidden: false, textContent: id === 'walkthrough-data' ? '{}' : '',
          removeAttribute(name) {delete this[name];},
        });
        return nodes.get(id);
      },
    },
    requestAnimationFrame: callback => enqueue(frames, callback),
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: callback => enqueue(timers, callback),
    clearTimeout: id => timers.delete(id),
  };
  if (kind !== 'legacy') context.__bf01EarlyTransport = {transport: {ready: new Promise(r => resolve = r)}};
  const completed = vm.runInNewContext(prefix, context);
  const root = nodes.get('building-walkthrough');
  const progress = nodes.get('walkthrough-loading-progress');
  const detail = nodes.get('walkthrough-loading-detail');
  assert.equal(parses, 0);
  if (kind !== 'legacy') {
    assert.equal(root.dataset.initialization, 'waiting_for_live_engine');
    assert.equal(progress.value, undefined);
    assert.match(detail.textContent, /Live-Patrouille/);
    assert.equal(timers.size, 0);
    resolve({status: kind});
  }
  await flush();
  if (kind === 'error') {
    await completed;
    assert.equal(parses, 0);
    assert(nodes.get('walkthrough-loading').hidden);
    assert.equal(nodes.get('walkthrough-error').hidden, false);
    assert.equal(root.dataset.ready, 'false');
    assert.equal(errors.length, 1);
    return;
  }
  assert.equal(progress.value, 0);
  assert.equal(detail.textContent, 'Reading the building data…');
  if (schedule !== 'hidden') {
    assert.equal(parses, 0, 'The reading status has a chance to paint before decoding');
    if (schedule === 'paint') {
      advance(frames);
      assert.equal(parses, 0, 'Decoding follows the frame that paints the status');
    }
    advance(timers);
  }
  await completed;
  assert.equal(parses, 1);
  assert.equal(context.decoded, true);
  assert.equal(frames.size, 0);
  assert.equal(timers.size, 0);
  assert.deepEqual(errors, []);
}

(async () => {
  await run('ready', 'paint');
  await run('error');
  await run('legacy', 'paint');
  await run('legacy', 'timeout');
  await run('legacy');
  console.log('Loading status precedes decoding in standalone and fleet startup, including without animation frames');
})().catch(error => {console.error(error); process.exitCode = 1;});
