import {test} from 'node:test';
import assert from 'node:assert/strict';
import {pageFromHash,hostSelectionPage} from '../src/navigation.ts';

test('every workspace page can be restored from its address',()=>{
  for(const page of ['overview','connections','watch','precision','reservations','settings'])assert.equal(pageFromHash('#'+page),page);
  assert.equal(pageFromHash(''),'overview');
  assert.equal(pageFromHash('#unknown'),'overview');
});

test('machine names always open device overview, including precision and watch pages',()=>{
  for(const page of ['overview','connections','watch','precision','reservations','settings'])assert.equal(hostSelectionPage(page,true),'overview');
});

test('machine filter controls leave non-device pages and preserve the connections view',()=>{
  assert.equal(hostSelectionPage('precision'),'overview');
  assert.equal(hostSelectionPage('watch'),'overview');
  assert.equal(hostSelectionPage('overview'),'overview');
  assert.equal(hostSelectionPage('connections'),'connections');
});
