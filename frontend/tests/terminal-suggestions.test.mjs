import test from 'node:test';import assert from 'node:assert/strict';
import {editCommandLine,historySuggestion} from '../src/terminalSuggestions.ts';
test('history candidates are prefixes, preserve punctuation and never accept in middle of the line',()=>{
  const history=[{command:'python train.py --port 1234'},{command:'python other.py'}];
  let line={text:'python tr',cursor:9,valid:true};
  assert.equal(historySuggestion(line,history),'ain.py --port 1234');
  assert.equal(historySuggestion({...line,cursor:0},history),'');
  assert.equal(historySuggestion({...line,valid:false},history),'');
  assert.equal(historySuggestion({text:'',cursor:0,valid:true},history),'');
});
test('line tracking respects editing and suspends during history search or multiline paste',()=>{
  let line={text:'',cursor:0,valid:true};
  line=editCommandLine(line,'python tr');line=editCommandLine(line,'\x7f');
  assert.deepEqual(line,{text:'python t',cursor:8,valid:true});
  assert.equal(editCommandLine(line,'\x12').valid,false);
  assert.equal(editCommandLine(line,'x\ry').valid,false);
  assert.equal(editCommandLine(line,'\r').valid,false);
  assert.deepEqual(editCommandLine(line,'\x15'),{text:'',cursor:0,valid:true});
});
