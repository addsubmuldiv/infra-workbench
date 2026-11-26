"""Changed internal defaults must reach standalone SSH scripts, not only local imports."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
PROBES=['log_reader.py','log_download_probe.py']

def test_changed_defaults_reach_independent_probes(tmp_path):
    (tmp_path/'config').mkdir();(tmp_path/'backend/probes').mkdir(parents=True)
    config=json.loads(subprocess.check_output(['node','--input-type=module','-e',f'import {{parseConfig}} from {json.dumps((ROOT/"scripts/generate-internal-defaults.mjs").as_uri())};import {{readFileSync}} from "node:fs";console.log(JSON.stringify(parseConfig(readFileSync("config/internal-defaults.jsonc","utf8"))));'],cwd=ROOT,text=True))
    config['logs'].update(read_max_bytes=8,line_max_bytes=4,download_max_bytes=8)
    (tmp_path/'config/internal-defaults.jsonc').write_text(json.dumps(config),encoding='utf-8')
    for name in PROBES:shutil.copyfile(ROOT/'backend/probes'/name,tmp_path/'backend/probes'/name)
    module=(ROOT/'scripts/generate-internal-defaults.mjs').as_uri()
    subprocess.run(['node','--input-type=module','-e',f'import {{generateInternalDefaults}} from {json.dumps(module)};generateInternalDefaults({json.dumps(str(tmp_path))});'],check=True)
    # Isolated Python (-I) proves no repository imports or JSON are required remotely.
    code='import runpy,sys,json;v=runpy.run_path(sys.argv[1]);print(json.dumps({k:v[k] for k in sys.argv[2:]}))'
    reader=subprocess.check_output([sys.executable,'-I','-c',code,str(tmp_path/'backend/probes/log_reader.py'),'MAX_BYTES','MAX_LINE'],text=True)
    download=subprocess.check_output([sys.executable,'-I','-c',code,str(tmp_path/'backend/probes/log_download_probe.py'),'MAX_DOWNLOAD'],text=True)
    assert json.loads(reader)=={'MAX_BYTES':8,'MAX_LINE':4}
    assert json.loads(download)=={'MAX_DOWNLOAD':8}
# Tests for policy consumers, with a different generated module in a fresh interpreter.
def test_connection_transfer_and_history_consumers_use_generated_values(tmp_path):
    config=json.loads(subprocess.check_output(['node','--input-type=module','-e',f'import {{parseConfig}} from {json.dumps((ROOT/"scripts/generate-internal-defaults.mjs").as_uri())};import {{readFileSync}} from "node:fs";console.log(JSON.stringify(parseConfig(readFileSync("config/internal-defaults.jsonc","utf8"))));'],cwd=ROOT,text=True))
    config['history'].update(changes_retention_days=2,resources_retention_days=3,changes_max_events=4)
    config['transfers']['concurrency']=3
    config['assistant']['context_fallback_tokens']=12345
    (tmp_path/'config').mkdir();(tmp_path/'backend/probes').mkdir(parents=True)
    (tmp_path/'config/internal-defaults.jsonc').write_text(json.dumps(config),encoding='utf-8')
    for name in PROBES:shutil.copyfile(ROOT/'backend/probes'/name,tmp_path/'backend/probes'/name)
    subprocess.run(['node','--input-type=module','-e',f'import {{generateInternalDefaults}} from {json.dumps((ROOT/"scripts/generate-internal-defaults.mjs").as_uri())};generateInternalDefaults({json.dumps(str(tmp_path))});'],check=True)
    code='''import sys,importlib.util,json
spec=importlib.util.spec_from_file_location('backend.internal_defaults',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.modules['backend.internal_defaults']=m
from backend.monitoring import resource_history,resource_stats
from backend.files import file_transfers
from backend.assistant import agent_context
assert resource_history.RETENTION==2*86400
assert resource_stats.RETENTION_SECONDS==3*86400
assert resource_history.MAX_EVENTS==4
assert file_transfers.FileTransfers(None).slots._value==3
assert agent_context.FALLBACK_CONTEXT==12345
'''
    subprocess.run([sys.executable,'-c',code,str(tmp_path/'backend/internal_defaults.py')],check=True,cwd=ROOT)

def test_frozen_policy_check_detects_mixed_probe_sources(tmp_path):
    from backend.desktop_runtime import check_internal_defaults
    for name in PROBES:shutil.copyfile(ROOT/'backend/probes'/name,tmp_path/name)
    assert check_internal_defaults(tmp_path)==4
    p=tmp_path/'log_reader.py'
    p.write_text(p.read_text(encoding='utf-8')+'\nMAX_RECORDS = 1\n',encoding='utf-8')
    with pytest.raises(RuntimeError,match='log_reader'):check_internal_defaults(tmp_path)

def test_skill_limit_error_reports_configured_count(monkeypatch):
    from backend.assistant import skill_service
    monkeypatch.setattr(skill_service,'COUNT_LIMIT',2)
    with pytest.raises(skill_service.SkillError,match='最多 2 个'):
        skill_service.encode_files({'a':'','b':'','c':''})

def test_probe_directory_uses_package_not_frozen_entry_path(tmp_path,monkeypatch):
    import backend
    from backend import desktop_runtime
    monkeypatch.setattr(desktop_runtime,'__file__',str(tmp_path/'_internal/desktop_runtime.py'))
    monkeypatch.setattr(backend,'__file__',str(tmp_path/'_internal/backend/__init__.py'))
    assert desktop_runtime.probe_directory()==tmp_path/'_internal/backend/probes'
