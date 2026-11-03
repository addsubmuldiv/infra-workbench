import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, writeFileSync, readFileSync, rmSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {checksums, verifyVersion} from './release.mjs';

test('release tag must match all desktop versions', () => {
  const current = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')).version;
  verifyVersion('v' + current);
  assert.throws(() => verifyVersion('v9.9.9'), /version must equal/);
  assert.throws(() => verifyVersion('../main'), /Expected a version tag/);
});
test('checksum inventory requires all three platform installers', () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'iwb-release-'));
  try {
    writeFileSync(path.join(dir, 'windows.exe'), 'abc');
    assert.throws(() => checksums(dir), /Expected one Windows/);
    writeFileSync(path.join(dir, 'arm64.dmg'), 'abc');
    writeFileSync(path.join(dir, 'x64.dmg'), 'abc');
    checksums(dir);
    const manifest = readFileSync(path.join(dir, 'SHA256SUMS.txt'), 'utf8');
    assert.equal(manifest.split('\n').filter(Boolean).length, 3);
    assert.match(manifest, /ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad/);
    assert.doesNotThrow(() => checksums(dir));
  } finally { rmSync(dir, {recursive: true}); }
});
