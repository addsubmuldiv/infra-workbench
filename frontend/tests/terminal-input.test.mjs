import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareTerminalInput} from '../src/terminalInput.ts';
test('selected commands lose control bytes and trailing Enter without changing indentation',()=>{
 assert.equal(prepareTerminalInput('  echo hello\r\n'), '  echo hello');
 assert.equal(prepareTerminalInput('echo a\r\necho b\n'),'echo a\necho b');
 assert.equal(prepareTerminalInput('\x1b[31mecho\x03'),'[31mecho');
 assert.throws(()=>prepareTerminalInput(' \n'));
 assert.throws(()=>prepareTerminalInput('字'.repeat(12001)));
});
