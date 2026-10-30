"""Compare unmodified values on actual common steps, never positional alignment."""
import math


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


def compare_logs(baseline,candidate,metrics,baseline_group=None,candidate_group=None,duplicate_policy='error',start=None,end=None):
    if duplicate_policy not in ('error','first','last'): raise ValueError('无效的重复 step 策略')
    if not metrics or len(metrics)>8: raise ValueError('请选择 1 至 8 个对比指标')
    if start is not None and end is not None and start>end: raise ValueError('起始 step 不能大于结束 step')
    a=selected_rows(baseline,baseline_group,duplicate_policy,start,end)
    b=selected_rows(candidate,candidate_group,duplicate_policy,start,end)
    common=sorted(a.keys()&b.keys())
    if not common: raise ValueError('所选范围内没有共同 step，无法计算误差')
    output=[]
    for name in dict.fromkeys(metrics):
        points=[]
        for step in common:
            x,y=a[step]['metrics'].get(name),b[step]['metrics'].get(name)
            if x is None or y is None: continue
            difference=y-x
            if not math.isfinite(difference): raise ValueError('指标差值超出数值范围，无法计算误差')
            points.append(dict(step=step,baseline=x,candidate=y,difference=difference,absolute_error=abs(difference),
                               baseline_line=a[step]['line'],candidate_line=b[step]['line']))
        count=len(points)
        worst=max(points,key=lambda p:p['absolute_error']) if points else None
        # Divide before summing to avoid overflowing a finite mean.
        mae=math.fsum(p['absolute_error']/count for p in points) if count else None
        output.append(dict(name=name,count=count,missing_metric_steps=len(common)-count,mae=mae,
                           max_abs_error=worst['absolute_error'] if worst else None,
                           max_error_step=worst['step'] if worst else None,points=points,
                           baseline_series=[dict(step=s,value=a[s]['metrics'][name]) for s in sorted(a) if name in a[s]['metrics']],
                           candidate_series=[dict(step=s,value=b[s]['metrics'][name]) for s in sorted(b) if name in b[s]['metrics']]))
    if not any(m['count'] for m in output): raise ValueError('共同 step 中没有双方均可用的所选指标')
    mismatches=[s for s in common if 'learning_rate' in a[s]['metrics'] and 'learning_rate' in b[s]['metrics']
                and not math.isclose(a[s]['metrics']['learning_rate'],b[s]['metrics']['learning_rate'],rel_tol=1e-9,abs_tol=0)]
    return dict(metrics=output,alignment=dict(common_steps=len(common),baseline_only=len(a.keys()-b.keys()),candidate_only=len(b.keys()-a.keys())),
                learning_rate_mismatch_count=len(mismatches),learning_rate_first_mismatch=mismatches[0] if mismatches else None,
                range=dict(start=common[0],end=common[-1]),duplicate_policy=duplicate_policy)
