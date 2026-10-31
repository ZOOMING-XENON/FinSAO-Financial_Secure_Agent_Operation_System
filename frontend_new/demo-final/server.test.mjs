import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import http from 'node:http';
import test from 'node:test';

import { createFrontendServer } from './server.mjs';

const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
const close = server => new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
const fixture = name => http.createServer((req, res) => { let body = ''; req.on('data', chunk => { body += chunk; }); req.on('end', () => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ name, method: req.method, url: req.url, body, authorization: req.headers.authorization })); }); });

test('serves the app and routes Core and Agent independently', async t => {
  const core = fixture('core'), agent = fixture('agent');
  const corePort = await listen(core), agentPort = await listen(agent);
  const frontend = createFrontendServer({ coreBackend: `http://127.0.0.1:${corePort}`, agentBackend: `http://127.0.0.1:${agentPort}`, coreToken: 'core-fixture', agentToken: 'agent-fixture' });
  const frontendPort = await listen(frontend);
  t.after(async () => Promise.all([close(frontend), close(core), close(agent)]));

  const page = await fetch(`http://127.0.0.1:${frontendPort}/`);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Finpilot/);
  const styles = await fetch(`http://127.0.0.1:${frontendPort}/styles.css`);
  assert.equal(styles.status, 200);
  assert.match(styles.headers.get('content-type'), /text\/css/);
  const source = await readFile(new URL('./index.html', import.meta.url), 'utf8');
  const script = source.match(/<script>([\s\S]*)<\/script>/)?.[1];
  assert.ok(script);
  assert.doesNotThrow(() => new Function(script));
  assert.doesNotMatch(source, /function splitCompoundTasks/);
  assert.match(source, /agentApi\('\/decompose'/);
  assert.doesNotMatch(
    source.match(/function submitClarification\(id\)\{[^\n]+\}/)?.[0] ?? '',
    /ai\.transferIntent|source_account_id} to account/,
  );

  const coreResponse = await fetch(`http://127.0.0.1:${frontendPort}/api/core/accounts?limit=2`);
  assert.deepEqual(await coreResponse.json(), { name: 'core', method: 'GET', url: '/accounts?limit=2', body: '', authorization: 'Bearer core-fixture' });
  const agentResponse = await fetch(`http://127.0.0.1:${frontendPort}/api/agent/requests`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"x"}' });
  assert.deepEqual(await agentResponse.json(), { name: 'agent', method: 'POST', url: '/agent/requests', body: '{"message":"x"}', authorization: 'Bearer agent-fixture' });
  const decomposition = await fetch(`http://127.0.0.1:${frontendPort}/api/agent/decompose`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"x"}' });
  assert.deepEqual(await decomposition.json(), { name: 'agent', method: 'POST', url: '/agent/decompose', body: '{"message":"x"}', authorization: 'Bearer agent-fixture' });
  const openApi = await fetch(`http://127.0.0.1:${frontendPort}/api/agent/openapi.json`);
  assert.deepEqual(await openApi.json(), { name: 'agent', method: 'GET', url: '/openapi.json', body: '', authorization: 'Bearer agent-fixture' });
  assert.equal((await fetch(`http://127.0.0.1:${frontendPort}/unknown`)).status, 404);
});
