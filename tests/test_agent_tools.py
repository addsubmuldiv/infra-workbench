import copy
import json

import pytest
from jsonschema import Draft202012Validator
from backend.agent_tools import TOOLS,INSTRUCTIONS,validate_call
from backend.agent_errors import AgentError

EXPECTED={'list_hosts','find_hosts','search_hosts','get_host','get_resources','get_ssh_info','get_ssh_password'}

def test_query_tools_are_discoverable_with_complete_schemas_and_valid_examples():
    assert set(TOOLS)==EXPECTED
    for name,tool in TOOLS.items():
        assert tool['name']==name
        assert len(tool['description'])>=120
        Draft202012Validator.check_schema(tool['inputSchema'])
        Draft202012Validator.check_schema(tool['outputSchema'])
        assert tool['inputSchema']['additionalProperties'] is False
        assert set(tool['outputSchema']['properties'])>={'ok','partial','data','error'}
        examples=tool['_meta']['examples'];assert examples
        for example in examples:
            Draft202012Validator(tool['inputSchema']).validate(example['arguments'])
            validate_call(name,example['arguments'])
        # Clients which hide _meta must still get copyable JSON examples.
        for rendered in tool['description'].split('示例参数：',1)[1].split('；'):
            Draft202012Validator(tool['inputSchema']).validate(json.loads(rendered))
        assert tool['_meta']['recovery']
        assert 'infra-cli' not in json.dumps(tool,ensure_ascii=False)

def test_server_side_defaults_are_applied_without_mutating_tool_registry():
    original=copy.deepcopy(TOOLS)
    args=validate_call('search_hosts',{})
    assert args['idle'] is True and args['count']==1 and args['max_age']==30
    assert args['refresh'] is False
    assert TOOLS==original

@pytest.mark.parametrize('name,args',[
    ('search_hosts',{'count':0}),('search_hosts',{'count':True}),
    ('search_hosts',{'min_free_gib':float('nan')}),('search_hosts',{'model':'','unexpected':1}),
    ('get_ssh_password',{}),('get_ssh_info',{'host_id':'x','password':'never-an-input'}),
    ('made_up_tool',{}),
])
def test_invalid_tool_arguments_provide_mcp_recovery_without_shell_commands(name,args):
    with pytest.raises(AgentError) as result:validate_call(name,args)
    value=result.value.as_dict()
    assert value['code']=='INVALID_ARGUMENT'
    assert isinstance(value['next_action'],dict)
    assert 'infra-cli' not in json.dumps(value)

def test_instructions_explain_workflow_password_scope_and_remote_environment():
    for name in EXPECTED:assert name in INSTRUCTIONS
    for term in ('host_id','GiB','count_unit','partial','Windows','ProxyJump','SSH'):
        assert term in INSTRUCTIONS
    assert '密码' in INSTRUCTIONS and '不执行' in INSTRUCTIONS
