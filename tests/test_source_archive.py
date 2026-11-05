import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('source_archive', Path(__file__).resolve().parents[1]/'scripts/source_archive.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


def test_archive_uses_immutable_tree_and_only_current_assets(tmp_path):
    repo=tmp_path/'repo'
    repo.mkdir()
    subprocess.run(['git','init',str(repo)],check=True,capture_output=True)
    def put(name,data):
        file=repo/name
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(data)
    import hashlib
    put('frontend/package.json',json.dumps({'version':'1.0'}))
    put('frontend/dist/index.html','current')
    put('frontend/dist/old.js','old')
    put('.zcode/local','private')
    put('frontend/dist/.iwb-build.json',json.dumps({'version':2,'appVersion':'1.0','files':{'index.html':{'size':7,'sha256':hashlib.sha256(b'current').hexdigest()}}}))
    subprocess.run(['git','-C',str(repo),'add','.'],check=True)
    tree=subprocess.check_output(['git','-C',str(repo),'write-tree'],text=True).strip()
    put('frontend/dist/index.html','dirty')
    output=tmp_path/'source.zip'
    archive.create_archive(repo,tree,output,build_launcher=False,required=())
    with zipfile.ZipFile(output) as z:
        assert z.read('infra-workbench/frontend/dist/index.html')==b'current'
        assert 'infra-workbench/frontend/dist/old.js' not in z.namelist()
        assert not any('.zcode' in n for n in z.namelist())


def test_archive_rejects_changed_committed_asset(tmp_path):
    # The shared validator rejects a mixed inventory even if the ZIP source is immutable.
    with pytest.raises(ValueError,match='hash mismatch'):
        archive.validate_inventory({'version':2,'appVersion':'1','files':{'index.html':{'size':1,'sha256':'0'*64}}},lambda _:b'x','1')


@pytest.mark.parametrize('private', ['data/hosts.json', '.env.local', 'keys/id_rsa', 'cache/secrets.db'])
def test_archive_rejects_private_tracked_paths(tmp_path, private):
    repo=tmp_path/'repo'
    repo.mkdir()
    subprocess.run(['git','init',str(repo)],check=True,capture_output=True)
    target=repo/private
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('private')
    subprocess.run(['git','-C',str(repo),'add','.'],check=True)
    tree=subprocess.check_output(['git','-C',str(repo),'write-tree'],text=True).strip()
    with pytest.raises(ValueError,match='Sensitive'):
        archive.create_archive(repo,tree,tmp_path/'source.zip',build_launcher=False,required=())
    assert not (tmp_path/'source.zip').exists()
