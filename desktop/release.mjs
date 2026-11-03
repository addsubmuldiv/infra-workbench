import {createHash} from 'node:crypto';
import {readFileSync, readdirSync, writeFileSync} from 'node:fs';
import path from 'node:path';

export function verifyVersion(tag, root = path.resolve(import.meta.dirname, '..')) {
  if (!/^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(tag)) throw new Error('Expected a version tag such as v0.1.0');
  const expected = tag.slice(1);
  for (const file of ['desktop/package.json', 'desktop/package-lock.json', 'desktop/src-tauri/tauri.conf.json']) {
    if (JSON.parse(readFileSync(path.join(root, file), 'utf8')).version !== expected) throw new Error(`${file} version must equal ${expected}`);
  }
  const cargo = readFileSync(path.join(root, 'desktop/src-tauri/Cargo.toml'), 'utf8');
  const version = cargo.match(/\[package\][\s\S]*?^version\s*=\s*"([^"]+)"/m)?.[1];
  if (version !== expected) throw new Error(`Cargo.toml version must equal ${expected}`);
  const lock = JSON.parse(readFileSync(path.join(root, 'desktop/package-lock.json'), 'utf8'));
  if (lock.packages[''].version !== expected) throw new Error(`package-lock root version must equal ${expected}`);
  const cargoLock = readFileSync(path.join(root, 'desktop/src-tauri/Cargo.lock'), 'utf8');
  const lockedVersion = cargoLock.match(/name = "infra-workbench-desktop"\s+version = "([^"]+)"/)?.[1];
  if (lockedVersion !== expected) throw new Error(`Cargo.lock version must equal ${expected}`);
}

export function checksums(directory) {
  const files = readdirSync(directory).filter(name => /\.(exe|dmg)$/.test(name)).sort();
  if (files.length !== 3 || files.filter(n => n.endsWith('.exe')).length !== 1 || files.filter(n => n.endsWith('.dmg')).length !== 2) {
    throw new Error('Expected one Windows installer and two macOS disk images');
  }
  const lines = files.map(name => `${createHash('sha256').update(readFileSync(path.join(directory, name))).digest('hex')}  ${name}`);
  writeFileSync(path.join(directory, 'SHA256SUMS.txt'), lines.join('\n') + '\n');
  return files;
}

if (process.argv[1] && path.resolve(process.argv[1]) === import.meta.filename) {
  if (process.argv[2] === 'version') verifyVersion(process.argv[3]);
  else if (process.argv[2] === 'checksums') checksums(path.resolve(process.argv[3]));
  else throw new Error('Use release.mjs version <tag> or checksums <directory>');
}
