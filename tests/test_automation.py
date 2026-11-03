import asyncio
import copy
import pytest
import functools
def async_test(fn):
 @functools.wraps(fn)
 def wrapped(*a,**kw):return asyncio.run(fn(*a,**kw))
 return wrapped
from backend.automation import Automation,Draft,ALLOW,catalog
from backend.agent_errors import response

class Store:
 def __init__(self):self.data={}
 def load(self,k,d):return copy.deepcopy(self.data.get(k,d))
 def save(self,k,v):self.data[k]=copy.deepcopy(v)
class Service:
 def __init__(self,result=None):self.result=result or response({'status':'completed'});self.calls=[];self.allowed=None;self.wait=None
 def catalog(self):return {n:dict(inputSchema=dict(type='object',properties={'host_id':{'type':'string'}},required=['host_id'],additionalProperties=False),annotations={'readOnlyHint':n!='execute_server_command'}) for n in ALLOW}
 def scoped(self,state,allowed):self.allowed=allowed;return self
 async def call(self,name,args):
  self.calls.append((name,args))
  if self.wait:await self.wait.wait()
  return self.result

def setup(tool='refresh_host',**changes):
 service=Service();manager=Automation(Store(),[{'id':'h'},{'id':'x'}],service)
 draft=Draft(name='Inspect',host_ids=['h'],steps=[{'tool':tool,'arguments':{'host_id':'h'}}]).model_dump();draft.update(changes)
 return manager,service,draft

def test_validation_private_schema_host_and_scope():
 m,s,d=setup()
 for bad in ['get_ssh_password','create_automation','install_skill','missing']:
  candidate=copy.deepcopy(d);candidate['steps'][0]['tool']=bad
  with pytest.raises(ValueError):m.save(candidate)
 with pytest.raises(ValueError):m.save(d,allowed={'x'})
 candidate=copy.deepcopy(d);candidate['steps'][0]['arguments']['host_id']='x'
 with pytest.raises(ValueError):m.save(candidate)
 candidate=copy.deepcopy(d);candidate['steps'][0]['arguments']['extra']=True
 with pytest.raises(ValueError):m.save(candidate)
 assert m.save(d)['id']

def test_catalog_schema_refs():
 from jsonschema import Draft202012Validator
 for spec in catalog().values():Draft202012Validator.check_schema(spec['inputSchema'])

@async_test
async def test_run_scope_and_scrubbing():
 m,s,d=setup();s.result=response({'password':'secret','value':'ok'})
 w=m.save(d);r=m.start(w['id']);await m.tasks[w['id']]
 assert s.allowed=={'h'} and r['status']=='running'
 assert m.runs[-1]['status']=='completed' and 'secret' not in m.runs[-1]['steps'][0]['output']

@pytest.mark.parametrize('result,status',[(response({'job_id':'abc'}),'awaiting_job'),(response({'status':'unknown'}),'failed'),(response({'exit_code':1}),'failed'),(response({},partial=True),'failed'),({'ok':False},'failed')])
@async_test
async def test_incomplete_stops_steps(result,status):
 m,s,d=setup();d['steps']*=2;s.result=result;w=m.save(d);m.start(w['id']);await m.tasks[w['id']]
 assert m.runs[-1]['status']==status and len(s.calls)==1

@async_test
async def test_cancel_and_limits():
 m,s,d=setup();s.wait=asyncio.Event();w=m.save(d);m.start(w['id']);await asyncio.sleep(0)
 with pytest.raises(ValueError):m.start(w['id'])
 w2=m.save(dict(d,name='two'));m.start(w2['id']);w3=m.save(dict(d,name='three'))
 with pytest.raises(ValueError):m.start(w3['id'])
 await m.cancel(w['id']);assert m.runs[0]['status']=='cancelled';await m.close()

@async_test
async def test_trigger_optin_cooldown_and_edit_disable():
 m,s,d=setup(trigger='onOutput',literal='ready');now=[100];m.clock=lambda:now[0];w=m.save(d)
 m.terminal_event('h','s','onOutput','ready');assert not m.tasks
 m.activate(w['id'],True);m.terminal_event('x','s','onOutput','ready');assert not m.tasks
 m.terminal_event('h','s','onOutput','rea');m.terminal_event('h','s','onOutput','dy');await m.tasks[w['id']]
 m.terminal_event('h','s','onOutput','ready');assert not m.tasks
 now[0]+=61;m.terminal_event('h','s','onOutput','ready');await m.tasks[w['id']]
 m.save(d,w['id']);assert not m.enabled
 m.terminal_event('h','s','close');assert not m.buffers

@async_test
async def test_output_never_writes_connect_optin():
 m,s,d=setup('execute_server_command',trigger='onOutput',literal='go');w=m.save(d);m.activate(w['id'],True)
 m.terminal_event('h','s','onOutput','go');assert not m.tasks
 d['trigger']='onConnect';m.save(d,w['id']);m.terminal_event('h','s','onConnect');assert not m.tasks
 m.activate(w['id'],True);m.terminal_event('h','s','onConnect');await m.tasks[w['id']]
 assert len(s.calls)==1

@async_test
async def test_immediate_cancel_releases_slot():
 m,s,d=setup();w=m.save(d);m.start(w['id']);await m.cancel(w['id'])
 assert not m.tasks and m.runs[-1]['status']=='cancelled'

@async_test
async def test_actual_mcp_draft_scope_and_ui_only_execution(tmp_path):
 from backend.app import create_app
 from backend.agent_errors import AgentError
 app=create_app(tmp_path,start_poll=False)
 app.state.hosts.extend([dict(id='a',target='a',user='u',port=22),dict(id='b',target='b',user='u',port=22)])
 service=app.state.mcp_service.scoped({}, {'a'})
 draft=Draft(name='Inspect',host_ids=['a'],steps=[{'tool':'refresh_host','arguments':{'host_id':'a'}}]).model_dump()
 saved=(await service.call('create_automation',draft))['data']
 assert not app.state.automation.enabled and not app.state.automation.tasks
 assert 'run_automation' not in service.catalog() and 'activate_automation' not in service.catalog()
 draft['host_ids']=['b'];draft['steps'][0]['arguments']['host_id']='b'
 with pytest.raises(AgentError):await service.call('create_automation',draft)
 assert len((await service.call('list_automations',{}))['data']['items'])==1
 assert not (await app.state.mcp_service.scoped({}, {'b'}).call('list_automations',{}))['data']['items']
 app.state.agent_chat.store.db.close()

@async_test
async def test_completed_job_can_advance_and_old_literal_cannot_retrigger():
 m,s,d=setup();s.result=response({'job_id':'abc','status':'completed','exit_code':0});d['steps']*=2;w=m.save(d);m.start(w['id']);await m.tasks[w['id']]
 assert m.runs[-1]['status']=='completed' and len(s.calls)==2
 m,s,d=setup(trigger='onOutput',literal='ready');clock=[0];m.clock=lambda:clock[0];w=m.save(d);m.activate(w['id'],True);m.terminal_event('h','s','onOutput','ready');await m.tasks[w['id']]
 clock[0]=61;m.terminal_event('h','s','onOutput','unrelated');assert not m.tasks
