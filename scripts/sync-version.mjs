import {readFileSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export function syncVersion(root = ROOT, {check = false} = {}) {
  const version = JSON.parse(readFileSync(path.join(root, 'version.json'), 'utf8')).version;
  if (typeof version !== 'string' || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/.test(version)) throw new Error('Invalid version.json version');
  const changes = [];
  function update(file, transform) {
    const before = readFileSync(path.join(root, file), 'utf8');
    const after = transform(before);
    if (before !== after) changes.push([file, after]);
  }
  for (const file of ['frontend/package.json', 'frontend/package-lock.json', 'desktop/package.json', 'desktop/package-lock.json', 'desktop/src-tauri/tauri.conf.json']) {
    update(file, text => {
      const value = JSON.parse(text);
      value.version = version;
      if (file.endsWith('package-lock.json')) value.packages[''].version = version;
      return JSON.stringify(value, null, 2) + '\n';
    });
  }
  function replace(text, pattern, replacement, file) {
    if (!pattern.test(text)) throw new Error(`Missing version field in ${file}`);
    return text.replace(pattern, replacement);
  }
  update('desktop/src-tauri/Cargo.toml', text => replace(text, /(\[package\][\s\S]*?^version\s*=\s*")[^"]+(")/m, `$1${version}$2`, 'Cargo.toml'));
  update('desktop/src-tauri/Cargo.lock', text => replace(text, /(name = "infra-workbench-desktop"\r?\nversion = ")[^"]+(")/, `$1${version}$2`, 'Cargo.lock'));
  update('backend/app.py', text => replace(text, /('name': 'infra-workbench', 'version': ')[^']+(')/, `$1${version}$2`, 'backend/app.py'));
  if (check && changes.length) throw new Error('Versions out of sync: ' + changes.map(([file]) => file).join(', '));
  if (!check) for (const [file, text] of changes) writeFileSync(path.join(root, file), text);
  return version;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.slice(2).some(arg => arg !== '--check')) throw new Error('Use node scripts/sync-version.mjs [--check]');
  console.log(syncVersion(ROOT, {check: process.argv.includes('--check')}));
}
