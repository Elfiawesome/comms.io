import fs from 'node:fs';
import path from 'node:path';

const candidates = [
  process.env.COMMS_WEBSITE_DATA,
  path.resolve('..', 'dist', 'data', 'v1'),
  path.resolve('..', 'data-src'),
  path.resolve('data-src')
].filter(Boolean);

const source = candidates.find((candidate) => {
  try {
    return fs.existsSync(path.join(candidate, 'manifest.json'));
  } catch {
    return false;
  }
});

if (!source) {
  console.warn(
    'No local data snapshot found. Set COMMS_WEBSITE_DATA to the archiver export directory.'
  );
  process.exit(0);
}

const target = path.resolve('public', 'data', 'v1');
fs.rmSync(target, { recursive: true, force: true });
fs.mkdirSync(path.dirname(target), { recursive: true });
fs.cpSync(source, target, { recursive: true });
console.log(`Copied local data: ${source} -> ${target}`);
