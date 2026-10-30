import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createAegisServer } from '../server.mjs';

const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));

test('proxies core and agent with server-side tokens and serves the app shell', async t => {
  const seen = [];
  const upstream = http.createServer((req, res) => {
    seen.push({ url: req.url, auth: req.headers.authorization, cookie: req.headers.cookie });
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{"ok":true}');
  });
  const upPort = await listen(upstream);
  const app = createAegisServer({
    coreBackend: `http://127.0.0.1:${upPort}`,
    agentBackend: `http://127.0.0.1:${upPort}`,
    coreToken: 'core-secret',
    agentToken: 'agent-secret',
  });
  const port = await listen(app);
  t.after(() => { app.close(); upstream.close(); });
  const base = `http://127.0.0.1:${port}`;

  const core = await fetch(`${base}/api/core/accounts?limit=5`, { headers: { Authorization: 'Bearer from-browser', Cookie: 'x=1' } });
  assert.equal(core.status, 200);
  assert.equal(core.headers.get('cache-control'), 'no-store');
  await fetch(`${base}/api/agent/tasks`, { method: 'POST', body: '{}' });
  await fetch(`${base}/api/agent/openapi.json`);
  assert.deepEqual(seen.map(s => s.url), ['/accounts?limit=5', '/agent/tasks', '/openapi.json']);
  assert.deepEqual(seen.map(s => s.auth), ['Bearer core-secret', 'Bearer agent-secret', 'Bearer agent-secret']);
  assert.equal(seen[0].cookie, undefined);

  for (const path of ['/..%2Fserver.mjs', '/..%2F..%2Fpackage.json', '/%2e%2e/server.mjs']) {
    const body = await (await fetch(base + path)).text();
    assert.ok(!body.includes('createAegisServer') && !body.includes('"devDependencies"'), `blocked ${path}`);
  }
});

test('returns 502 JSON when the backend is down', async t => {
  const app = createAegisServer({ coreBackend: 'http://127.0.0.1:9', agentBackend: 'http://127.0.0.1:9' });
  const port = await listen(app);
  t.after(() => app.close());
  const res = await fetch(`http://127.0.0.1:${port}/api/core/health`);
  assert.equal(res.status, 502);
  assert.equal((await res.json()).code, 'UPSTREAM_UNAVAILABLE');
});

test('allows native app origins, blocks unknown cross-origin callers', async t => {
  const upstream = http.createServer((req, res) => res.end('{}'));
  const upPort = await listen(upstream);
  const app = createAegisServer({ coreBackend: `http://127.0.0.1:${upPort}`, agentBackend: `http://127.0.0.1:${upPort}` });
  const port = await listen(app);
  t.after(() => { app.close(); upstream.close(); });
  const base = `http://127.0.0.1:${port}`;

  const pre = await fetch(`${base}/api/core/accounts`, { method: 'OPTIONS', headers: { Origin: 'capacitor://localhost' } });
  assert.equal(pre.status, 204);
  assert.equal(pre.headers.get('access-control-allow-origin'), 'capacitor://localhost');
  assert.match(pre.headers.get('access-control-allow-headers'), /Idempotency-Key/);

  const ok = await fetch(`${base}/api/core/accounts`, { headers: { Origin: 'https://localhost' } });
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get('access-control-allow-origin'), 'https://localhost');

  const evil = await fetch(`${base}/api/core/accounts`, { headers: { Origin: 'https://evil.example' } });
  assert.equal(evil.status, 403);
  assert.equal(evil.headers.get('access-control-allow-origin'), null);

  const same = await fetch(`${base}/api/core/accounts`, { headers: { Origin: base } });
  assert.equal(same.status, 200);
});
