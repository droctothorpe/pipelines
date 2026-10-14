// THROWAWAY: serve graph-boundary alternatives against the existing mock API.
import { spawn } from 'node:child_process';
import { copyFileSync } from 'node:fs';
import { build, preview } from 'vite';

// Use a preview build to bypass Vite 8's broken MUI/Emotion dev dependency optimizer.
// This is deliberately a development-only artifact; the normal production build stays unchanged.
const outDir = 'node_modules/.cache/graph-boundary-prototype';
await build({
  mode: 'development',
  define: { 'process.env.NODE_ENV': JSON.stringify('development') },
  build: { outDir, emptyOutDir: true, sourcemap: false },
});
// Ace resolves the Pipeline Spec worker relative to the page, not the bundled script.
copyFileSync(
  'node_modules/ace-builds/src-min-noconflict/worker-yaml.js',
  `${outDir}/worker-yaml.js`,
);
const mock = spawn(
  process.execPath,
  [
    'node_modules/tsx/dist/cli.mjs',
    '--tsconfig',
    'mock-backend/tsconfig.json',
    'mock-backend/mock-api-server.ts',
    '3001',
  ],
  { stdio: 'inherit' },
);
const server = await preview({
  build: { outDir },
  preview: { port: 3002, strictPort: true },
});
let stopping = false;
function stop(code) {
  if (stopping) return;
  stopping = true;
  mock.kill('SIGTERM');
  server.httpServer.close();
  process.exitCode = code;
}
mock.on('exit', (code) => stop(code ?? 0));
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));
console.log('\nGraph boundary prototype (mock data only):');
console.log(
  'http://localhost:3002/#/pipelines/details/8fbe3bd6-a01f-11e8-98d0-529269fb1462?variant=flush\n',
);
