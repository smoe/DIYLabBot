// Cache reuse still verifies bytes; Wasm startup overlaps model downloading.
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const {pathToFileURL} = require('node:url');
const path = require('node:path');

(async () => {
 const worker = await import(pathToFileURL(path.resolve(__dirname,
  '../scripts/building_fleet_browser_worker.mjs')).href);
 const raw = new TextEncoder().encode('immutable model bytes');
 const hash = Buffer.from(await webcrypto.subtle.digest('SHA-256', raw)).toString('hex');
 const originalFetch = globalThis.fetch;
 const requests = [];
 try {
  globalThis.fetch = async (url, options) => {
   requests.push({url, options});
   return new Response(raw);
  };
  assert.deepEqual(await worker.download('runtime.zip?sha256=' + hash, hash, raw.length), raw);
  assert.equal(requests[0].options.cache, 'force-cache');
  globalThis.fetch = async () => new Response(new TextEncoder().encode('corrupt cached bytes!'));
  await assert.rejects(worker.download('runtime.zip', hash, raw.length), /hash differs/);
  globalThis.fetch = async () => new Response(new Uint8Array(raw.length + 1));
  await assert.rejects(worker.download('runtime.zip', hash, raw.length), /exceeds/);
 } finally {
  globalThis.fetch = originalFetch;
 }

 const manifest = {runtime: {loader_module_url:
  'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.mjs'}, archive: {bytes: raw.length}};
 const config = {bundle: {url: 'runtime.zip', sha256: hash}};
 const events = [];
 let finishArchive, finishPython;
 const python = {liveRuntime: true};
 const pending = worker.loadRuntimeAssets(manifest, config, {
  loadModule: async () => ({loadPyodide: ({indexURL}) => {
   events.push('python-initialization');
   assert.equal(indexURL, 'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/');
   return new Promise(resolve => {finishPython = resolve;});
  }}),
  fetchArchive: (url, expectedHash, size) => {
   events.push('archive-download');
   assert.equal(url, config.bundle.url); assert.equal(expectedHash, hash);
   assert.equal(size, raw.length);
   return new Promise(resolve => {finishArchive = resolve;});
  }
 });
 await new Promise(resolve => setImmediate(resolve));
 assert.deepEqual(events, ['archive-download', 'python-initialization'],
  'Python initialization must begin while the model download is still pending');
 finishPython(python); finishArchive(raw);
 assert.deepEqual(await pending, [python, raw]);
 await assert.rejects(worker.loadRuntimeAssets(manifest, config, {
  loadModule: async () => {throw Error('runtime unavailable');},
  fetchArchive: async () => raw
 }), /runtime unavailable/);
 const names = ['pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm',
  'python_stdlib.zip', 'pyodide-lock.json'];
 const coreManifest = {...manifest, python_core: {directory: 'python/314.0.8-pinned',
  files: Object.fromEntries(names.map(name => [name, {sha256: hash, bytes: raw.length}]))}};
 const localConfig = {...config, manifest: {url: 'https://example.test/bf01/runtime-manifest.json'}};
 const fetched = [];
 const assets = await worker.loadRuntimeAssets(coreManifest, localConfig, {
  fetchCore: async (url, digest, size) => {
   assert.equal(digest, hash); assert.equal(size, raw.length); fetched.push(url); return raw;
  },
  fetchArchive: async () => raw,
  loadModule: async url => {
   assert.equal(fetched.length, names.length, 'All executable/runtime bytes must be checked first');
   assert.equal(url, 'https://example.test/bf01/python/314.0.8-pinned/pyodide.mjs');
   return {loadPyodide: async ({indexURL}) => {
    assert.equal(indexURL, 'https://example.test/bf01/python/314.0.8-pinned/'); return python;
   }};
  }
 });
 assert.deepEqual(assets, [python, raw]);
 await assert.rejects(worker.loadRuntimeAssets(coreManifest, localConfig, {
  fetchCore: async () => {throw Error('core hash differs');},
  fetchArchive: async () => raw,
  loadModule: async () => assert.fail('A corrupt original core must not execute')
 }), /core hash differs/);
 console.log('Passed parallel Python/model loading and hash-verified cache reuse.');
})().catch(error => {console.error(error); process.exitCode = 1;});
