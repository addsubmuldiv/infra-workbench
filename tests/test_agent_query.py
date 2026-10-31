import time

from backend.agent_query import query_hosts, resolve_host
from backend.agent_errors import AgentError
import pytest

GIB = 1024**3
NOW = 1000

def host(name='alpha', count=8, kind='NPU', age=1):
    return dict(id=name+'id', target=name, user=None, port=None, manual=False,
                snapshot=dict(status='online', collected_at=NOW-age, devices=[
                    dict(id='chip:0:'+str(i), card_id='0', chip_id=str(i), kind=kind,
                         name='Ascend 910B3' if kind=='NPU' else 'H200', memory_free=48*GIB,
                         memory_total=64*GIB, health='Warning', processes_known=True, processes=[])
                    for i in range(count)]))

def test_search_any_six_devices_and_structured_deficit():
    a,b=host(),host('busy')
    for d in a['snapshot']['devices'][:2]:d['processes']=[{'pid':3}]
    for d in b['snapshot']['devices'][:4]:d['processes']=[{'pid':4}]
    result=query_hosts([a,b],'search_hosts',dict(kind='NPU',count=6,min_free_gib=40,idle=True),NOW)
    assert result['ok'] and not result['partial']
    group=result['data']['items'][0]['matched_groups'][0]
    assert group['eligible_count']==6 and group['eligible_device_ids']==[d['id'] for d in a['snapshot']['devices'][2:]]
    assert group['count_unit']=='chip'
    excluded=result['data']['excluded'][0]
    assert excluded['missing_count']==2 and excluded['reason_code']=='INSUFFICIENT_DEVICES'

def test_unknown_alarm_stale_and_unrelated_hosts():
    a=host(count=4);ds=a['snapshot']['devices']
    ds[0]['processes_known']=False;ds[1]['health']='Alarm';ds[2]['memory_free']=None
    result=query_hosts([a,host('stale',age=50),host('unrelated',kind='GPU',age=50)],'search_hosts',dict(kind='NPU',idle=True),NOW)
    assert result['partial'] and not result['ok']
    assert result['data']['items'][0]['matched_groups'][0]['eligible_count']==1
    assert [h['host_id'] for h in result['data']['excluded']]==['staleid','unrelatedid']
    assert result['error']['code']=='INCOMPLETE_RESOURCE_QUERY'

def test_mixed_kinds_never_combine_and_hardware_count_is_unbounded():
    a=host(count=16)
    assert query_hosts([a],'search_hosts',dict(count=16,idle=True),NOW)['data']['items']
    a['snapshot']['devices']=host(count=4)['snapshot']['devices']+host(kind='GPU',count=4)['snapshot']['devices']
    result=query_hosts([a],'search_hosts',dict(count=6),NOW)
    assert result['data']['items']==[] and result['ok'] and not result['partial']

def test_resolution_exact_id_precedes_alias_and_never_fuzzy():
    a=host();b=host();b['id']='second'
    assert resolve_host([a,b],a['id']) is a
    with pytest.raises(AgentError,match='AMBIGUOUS_HOST'):resolve_host([a,b],'alpha')
    with pytest.raises(AgentError,match='HOST_NOT_FOUND'):resolve_host([a],'alp')

def test_list_retains_offline_hosts_without_refresh_and_sanitizes_fields():
    a=host();a['password']='must-not-leak';a['snapshot']['status']='error'
    result=query_hosts([a],'list_hosts',{},NOW)
    assert len(result['data']['items'])==1
    assert result['data']['items'][0]['fresh'] is False
    assert 'must-not-leak' not in str(result)


def test_global_resources_are_compact_while_single_host_retains_process_details():
    a=host()
    a['snapshot']['devices'][0]['processes']=[dict(pid=7,command='synthetic task',cwd='/synthetic')]
    global_result=query_hosts([a],'get_resources',{},NOW)
    assert 'devices' not in global_result['data']['items'][0]
    assert global_result['data']['items'][0]['device_groups'][0]['occupied_devices']==1
    detail=query_hosts([a],'get_resources',dict(host_id=a['id']),NOW)
    assert detail['data']['resource']['devices'][0]['processes'][0]['pid']==7
    assert 'synthetic task' not in str(global_result)


def test_partial_search_recovery_keeps_the_requested_resource_constraints():
    result=query_hosts([host(age=50)],'search_hosts',dict(kind='NPU',count=6,min_free_gib=40,idle=True),NOW)
    action=result['error']['next_action']
    assert action['tool']=='search_hosts' and action['arguments']['count']==6
    assert action['arguments']['min_free_gib']==40 and action['arguments']['refresh'] is True
