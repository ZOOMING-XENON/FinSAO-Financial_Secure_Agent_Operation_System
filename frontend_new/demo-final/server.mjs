// FinSAO zero-dependency development server with separate Core and Agent proxies.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

function proxy(req, res, target, upstreamPath, token) {
  const headers = { ...req.headers, host: target.host };
  delete headers.origin;
  delete headers.referer;
  headers.authorization = `Bearer ${token}`;
  const upstream = http.request(
    { hostname: target.hostname, port: target.port, path: upstreamPath, method: req.method, headers },
    response => {
      res.writeHead(response.statusCode || 502, response.headers);
      response.pipe(res);
    },
  );
  upstream.on('error', () => {
    if (res.headersSent) return res.end();
    res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ code: 'UPSTREAM_UNAVAILABLE', message: 'upstream unavailable' }));
  });
  req.pipe(upstream);
}

export function createFrontendServer({
  coreBackend = process.env.CORE_BACKEND_URL || process.env.BACKEND_URL || 'http://127.0.0.1:8000',
  agentBackend = process.env.AGENT_BACKEND_URL || 'http://127.0.0.1:8100',
  coreToken = process.env.BANKING_SERVICE_TOKEN || 'development-only',
  agentToken = process.env.AGENT_API_TOKEN || 'development-agent-only',
} = {}) {
  const core = new URL(coreBackend);
  const agent = new URL(agentBackend);
  return http.createServer(async (req, res) => {
    const requestUrl = new URL(req.url || '/', 'http://frontend.local');
    const assets = { '/styles.css': 'text/css; charset=utf-8', '/ui.js': 'text/javascript; charset=utf-8' };
    if (req.method === 'GET' && assets[requestUrl.pathname]) {
      try {
        const content = await readFile(join(here, requestUrl.pathname.slice(1)));
        res.writeHead(200, { 'Content-Type': assets[requestUrl.pathname], 'Cache-Control': 'no-store' });
        return res.end(content);
      } catch {
        res.writeHead(404);
        return res.end();
      }
    }
    if (req.method === 'GET' && ['/', '/index.html'].includes(requestUrl.pathname)) {
      try {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
        return res.end(await readFile(join(here, 'index.html')));
      } catch {
        res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
        return res.end(JSON.stringify({ code: 'FRONTEND_READ_FAILED' }));
      }
    }
    if (requestUrl.pathname.startsWith('/api/core/')) {
      return proxy(req, res, core, requestUrl.pathname.slice('/api/core'.length) + requestUrl.search, coreToken);
    }
    if (requestUrl.pathname.startsWith('/api/agent/')) {
      const path = requestUrl.pathname === '/api/agent/openapi.json'
        ? '/openapi.json' + requestUrl.search
        : requestUrl.pathname.slice('/api'.length) + requestUrl.search;
      return proxy(req, res, agent, path, agentToken);
    }
    res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
    return res.end(JSON.stringify({ code: 'FRONTEND_ROUTE_NOT_FOUND' }));
  });
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const port = Number(process.env.PORT || 5173);
  const server = createFrontendServer();
  server.listen(port, '127.0.0.1', () => {
    const address = server.address();
    const actualPort = typeof address === 'object' && address ? address.port : port;
    console.log(`FinSAO 前端: http://127.0.0.1:${actualPort}`);
    console.log(`Core: ${process.env.CORE_BACKEND_URL || process.env.BACKEND_URL || 'http://127.0.0.1:8000'}`);
    console.log(`Agent: ${process.env.AGENT_BACKEND_URL || 'http://127.0.0.1:8100'}`);
  });
}
