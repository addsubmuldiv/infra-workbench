import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest
from backend.ssh import SSHService
from backend.credentials import WindowsCredentialStore
from backend.ssh_passwords import SSHPasswords
from backend.connection_info import describe_connection
from backend.agent_errors import AgentError

class Vault:
    supported=True
    def __init__(self):self.values={}
    def get(self,key):return self.values.get(key)
    def put(self,key,value):self.values[key]=value
    def delete(self,key):self.values.pop(key,None)

class Remote:
    sessions={}
    def __init__(self):self.address='server.example'
    async def effective_details(self,host):
        return dict(hostname=self.address,user='tester',port='2222',identityfile=['/tmp/a key','/tmp/b'],certificatefile=[],proxyjump='none',proxycommand='none')

def test_password_roundtrip_identity_binding_and_no_echo():
    async def scenario():
        remote,vault=Remote(),Vault();svc=SSHPasswords(remote,vault);h=dict(id='one',target='alpha')
        secret='fake "password"\n中文'
        result=await svc.save(h,secret)
        assert result['password_saved'] and secret not in json.dumps(result)
        assert (await svc.get(h))['password']==secret
        restarted=SSHPasswords(remote,vault)
        assert (await restarted.get(h))['password']==secret
        remote.address='other.example'
        with pytest.raises(AgentError,match='CREDENTIAL_IDENTITY_CHANGED'):await restarted.get(h)
        svc.forget(h)
        with pytest.raises(AgentError,match='SSH_PASSWORD_UNAVAILABLE'):await svc.get(h)
    asyncio.run(scenario())

def test_effective_details_preserves_all_keys_and_applies_real_overrides(tmp_path):
    async def scenario():
        ssh=SSHService(tmp_path)
        seen=[]
        async def command(args,*_):
            seen.extend(args)
            return 0,'hostname example\nuser tester\nport 2200\nidentityfile C:/a key\nidentityfile C:/b\ncertificatefile C:/cert1\ncertificatefile C:/cert2\n',''
        ssh.command=command
        result=await ssh.effective_details(dict(id='a',target='alpha',user='override',port=2200,key_path='C:/a key'))
        assert result['identityfile']==['C:/a key','C:/b']
        assert result['certificatefile']==['C:/cert1','C:/cert2']
        assert '-G' in seen and '-i' in seen and 'override' in seen and '2200' in seen
    asyncio.run(scenario())

def test_description_distinguishes_key_argv_and_password_session():
    async def scenario():
        ssh=Remote();ssh.arguments=lambda host:['ssh','-o','BatchMode=yes',host['target']]
        svc=SSHPasswords(ssh,Vault());h=dict(id='one',target='alpha')
        desc=await describe_connection(ssh,svc,h)
        assert desc['ssh_argv_auth_mode']=='key_or_agent_noninteractive'
        assert desc['identity_files']==['/tmp/a key','/tmp/b']
        assert desc['auth']['external_ssh_status']=='not_tested'
        assert desc['auth']['software_session_exportable'] is False
        assert desc['auth']['ssh_password_available'] is False
        assert 'password' not in desc
    asyncio.run(scenario())

def test_real_ssh_config_include_and_repeated_identity_files(tmp_path):
    async def scenario():
        config=tmp_path/'ssh config'
        included=tmp_path/'included'
        included.write_text('Host cli-fixture\n HostName fixture.example\n User fixture\n Port 2228\n IdentityFile "'+str(tmp_path/'key one').replace('\\','/')+'"\n IdentityFile '+str(tmp_path/'key-two').replace('\\','/')+'\n ProxyJump jump-fixture\n',encoding='utf-8')
        config.write_text('Include "'+str(included).replace('\\','/')+'"\n',encoding='utf-8')
        if os.name=='nt':
            user=subprocess.check_output(['whoami'],text=True).strip()
            for path in (config,included):
                subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r',user+':F'],capture_output=True,check=True)
        ssh=SSHService(tmp_path/'data');original=ssh.arguments
        ssh.arguments=lambda host:original(host)[:-1]+['-F',str(config),host['target']]
        cfg=await ssh.effective_details(dict(id='fixture',target='cli-fixture'))
        assert cfg['hostname']=='fixture.example' and cfg['port']=='2228'
        assert len(cfg['identityfile'])==2 and cfg['proxyjump']=='jump-fixture'
    asyncio.run(scenario())

def test_connection_reports_configured_auth_instead_of_claiming_all_methods():
    async def scenario():
        ssh=Remote();original=ssh.effective_details
        async def details(h):return dict(await original(h),passwordauthentication='no',kbdinteractiveauthentication='no',pubkeyauthentication='yes',preferredauthentications='publickey,password')
        ssh.effective_details=details;ssh.arguments=lambda h:['ssh',h['target']]
        desc=await describe_connection(ssh,SSHPasswords(ssh,Vault()),dict(id='one',target='alpha'))
        assert desc['auth']['configured_methods']==['publickey']
    asyncio.run(scenario())

def test_credential_config_errors_are_classified_without_raw_exception():
    async def scenario():
        remote=Remote()
        async def broken(host):raise ValueError('untrusted external detail')
        remote.effective_details=broken
        svc=SSHPasswords(remote,Vault());host=dict(id='one',target='alpha')
        with pytest.raises(AgentError,match='SSH_CONFIG_UNRESOLVED') as error:await svc.get(host)
        assert 'untrusted external detail' not in str(error.value)
    asyncio.run(scenario())

@pytest.mark.skipif(os.name!='nt',reason='Windows Credential Manager integration')
def test_native_windows_credential_roundtrip_in_private_test_namespace():
    import uuid
    async def scenario():
        vault=WindowsCredentialStore('InfraWorkbench/cli-test/')
        host=dict(id=uuid.uuid4().hex,target='synthetic-only')
        secret='SYNTHETIC-ONLY-中文-"value"'
        try:
            await SSHPasswords(Remote(),vault).save(host,secret)
            restarted=SSHPasswords(Remote(),WindowsCredentialStore('InfraWorkbench/cli-test/'))
            assert (await restarted.get(host))['password']==secret
            restarted.forget(host)
            assert vault.get(host['id']) is None
        finally:
            vault.delete(host['id'])
    asyncio.run(scenario())
