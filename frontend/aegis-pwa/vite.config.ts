import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dev proxy mirrors server.mjs: service tokens are added here, never in the browser bundle.
const core = process.env.CORE_BACKEND_URL || 'http://127.0.0.1:8000';
const agent = process.env.AGENT_BACKEND_URL || 'http://127.0.0.1:8100';
const coreToken = process.env.BANKING_SERVICE_TOKEN || 'development-only';
const agentToken = process.env.AGENT_API_TOKEN || 'development-agent-only';
const recognition = process.env.RECOGNITION_BACKEND_URL;

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api/core': {
        target: core,
        rewrite: path => path.replace(/^\/api\/core/, ''),
        headers: { Authorization: `Bearer ${coreToken}` },
      },
      ...(recognition
        ? {
            '/api/recognition': {
              target: recognition,
              rewrite: (path: string) => path.replace(/^\/api\/recognition/, ''),
              headers: process.env.RECOGNITION_TOKEN ? { Authorization: `Bearer ${process.env.RECOGNITION_TOKEN}` } : {},
            },
          }
        : {}),
      '/api/agent/openapi.json': {
        target: agent,
        rewrite: () => '/openapi.json',
        headers: { Authorization: `Bearer ${agentToken}` },
      },
      '/api/agent': {
        target: agent,
        rewrite: path => path.replace(/^\/api/, ''),
        headers: { Authorization: `Bearer ${agentToken}` },
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
});
