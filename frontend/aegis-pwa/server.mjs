// Aegis PWA dev server: serves the static app and proxies /api/core and /api/agent.
// Service tokens stay on this server; the browser never sees them.
// Usage: npm run build && node server.mjs   (Node 18+)
import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { dirname, extname, join, normalize, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const publicDir = join(here, 'dist'); // run `npm run build` first

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

const SECURITY_HEADERS = {
  'Content-Security-Policy':
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
    "connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), geolocation=(), microphone=(self)',
};

// Native shells (Capacitor) load the app from these origins, so they call the API cross-origin.
const NATIVE_ORIGINS = ['capacitor://localhost', 'https://localhost', 'http://localhost'];
const CORS_HEADERS = 'Content-Type, Accept, Accept-Language, X-Trace-Id, Idempotency-Key';

function corsHeaders(req, allowed) {
  const origin = req.headers.origin;
  if (!origin || !allowed.includes(origin)) return {};
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': CORS_HEADERS,
    'Access-Control-Expose-Headers': 'X-Trace-Id',
    'Access-Control-Max-Age': '600',
    Vary: 'Origin',
  };
}

function sameHost(origin, host) {
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

function proxy(req, res, target, upstreamPath, token, cors = {}) {
  const headers = { ...req.headers, host: target.host };
  delete headers.origin;
  delete headers.referer;
  delete headers.cookie;
  if (token) headers.authorization = `Bearer ${token}`;
  else delete headers.authorization;
  const upstream = http.request(
    { hostname: target.hostname, port: target.port, path: upstreamPath, method: req.method, headers },
    response => {
      res.writeHead(response.statusCode || 502, { ...response.headers, 'Cache-Control': 'no-store', ...cors });
      response.pipe(res);
    },
  );
  upstream.on('error', () => {
    if (res.headersSent) return res.end();
    res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...cors });
    res.end(JSON.stringify({ code: 'UPSTREAM_UNAVAILABLE', message: 'upstream unavailable' }));
  });
  req.pipe(upstream);
}

async function serveStatic(pathname, res) {
  const rel = pathname === '/' ? 'index.html' : decodeURIComponent(pathname).replace(/^\/+/, '');
  const file = normalize(join(publicDir, rel));
  if (file !== publicDir && !file.startsWith(publicDir + sep)) return false;
  try {
    if (!(await stat(file)).isFile()) return false;
    const body = await readFile(file);
    const headers = {
      'Content-Type': TYPES[extname(file)] || 'application/octet-stream',
      'Cache-Control': rel === 'sw.js' || rel === 'index.html' ? 'no-cache' : 'public, max-age=300',
      ...SECURITY_HEADERS,
    };
    res.writeHead(200, headers);
    res.end(body);
    return true;
  } catch {
    return false;
  }
}

export function createAegisServer({
  coreBackend = process.env.CORE_BACKEND_URL || process.env.BACKEND_URL || 'http://127.0.0.1:8000',
  agentBackend = process.env.AGENT_BACKEND_URL || 'http://127.0.0.1:8100',
  coreToken = process.env.BANKING_SERVICE_TOKEN || 'development-only',
  agentToken = process.env.AGENT_API_TOKEN || 'development-agent-only',
  recognitionBackend = process.env.RECOGNITION_BACKEND_URL || '',
  recognitionToken = process.env.RECOGNITION_TOKEN || '',
  allowedOrigins = process.env.ALLOWED_ORIGINS ? process.env.ALLOWED_ORIGINS.split(',').map(o => o.trim()) : NATIVE_ORIGINS,
} = {}) {
  const core = new URL(coreBackend);
  const agent = new URL(agentBackend);
  return http.createServer(async (req, res) => {
    const url = new URL(req.url || '/', 'http://aegis.local');
    const isApi = url.pathname.startsWith('/api/');
    const cors = isApi ? corsHeaders(req, allowedOrigins) : {};
    if (isApi && req.headers.origin && !cors['Access-Control-Allow-Origin'] && !sameHost(req.headers.origin, req.headers.host)) {
      // Unknown cross-origin callers never reach the token-adding proxy.
      res.writeHead(403, { 'Content-Type': 'application/json; charset=utf-8' });
      return res.end(JSON.stringify({ code: 'ORIGIN_NOT_ALLOWED' }));
    }
    if (isApi && req.method === 'OPTIONS') {
      res.writeHead(204, cors);
      return res.end();
    }
    if (url.pathname.startsWith('/api/core/')) {
      return proxy(req, res, core, url.pathname.slice('/api/core'.length) + url.search, coreToken, cors);
    }
    if (url.pathname.startsWith('/api/recognition/')) {
      // Receipt recognition (separate service). Not configured → 501 so the app shows a clear message.
      if (!recognitionBackend) {
        res.writeHead(501, { 'Content-Type': 'application/json; charset=utf-8', ...cors });
        return res.end(JSON.stringify({ code: 'RECOGNITION_NOT_CONFIGURED' }));
      }
      const target = new URL(recognitionBackend);
      return proxy(req, res, target, url.pathname.slice('/api/recognition'.length) + url.search, recognitionToken, cors);
    }
    if (url.pathname.startsWith('/api/agent/')) {
      const path = url.pathname === '/api/agent/openapi.json'
        ? '/openapi.json' + url.search
        : url.pathname.slice('/api'.length) + url.search;
      return proxy(req, res, agent, path, agentToken, cors);
    }
    if (req.method === 'GET' || req.method === 'HEAD') {
      if (await serveStatic(url.pathname, res)) return;
      // SPA fallback: unknown non-file routes get the app shell.
      if (!extname(url.pathname) && (await serveStatic('/', res))) return;
    }
    res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ code: 'NOT_FOUND' }));
  });
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  const port = Number(process.env.PORT || 5174);
  const host = process.env.HOST || '127.0.0.1';
  const server = createAegisServer();
  server.listen(port, host, () => {
    const address = server.address();
    const actual = typeof address === 'object' && address ? address.port : port;
    console.log(`Aegis PWA: http://${host === '0.0.0.0' ? 'localhost' : host}:${actual}`);
    console.log(`Core:  ${process.env.CORE_BACKEND_URL || process.env.BACKEND_URL || 'http://127.0.0.1:8000'}`);
    console.log(`Agent: ${process.env.AGENT_BACKEND_URL || 'http://127.0.0.1:8100'}`);
  });
}
