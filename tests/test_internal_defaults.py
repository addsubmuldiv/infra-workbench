"""Changed internal defaults must reach standalone SSH scripts, not only local imports."""
import io
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
PROBES=['file_ops.py','file_upload_probe.py','folder_upload_probe.py','folder_download_probe.py','log_reader.py','log_download_probe.py']

def test_changed_defaults_reach_independent_probes_and_boundaries(tmp_path):
    (tmp_path/'config').mkdir();(tmp_path/'backend').mkdir()
    config=json.loads(subprocess.check_output(['node','--input-type=module','-e',f'import {{parseConfig}} from {json.dumps((ROOT/"scripts/generate-internal-defaults.mjs").as_uri())};import {{readFileSync}} from "node:fs";console.log(JSON.stringify(parseConfig(readFileSync("config/internal-defaults.jsonc","utf8"))));'],cwd=ROOT,text=True))
    config['files'].update(upload_max_bytes=8,text_edit_max_bytes=4,folder_upload_max_entries=2,folder_upload_max_bytes=16)
    config['logs'].update(read_max_bytes=8,line_max_bytes=4,download_max_bytes=8)
    (tmp_path/'config/internal-defaults.jsonc').write_text(json.dumps(config),encoding='utf-8')
    for name in PROBES:shutil.copyfile(ROOT/'backend'/name,tmp_path/'backend'/name)
    module=(ROOT/'scripts/generate-internal-defaults.mjs').as_uri()
    subprocess.run(['node','--input-type=module','-e',f'import {{generateInternalDefaults}} from {json.dumps(module)};generateInternalDefaults({json.dumps(str(tmp_path))});'],check=True)
    # Isolated Python (-I) proves no repository imports or JSON are required remotely.
    code='import runpy,sys,json;v=runpy.run_path(sys.argv[1]);print(json.dumps({k:v[k] for k in sys.argv[2:]}))'
    output=subprocess.check_output([sys.executable,'-I','-c',code,str(tmp_path/'backend/file_upload_probe.py'),'MAX_UPLOAD'],text=True)
    assert json.loads(output)=={'MAX_UPLOAD':8}
    ops=runpy.run_path(str(tmp_path/'backend/file_ops.py'))
    file=tmp_path/'sample';file.write_text('abcd',encoding='utf-8');assert ops['text_file'](str(file))
    file.write_text('abcde',encoding='utf-8')
    with pytest.raises(ValueError,match='4'):ops['text_file'](str(file))
    folder=runpy.run_path(str(tmp_path/'backend/folder_upload_probe.py'))
    assert folder['validate_manifest']({'version':1,'files':[],'directories':['a','b']})
    with pytest.raises(ValueError,match='2'):folder['validate_manifest']({'version':1,'files':[],'directories':['a','b','c']})
    upload=runpy.run_path(str(tmp_path/'backend/file_upload_probe.py'))
    for size in (8,9):
        import hashlib
        data=b'x'*size;header=dict(directory=str(tmp_path),name=f'upload-{size}',size=size,sha256=hashlib.sha256(data).hexdigest())
        stream=io.BytesIO(json.dumps(header).encode()+b'\n'+data)
        if size==8:assert upload['receive'](stream)['size']==8
        else:
            with pytest.raises(ValueError):upload['receive'](stream)
    assert runpy.run_path(str(tmp_path/'backend/log_reader.py'))['MAX_BYTES']==8
    assert runpy.run_path(str(tmp_path/'backend/log_download_probe.py'))['MAX_DOWNLOAD']==8
# Tests for policy consumers, with a different generated module in a fresh interpreter.
def test_connection_transfer_and_history_consumers_use_generated_values(tmp_path):
    config=json.loads(subprocess.check_output(['node','--input-type=module','-e',f'import {{parseConfig}} from {json.dumps((ROOT/"scripts/generate-internal-defaults.mjs").as_uri())};import {{readFileSync}} from "node:fs";console.log(JSON.stringify(parseConfig(readFileSync("config/internal-defaults.jsonc","utf8"))));'],cwd=ROOT,text=True))
    config['history'].update(changes_retention_days=2,resources_retention_days=3,changes_max_events=4)
    config['transfers']['concurrency']=3
    config['assistant']['context_fallback_tokens']=12345
    (tmp_path/'config').mkdir();(tmp_path/'backend').mkdir()
    (tmp_path/'config/internal-defaults.jsonc').write_text(json.dumps(config),encoding='utf-8')
    for name in PROBES:shutil.copyfile(ROOT/'backend'/name,tmp_path/'backend'/name)
    subprocess.run(['node','--input-type=module','-e',f'import {{generateInternalDefaults}} from {json.dumps((ROOT/"scripts/generate-internal-defaults.mjs").as_uri())};generateInternalDefaults({json.dumps(str(tmp_path))});'],check=True)
    code='''import sys,importlib.util,json
spec=importlib.util.spec_from_file_location('backend.internal_defaults',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.modules['backend.internal_defaults']=m
from backend import resource_history,resource_stats,file_transfers,agent_context
assert resource_history.RETENTION==2*86400
assert resource_stats.RETENTION_SECONDS==3*86400
assert resource_history.MAX_EVENTS==4
assert file_transfers.FileTransfers(None).slots._value==3
assert agent_context.FALLBACK_CONTEXT==12345
'''
    subprocess.run([sys.executable,'-c',code,str(tmp_path/'backend/internal_defaults.py')],check=True,cwd=ROOT)
