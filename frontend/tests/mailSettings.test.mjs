import test from 'node:test';
import assert from 'node:assert/strict';
import {recipientList,mailRequest} from '../src/mailSettings.ts';
test('recipient input accepts commas, semicolons and line breaks without duplicates',()=>{
  assert.deepEqual(recipientList('one@example.com，two@example.com;one@example.com\nthree@example.com'),['one@example.com','two@example.com','three@example.com']);
});
test('settings never use URL parameters for the password and surface safe API failures',async()=>{
  await mailRequest('','PUT',{password:'synthetic-only'},async(url,options)=>{
    assert.equal(url,'/api/settings/mail');assert.equal(options.headers['X-IWB'],'1');
    assert.equal(JSON.parse(options.body).password,'synthetic-only');return new Response('{}');
  });
  await assert.rejects(mailRequest('/test','POST',undefined,async()=>new Response(JSON.stringify({detail:'SMTP 登录失败'}),{status:400})),/SMTP 登录失败/);
});
