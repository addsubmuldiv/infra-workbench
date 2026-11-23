"""Compare unmodified values on actual common steps, never positional alignment."""
import math
from itertools import islice


def selected_rows(data,key,policy,start,end):
    groups=data['groups']
    if not key:
        if len(groups)!=1: raise ValueError('检测到多个 rank 或训练段，请选择要比较的轨迹')
        key=groups[0]['key']
    if not any(g['key']==key for g in groups): raise ValueError('所选训练轨迹已失效，请重新选择')
    result={}
    for row in data['records']:
        step=row['step']
        if row['group']!=key or (start is not None and step<start) or (end is not None and step>end): continue
        if step in result:
            if policy=='error': raise ValueError('所选轨迹存在重复 step，请明确选择保留首条或末条')
            if policy=='first': continue
        result[step]=row
    return result


def _point(step, baseline_row, candidate_row, baseline, candidate, difference, absolute_error):
    return {
        'step': step,
        'baseline': baseline,
        'candidate': candidate,
        'difference': difference,
        'absolute_error': absolute_error,
        'baseline_line': baseline_row['line'],
        'candidate_line': candidate_row['line'],
    }


def _compare_metric(name, baseline, candidate, aligned_rows, view, offset, limit):
    errors = []
    points = []
    worst_error = -1
    worst_step = None
    first_step = last_step = None
    detail = view == 'detail'
    page = view == 'page'
    point_end = offset + limit

    for step, a, b in aligned_rows:
        x, y = a['metrics'].get(name), b['metrics'].get(name)
        if x is None or y is None:
            continue
        difference = y - x
        if not math.isfinite(difference):
            raise ValueError('指标差值超出数值范围，无法计算误差')
        absolute_error = abs(difference)
        if absolute_error > worst_error:
            worst_error, worst_step = absolute_error, step
        if not errors:
            first_step = step
        last_step = step
        if detail or (page and offset <= len(errors) < point_end):
            points.append(_point(step, a, b, x, y, difference, absolute_error))
        errors.append(absolute_error)

    if view == 'summary' and errors:
        for step in dict.fromkeys((first_step, worst_step, last_step)):
            a, b = baseline[step], candidate[step]
            x, y = a['metrics'][name], b['metrics'][name]
            difference = y - x
            points.append(_point(step, a, b, x, y, difference, abs(difference)))

    count = len(errors)
    # Divide before summing to avoid overflowing a finite mean.
    mae = math.fsum(error / count for error in errors) if count else None
    return dict(
        name=name, count=count, missing_metric_steps=len(aligned_rows) - count, mae=mae,
        max_abs_error=worst_error if count else None, max_error_step=worst_step, points=points,
    )


def compare_logs(baseline,candidate,metrics,baseline_group=None,candidate_group=None,duplicate_policy='error',start=None,end=None,view='detail',offset=0,limit=10):
    if view not in ('detail','summary','page') or offset<0 or not 1<=limit<=20:
        raise ValueError('无效的输出视图或分页参数')
    if duplicate_policy not in ('error','first','last'): raise ValueError('无效的重复 step 策略')
    if not metrics or len(metrics)>8: raise ValueError('请选择 1 至 8 个对比指标')
    if view=='page':limit=min(limit,max(1,24//len(metrics)))
    if start is not None and end is not None and start>end: raise ValueError('起始 step 不能大于结束 step')
    a=selected_rows(baseline,baseline_group,duplicate_policy,start,end)
    b=selected_rows(candidate,candidate_group,duplicate_policy,start,end)
    common=sorted(a.keys()&b.keys())
    if not common: raise ValueError('所选范围内没有共同 step，无法计算误差')
    aligned_rows = [(step, a[step], b[step]) for step in common]
    output=[]
    series = () if view == 'summary' else (
        ('baseline_series', a, sorted(a)),
        ('candidate_series', b, sorted(b)),
    )
    for name in dict.fromkeys(metrics):
        item = _compare_metric(name, a, b, aligned_rows, view, offset, limit)
        for key, rows, sorted_steps in series:
            steps = (step for step in sorted_steps if name in rows[step]['metrics'])
            if view == 'page':
                size = len(sorted_steps)
                steps = islice(steps, min(offset, size), min(offset + limit, size))
            item[key] = [{'step': step, 'value': rows[step]['metrics'][name]} for step in steps]
        output.append(item)
    if not any(m['count'] for m in output): raise ValueError('共同 step 中没有双方均可用的所选指标')
    mismatches=[s for s in common if 'learning_rate' in a[s]['metrics'] and 'learning_rate' in b[s]['metrics']
                and not math.isclose(a[s]['metrics']['learning_rate'],b[s]['metrics']['learning_rate'],rel_tol=1e-9,abs_tol=0)]
    result=dict(metrics=output,alignment=dict(common_steps=len(common),baseline_only=len(a.keys()-b.keys()),candidate_only=len(b.keys()-a.keys())),
                learning_rate_mismatch_count=len(mismatches),learning_rate_first_mismatch=mismatches[0] if mismatches else None,
                range=dict(start=common[0],end=common[-1]),duplicate_policy=duplicate_policy)
    if view!='detail':
        total=max(len(a),len(b),len(common))
        result.update(view=view,offset=offset if view=='page' else None,
                      next_offset=offset+limit if view=='page' and offset+limit<total else None,
                      has_more=view=='page' and offset+limit<total,detail_available=True)
    return result
