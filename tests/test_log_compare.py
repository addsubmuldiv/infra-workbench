import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.log_reader import parse_lines, read_log
from backend.log_compare import compare_logs


def parsed(rows):
    return parse_lines([json.dumps(row)+'\n' for row in rows])


def test_json_fraction_iteration_prefix_and_scientific_notation():
    data=parse_lines(['startup\n','[rank0] 2026-10-30 '+json.dumps(dict(iteration='1/300',loss=2.35592484,grad_norm=10.93841362,learning_rate=6.7e-7))+'\n'])
    assert data['skipped_lines']==1
    row=data['records'][0]
    assert row['step']==1 and row['rank']=='0' and row['metrics']['grad_norm']==10.93841362
    assert row['metrics']['learning_rate']==6.7e-7 and row['line']==2


def test_mae_uses_matching_steps_and_keeps_missing_steps_explicit():
    a=parsed([dict(iteration=f'{s}/4',loss=x,grad_norm=x*2,learning_rate=1e-5) for s,x in [(1,2),(2,9),(4,4)]])
    b=parsed([dict(iteration=f'{s}/4',loss=x,grad_norm=x*2,learning_rate=2e-5) for s,x in [(1,3),(3,7),(4,2)]])
    result=compare_logs(a,b,metrics=['loss','grad_norm'])
    loss=result['metrics'][0]
    assert loss['name']=='loss' and loss['mae']==1.5 and loss['max_abs_error']==2
    assert loss['max_error_step']==4 and loss['count']==2
    assert [r['step'] for r in loss['points']]==[1,4]
    assert result['alignment']==dict(common_steps=2,baseline_only=1,candidate_only=1)
    assert result['learning_rate_mismatch_count']==2
    assert result['metrics'][1]['mae']==3


def test_ranks_restarts_and_duplicates_require_explicit_selection():
    rows=[dict(iteration=s,loss=x,rank=rank) for rank,s,x in [(0,1,1),(1,1,8),(0,2,2),(0,1,3),(0,1,4)]]
    a=parsed(rows)
    assert len(a['groups'])==3
    with pytest.raises(ValueError,match='选择'): compare_logs(a,a,metrics=['loss'])
    group=next(g['key'] for g in a['groups'] if g['rank']=='0' and g['segment']==2)
    with pytest.raises(ValueError,match='重复'): compare_logs(a,a,metrics=['loss'],baseline_group=group,candidate_group=group)
    result=compare_logs(a,a,metrics=['loss'],baseline_group=group,candidate_group=group,duplicate_policy='last')
    assert result['metrics'][0]['points'][0]['baseline']==4


def test_nonfinite_missing_metrics_and_empty_overlap_are_not_zero_error():
    a=parsed([dict(iteration=1,loss=float('nan'),grad_norm=2),dict(iteration=2,loss=4)])
    b=parsed([dict(iteration=1,loss=3,grad_norm=float('inf')),dict(iteration=2,loss=5)])
    result=compare_logs(a,b,metrics=['loss','grad_norm'])
    assert result['metrics'][0]['count']==1 and result['metrics'][0]['mae']==1
    assert result['metrics'][1]['count']==0 and result['metrics'][1]['mae'] is None
    assert a['invalid_values']==1
    with pytest.raises(ValueError,match='共同'): compare_logs(a,parsed([dict(iteration=3,loss=2)]),metrics=['loss'])
    json.dumps(result,allow_nan=False)


def test_reader_is_bounded_regular_file_and_does_not_silently_truncate(tmp_path):
    file=tmp_path/'a; $(echo secret) 日志.jsonl'
    file.write_text(json.dumps(dict(iteration='1/300',loss=2))+'\n',encoding='utf-8')
    assert read_log(str(file))['records'][0]['step']==1
    with pytest.raises(ValueError,match='大小'): read_log(str(file),max_bytes=1)
    with pytest.raises(ValueError): read_log(str(tmp_path))
    with pytest.raises(ValueError,match='记录'): parse_lines([json.dumps(dict(iteration=i,loss=2))+'\n' for i in (1,2)],max_records=1)


def test_iteration_fallback_local_rank_and_range_selection():
    a=parsed([dict(iteration='not-step',global_step=s,loss=s,local_rank=0) for s in (0,2,5)])
    assert a['groups'][0]['rank']=='0'
    result=compare_logs(a,a,metrics=['loss'],start=2,end=2)
    assert result['metrics'][0]['count']==1 and result['range']==dict(start=2,end=2)
    with pytest.raises(ValueError,match='起始'): compare_logs(a,a,metrics=['loss'],start=5,end=2)
    with pytest.raises(ValueError,match='多条 JSON'): parse_lines(['{"iteration":1,"loss":2} {"iteration":2,"loss":3}'])


def test_overflow_values_and_missing_selected_metric_do_not_misreport_precision():
    a=parsed([dict(iteration=1,loss=1e308,grad_norm=2),dict(iteration=2,loss=1)])
    b=parsed([dict(iteration=1,loss=-1e308,grad_norm=2),dict(iteration=2,loss=2)])
    with pytest.raises(ValueError,match='数值范围'): compare_logs(a,b,metrics=['loss'])
    with pytest.raises(ValueError,match='所选指标'): compare_logs(a,b,metrics=['does-not-exist'])
    assert parsed([dict(iteration=True,loss=1),dict(iteration=1,loss=True),dict(iteration=2,loss=1)])['skipped_lines']==2


def test_optimizer_steps_aligns_real_style_metrics_without_treating_steps_as_metric():
    a=parsed([dict(optimizer_steps=10,mean_recent_loss=.4,gradient_norm=.5),dict(optimizer_steps=20,mean_recent_loss=.2,gradient_norm=.3)])
    b=parsed([dict(optimizer_steps=10,mean_recent_loss=.3,gradient_norm=.4),dict(optimizer_steps=20,mean_recent_loss=.4,gradient_norm=.4)])
    assert [r['step'] for r in a['records']]==[10,20]
    assert 'optimizer_steps' not in a['groups'][0]['metrics']
    result=compare_logs(a,b,metrics=['mean_recent_loss'],view='summary')
    assert result['alignment']['common_steps']==2
    assert result['metrics'][0]['mae']==pytest.approx(.15)
    assert result['metrics'][0]['max_abs_error']==pytest.approx(.2)


@pytest.mark.parametrize('value',[True,-1,1.5,'not-a-step',None])
def test_optimizer_steps_rejects_invalid_step_values(value):
    assert parsed([dict(optimizer_steps=value,mean_recent_loss=.2)])['records']==[]


def test_explicit_step_keeps_priority_over_optimizer_step_alias():
    data=parsed([dict(step=7,optimizer_steps=99,mean_recent_loss=.2)])
    assert data['records'][0]['step']==7
    assert 'optimizer_steps' not in data['records'][0]['metrics']
