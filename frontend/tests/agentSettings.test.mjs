import test from 'node:test';
import assert from 'node:assert/strict';
import {agentRequest,agentPayload,agentDirty,defaultAgentConfig} from '../src/agentSettings.ts';

test('a blank key preserves the saved credential without putting it in config or the URL',async()=>{
  const body=agentPayload({...defaultAgentConfig,model:' example-model '},'',true);
  assert.equal(body.api_key,null);
  assert.equal(body.model,'example-model');
  await agentRequest('','PUT',{...body,api_key:'synthetic-key'},async(url,options)=>{
    assert.equal(url,'/api/settings/agent');
    assert.equal(options.headers['X-IWB'],'1');
    assert.equal(options.cache,'no-store');
    assert.equal(JSON.parse(options.body).api_key,'synthetic-key');
    return new Response('{}');
  });
});

test('testing a saved configuration is blocked when the endpoint, model or credential changes',()=>{
  const saved={...defaultAgentConfig,model:'model-a',has_api_key:true,api_key_saved:true,can_remember:true};
  assert.equal(agentDirty(saved,saved,'',true),false);
  assert.equal(agentDirty({...saved,model:'model-b'},saved,'',true),true);
  assert.equal(agentDirty({...saved,base_url:'https://other.example/v1'},saved,'',true),true);
  assert.equal(agentDirty(saved,saved,'replacement',true),true);
  assert.equal(agentDirty(saved,saved,'',false),true);
});

test('connection errors remain readable when the backend is outdated or returns non-JSON',async()=>{
  await assert.rejects(agentRequest('/test','POST',undefined,async()=>new Response(JSON.stringify({detail:'认证失败'}),{status:400})),/认证失败/);
  await assert.rejects(agentRequest('', 'GET', undefined,async()=>new Response('<html>not an API</html>',{status:404})),/后台|接口/);
});
