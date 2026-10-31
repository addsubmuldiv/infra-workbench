"""Credential backends are isolated fakes; no OS credential store is opened."""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend import credentials


SECRET='SYNTHETIC-MAC-KEYCHAIN-SECRET'


class Backend:
    def __init__(self):self.values={};self.calls=[];self.fail=None
    def get_password(self,service,account):
        self.calls.append(('get',service,account))
        if self.fail=='get':raise RuntimeError('denied '+SECRET)
        return self.values.get((service,account))
    def set_password(self,service,account,password):
        self.calls.append(('put',service,account))
        if self.fail=='put':raise RuntimeError('locked '+SECRET)
        self.values[(service,account)]=password
    def delete_password(self,service,account):
        self.calls.append(('delete',service,account))
        if self.fail=='delete':raise RuntimeError('denied '+SECRET)
        self.values.pop((service,account),None)


def mac_module():
    assert hasattr(credentials,'create_credential_store'), 'platform credential factory is missing'
    return importlib.import_module('backend.macos_credentials')


def test_factory_keeps_windows_backend_and_namespace(monkeypatch):
    assert hasattr(credentials,'create_credential_store'), 'platform credential factory is missing'
    marker=object();calls=[]
    def windows(namespace):calls.append(namespace);return marker
    monkeypatch.setattr(credentials.sys,'platform','win32')
    monkeypatch.setattr(credentials,'WindowsCredentialStore',windows)
    assert credentials.create_credential_store('InfraWorkbench/ssh/') is marker
    assert calls==['InfraWorkbench/ssh/']


def test_factory_uses_explicit_mac_backend_and_keeps_namespaces_separate(monkeypatch):
    module=mac_module();backend=Backend()
    monkeypatch.setattr(credentials.sys,'platform','darwin')
    monkeypatch.setattr(module,'_load_backend',lambda:backend)
    sudo=credentials.create_credential_store()
    ssh=credentials.create_credential_store('InfraWorkbench/ssh/')
    mail=credentials.create_credential_store('InfraWorkbench/mail/')
    assert all(store.supported for store in (sudo,ssh,mail))
    for store,name in ((sudo,'sudo'),(ssh,'ssh'),(mail,'mail')):
        store.put('host123',dict(password=SECRET,kind=name,identity=['目标',22]))
    assert len(backend.values)==3
    assert json.loads(backend.values[('InfraWorkbench/ssh/','host123')])['kind']=='ssh'
    assert ssh.get('host123')==dict(password=SECRET,kind='ssh',identity=['目标',22])
    sudo.delete('host123')
    assert sudo.get('host123') is None and ssh.get('host123')['password']==SECRET
    assert mail.get('host123')['kind']=='mail'


@pytest.mark.parametrize('key',['','../other','a/b','with space','x'*129,None,123])
def test_mac_rejects_invalid_machine_ids_before_backend_access(key):
    backend=Backend();store=mac_module().MacOSCredentialStore(backend=backend)
    for operation in (lambda:store.get(key),lambda:store.put(key,{'password':SECRET}),lambda:store.delete(key)):
        with pytest.raises(ValueError) as error:operation()
        assert SECRET not in str(error.value)
    assert backend.calls==[]


@pytest.mark.parametrize('namespace',['other-app/sudo/','InfraWorkbench','InfraWorkbench/../','InfraWorkbench/ssh/extra space/'])
def test_mac_namespace_is_limited_to_app_entries(namespace):
    with pytest.raises(ValueError):mac_module().MacOSCredentialStore(namespace,backend=Backend())


@pytest.mark.parametrize('raw',['not-json '+SECRET,'null','[]','"'+SECRET+'"','42',b'not text'])
def test_malformed_keychain_data_is_reported_without_echoing_it(raw):
    backend=Backend();store=mac_module().MacOSCredentialStore(backend=backend)
    backend.values[(store.namespace,'host123')]=raw
    with pytest.raises(ValueError) as error:store.get('host123')
    assert SECRET not in str(error.value)
    assert (store.namespace,'host123') in backend.values


@pytest.mark.parametrize('operation',['get','put','delete'])
def test_denied_keychain_operations_raise_safe_errors_and_keep_existing_data(operation):
    backend=Backend();store=mac_module().MacOSCredentialStore(backend=backend)
    store.put('host123',{'password':SECRET});before=dict(backend.values)
    backend.fail=operation
    action={'get':lambda:store.get('host123'),'put':lambda:store.put('host123',{'password':'new '+SECRET}),
            'delete':lambda:store.delete('host123')}[operation]
    with pytest.raises(ValueError) as error:action()
    assert SECRET not in str(error.value) and '钥匙串' in str(error.value)
    assert backend.values==before and store.supported is True


def test_missing_entry_is_none_and_delete_is_idempotent_but_denial_is_not_missing():
    backend=Backend();store=mac_module().MacOSCredentialStore(backend=backend)
    assert store.get('missing') is None
    store.delete('missing')
    assert not any(call[0]=='delete' for call in backend.calls)
    backend.fail='get'
    with pytest.raises(ValueError):store.get('missing')
    with pytest.raises(ValueError):store.delete('missing')
    assert not any(call[0]=='delete' for call in backend.calls)


def test_missing_mac_dependency_disables_remember_without_claiming_existing_entry_missing(monkeypatch):
    module=mac_module()
    def missing():raise ImportError('missing dependency '+SECRET)
    monkeypatch.setattr(module,'_load_backend',missing)
    store=module.MacOSCredentialStore()
    assert store.supported is False
    for action in (lambda:store.get('host123'),lambda:store.put('host123',{'password':SECRET}),lambda:store.delete('host123')):
        with pytest.raises(ValueError) as error:action()
        assert SECRET not in str(error.value)


def test_backend_initialization_failure_is_not_reported_as_missing_credentials(monkeypatch):
    module=mac_module()
    def denied():raise RuntimeError('locked '+SECRET)
    monkeypatch.setattr(module,'_load_backend',denied)
    store=module.MacOSCredentialStore()
    assert store.supported is True
    with pytest.raises(ValueError) as error:store.get('host123')
    assert SECRET not in str(error.value)


def test_non_mac_import_does_not_import_keyring_or_load_native_mac_frameworks():
    mac_module()
    source="""
import builtins
original=__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in ('keyring','objc','Foundation'):
        raise AssertionError('native/keyring import on non-mac')
    return original(name,*args,**kwargs)
builtins.__import__=guarded
import backend.credentials
import backend.macos_credentials
assert callable(backend.credentials.create_credential_store)
"""
    completed=subprocess.run([sys.executable,'-c',source],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr


def test_app_defaults_use_factory_three_times_and_preserve_explicit_vaults(tmp_path,monkeypatch):
    mac_module()
    import backend.app as module
    from test_server_import_routes import Vault
    calls=[]
    def factory(namespace='InfraWorkbench/sudo/'):
        calls.append(namespace);return Vault()
    monkeypatch.setattr(module,'create_credential_store',factory)
    app=module.create_app(tmp_path/'defaults',start_poll=False)
    assert calls==['InfraWorkbench/ssh/','InfraWorkbench/sudo/','InfraWorkbench/mail/']
    assert app.state.ssh_passwords.vault is not app.state.mail.vault
    calls.clear();vault=Vault()
    app=module.create_app(tmp_path/'injected',start_poll=False,credential_store=vault,email_credential_store=vault,ssh_credential_store=vault)
    assert calls==[] and app.state.mail.vault is vault and app.state.ssh_passwords.vault is vault


def test_backend_loader_selects_only_mac_backend_without_keyring_autodetection(monkeypatch):
    import builtins
    from types import SimpleNamespace
    module=mac_module();backend=Backend();backend.priority=5;imports=[]
    original=builtins.__import__
    def direct_only(name,*args,**kwargs):
        if name=='keyring.backends.macOS':
            imports.append(name);return SimpleNamespace(Keyring=lambda:backend)
        if name.startswith('keyring'):
            raise AssertionError('automatic keyring selection is forbidden')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',direct_only)
    assert module._load_backend() is backend
    assert imports==['keyring.backends.macOS']


def test_unsupported_platform_has_no_native_vault_or_file_fallback(monkeypatch):
    assert hasattr(credentials,'create_credential_store')
    monkeypatch.setattr(credentials.sys,'platform','linux')
    store=credentials.create_credential_store()
    assert store.supported is False and store.get('host123') is None
    store.delete('host123')
    with pytest.raises(ValueError):store.put('host123',{'password':SECRET})


@pytest.mark.parametrize('value',[None,[],SECRET,{'password':object()},{'password':float('nan')}])
def test_invalid_json_payload_never_reaches_keychain(value):
    backend=Backend();store=mac_module().MacOSCredentialStore(backend=backend)
    with pytest.raises(ValueError) as error:store.put('host123',value)
    assert SECRET not in str(error.value) and backend.calls==[]


def test_oversized_payload_is_rejected_without_overwriting_stored_entry():
    backend=Backend();store=mac_module().MacOSCredentialStore(backend=backend)
    store.put('host123',{'password':SECRET});before=dict(backend.values)
    with pytest.raises(ValueError):store.put('host123',{'password':SECRET*200})
    assert backend.values==before


@pytest.mark.parametrize('raw',['{"password":NaN}','{"password":Infinity}','{"password":-Infinity}'])
def test_nonstandard_json_numbers_are_malformed_keychain_data(raw):
    backend=Backend();store=mac_module().MacOSCredentialStore(backend=backend)
    backend.values[(store.namespace,'host123')]=raw
    with pytest.raises(ValueError):store.get('host123')
