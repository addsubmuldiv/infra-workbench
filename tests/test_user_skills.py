import io
import zipfile
import pytest
from backend.store import Store
from backend.skill_service import SkillService, SkillError


def files(name='my-check', body='检查机器。', metadata=''):
    return {'SKILL.md': f'---\nname: {name}\ndescription: 检查机器时使用\n{metadata}---\n{body}'}


@pytest.fixture
def skills(tmp_path):
    store=Store(tmp_path/'skills.db')
    service=SkillService(store, tmp_path/'builtins')
    yield service
    store.db.close()


def install(service, content=None, **kwargs):
    draft=service.create_draft(content or files(), **kwargs)
    return service.install_draft(draft['id'], draft['revision'], ['list_hosts'])


def test_lifecycle_versions_snapshot_and_restart(skills):
    one=install(skills)
    assert one['version']==1 and one['effective']=='next_turn'
    draft=skills.create_draft(files(body='新步骤。'), 'my-check', 1)
    two=skills.install_draft(draft['id'], draft['revision'], [])
    assert two['version']==2
    assert '新步骤' in skills.read('my-check')['files']['SKILL.md']
    skills.rollback('my-check', 1, 2)
    assert skills.read('my-check')['version']==1
    assert len(skills.read('my-check')['versions'])==2
    skills.set_enabled('my-check', False, 1)
    assert skills.snapshot()==({}, [])
    skills.set_enabled('my-check', True, 1)
    assert '/skills/my-check/SKILL.md' in SkillService(skills.store, skills.builtin_root).snapshot()[0]


def test_stale_draft_revision_and_uninstall_reinstall(skills):
    install(skills)
    draft=skills.create_draft(files(body='old'), 'my-check', 1)
    changed=skills.update_draft(draft['id'], 1, files(body='new'))
    with pytest.raises(SkillError): skills.install_draft(draft['id'], 1, [])
    skills.delete('my-check', 1)
    install(skills)
    with pytest.raises(SkillError): skills.install_draft(draft['id'], changed['revision'], [])


def test_validation_dependencies_references_and_yaml(skills):
    draft=skills.create_draft(files(metadata='metadata:\n  iwb-required-tools: list_hosts missing_tool\n'))
    report=skills.validate_draft(draft['id'], 1, ['list_hosts'])
    assert report['missing_tools']==['missing_tool'] and not report['valid']
    with pytest.raises(SkillError): skills.install_draft(draft['id'], 1, ['list_hosts'])
    draft=skills.create_draft(files(body='读取 references/absent.md。'))
    assert not skills.validate_draft(draft['id'],1,[])['valid']
    draft=skills.create_draft({'SKILL.md':'---\nname: [\n---\nx'})
    assert not skills.validate_draft(draft['id'],1,[])['valid']


def test_zip_preserves_binary_and_blocks_traversal(skills):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('my-check/SKILL.md',files()['SKILL.md'])
        z.writestr('my-check/assets/picture.png',b'\x89PNG\x00\xff')
    draft=skills.import_package('skill.zip',out.getvalue())
    skills.install_draft(draft['id'],1,[])
    assert 'assets/picture.png' not in skills.read('my-check')['files']
    with zipfile.ZipFile(io.BytesIO(skills.export('my-check'))) as z:
        assert z.read('my-check/assets/picture.png')==b'\x89PNG\x00\xff'
    for bad in ['../evil','C:/evil','x/../evil','x\\evil','x/CON','x/a:stream']:
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr(bad,'bad')
        with pytest.raises(SkillError):skills.import_package('bad.zip',out.getvalue())


def test_builtin_immutable_and_conflict(skills):
    root=skills.builtin_root/'my-check';root.mkdir(parents=True)
    (root/'SKILL.md').write_text(files()['SKILL.md'],encoding='utf-8')
    assert skills.catalog()[0]['source']=='builtin'
    with pytest.raises(SkillError):install(skills)
    with pytest.raises(SkillError):skills.delete('my-check',1)


def test_duplicate_case_and_symlink_packages_rejected(skills):
    for entries in [[('SKILL.md',files()['SKILL.md']),('skill.md','x')], [('SKILL.md',files()['SKILL.md']),('a','x')]]:
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for path,data in entries:
                info=zipfile.ZipInfo(path)
                if path=='a': info.create_system=3;info.external_attr=0o120777<<16
                z.writestr(info,data)
        with pytest.raises(SkillError):skills.import_package('bad.zip',out.getvalue())


def test_routes_shared_service_and_upload_bounds(skills):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.skill_routes import register_skill_routes
    app=FastAPI();register_skill_routes(app,skills,lambda:['list_hosts'])
    with TestClient(app) as client:
        draft=client.post('/api/skills/drafts',json={'files':files()}).json()
        assert client.post('/api/skills/drafts/'+draft['id']+'/validate',json={'revision':1}).json()['valid']
        assert client.post('/api/skills/drafts/'+draft['id']+'/install',json={'revision':1}).status_code==200
        assert client.get('/api/skills').json()['items'][0]['name']=='my-check'
        assert client.get('/api/skills/my-check/export').headers['content-type']=='application/zip'
        assert client.put('/api/skills/my-check/enabled',json={'enabled':False,'expected_version':2}).status_code==409
        assert client.put('/api/skills/my-check/enabled',json={'enabled':False,'expected_version':1}).status_code==200
        assert client.post('/api/skills/import?filename=x.md',content=b'x'*(2*1024*1024+1)).status_code==413
        assert client.delete('/api/skills/my-check?expected_version=1').status_code==200
        assert client.get('/api/skills/my-check').status_code==404


def test_size_bounds_and_unsafe_windows_names(skills):
    with pytest.raises(SkillError):skills.create_draft({'SKILL.md':'x'*(1024*1024+1)})
    with pytest.raises(SkillError):skills.create_draft({str(i):'x' for i in range(129)})
    for path in ['a?.md','a|b.md','a<z.md','a*.md']:
        with pytest.raises(SkillError):skills.create_draft({path:'x'})


def test_duplicate_yaml_keys_rejected(skills):
    draft=skills.create_draft({'SKILL.md':'---\nname: my-check\nname: other-check\ndescription: Check\n---\nDo it.'})
    assert not skills.validate_draft(draft['id'],1,[])['valid']


def test_edit_installed_text_preserves_binary_assets(skills):
    draft=skills.create_draft(dict(files(),**{'assets/picture.png':b'\x89PNG\xff'}))
    skills.install_draft(draft['id'],1,[])
    detail=skills.read('my-check')
    draft=skills.create_draft(detail['files'],'my-check',1)
    skills.install_draft(draft['id'],1,[])
    with zipfile.ZipFile(io.BytesIO(skills.export('my-check'))) as z:
        assert z.read('my-check/assets/picture.png')==b'\x89PNG\xff'


def test_markdown_nested_reference_links(skills):
    draft=skills.create_draft(dict(files(body='[参考](references/指南.md)'),**{'references/指南.md':'[下一步](missing.md)'}))
    assert not skills.validate_draft(draft['id'],1,[])['valid']
    draft=skills.create_draft(dict(files(body='[参考](references/指南.md)'),**{'references/指南.md':'[模板](../assets/报告.md)','assets/报告.md':'报告'}))
    assert skills.validate_draft(draft['id'],1,[])['valid']


def test_exportable_path_tree_has_consistent_directories(skills):
    for content in [dict(files(),**{'a':'file','a/b.md':'child'}),dict(files(),**{'References/a.md':'a','references/b.md':'b'})]:
        with pytest.raises(SkillError):skills.create_draft(content)


def test_binary_copy_by_rename_keeps_assets(skills):
    draft=skills.create_draft(dict(files(),**{'assets/image.bin':b'\xff\x00'}))
    skills.install_draft(draft['id'],1,[])
    copied=skills.import_package('copy.zip',skills.export('my-check'))
    content=dict(copied['files']);content['SKILL.md']=content['SKILL.md'].replace('name: my-check','name: my-copy')
    copied=skills.update_draft(copied['id'],1,content)
    skills.install_draft(copied['id'],copied['revision'],[])
    with zipfile.ZipFile(io.BytesIO(skills.export('my-copy'))) as z:
        assert z.read('my-copy/assets/image.bin')==b'\xff\x00'


def test_persisted_drafts_are_resumable_but_installed_hidden(skills):
    draft=skills.create_draft(files())
    restarted=SkillService(skills.store,skills.builtin_root)
    assert restarted.list_drafts()[0]['id']==draft['id']
    assert restarted.list_drafts()[0]['name']=='my-check'
    restarted.install_draft(draft['id'],1,[])
    assert restarted.list_drafts()==[]


def test_deep_yaml_and_bad_url_are_validation_errors(skills):
    for body in ['---\nname: my-check\ndescription: Check\nmetadata: '+('['*2000)+(']'*2000)+'\n---\nDo it.', files(body='[x](http://[bad)')['SKILL.md']]:
        draft=skills.create_draft({'SKILL.md':body})
        assert not skills.validate_draft(draft['id'],1,[])['valid']


def test_ui_private_tool_dependency_rejected_by_embedded_catalog(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    app=create_app(tmp_path,start_poll=False)
    with TestClient(app) as client:
        draft=client.post('/api/skills/import?filename=private.md',headers={'X-IWB':'1'},content=files(metadata='metadata:\n  workbench-required-tools: get_ssh_password\n')['SKILL.md'].encode()).json()
        report=client.post('/api/skills/drafts/'+draft['id']+'/validate',headers={'X-IWB':'1'},json={'revision':1}).json()
        assert report['missing_tools']==['get_ssh_password'] and not report['valid']
        assert client.post('/api/skills/drafts/'+draft['id']+'/install',headers={'X-IWB':'1'},json={'revision':1}).status_code==400


def test_builtin_cache_tracks_added_and_modified_files(skills):
    assert skills.catalog()==[]
    root=skills.builtin_root/'my-check';root.mkdir(parents=True)
    path=root/'SKILL.md';path.write_text(files()['SKILL.md'],encoding='utf-8')
    first=skills.read('my-check')
    assert skills.read('my-check')['created']==first['created']
    path.write_text(files(body='Changed instructions')['SKILL.md'],encoding='utf-8')
    assert skills.read('my-check')['hash']!=first['hash']

def test_delete_draft_revision_and_installed_skill_preserved(skills):
    install(skills)
    draft=skills.create_draft(files(body='修改'), 'my-check', 1)
    with pytest.raises(SkillError) as exc:
        skills.delete_draft(draft['id'], 2)
    assert exc.value.status_code==409
    assert skills.read_draft(draft['id'])['revision']==1
    skills.delete_draft(draft['id'], 1)
    assert skills.list_drafts()==[]
    assert skills.read('my-check')['version']==1
    with pytest.raises(SkillError) as exc:
        skills.read_draft(draft['id'])
    assert exc.value.status_code==404


def test_delete_draft_route(skills):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.skill_routes import register_skill_routes
    app=FastAPI();register_skill_routes(app,skills,lambda:[])
    draft=skills.create_draft(files())
    path='/api/skills/drafts/'+draft['id']
    with TestClient(app) as client:
        assert client.delete(path).status_code==422
        assert client.delete(path+'?expected_revision=2').status_code==409
        assert client.delete(path+'?expected_revision=1').status_code==200
        assert client.get(path).status_code==404
