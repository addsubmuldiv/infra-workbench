"""Keep unattended macOS API tests away from the user's interactive Keychain."""
import copy
import os
import sys

import pytest


class AppTestVault:
    supported = True

    def __init__(self, namespace='InfraWorkbench/sudo/'):
        self.namespace = namespace
        self.values = {}

    def get(self, key):
        return copy.deepcopy(self.values.get(key))

    def put(self, key, value):
        self.values[key] = copy.deepcopy(value)

    def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture(autouse=True)
def isolate_default_mac_app_vaults(monkeypatch):
    if sys.platform != 'darwin' or os.environ.get('IWB_TEST_KEYCHAIN') == '1':
        return
    # Only app defaults are replaced. Tests of the factory/backend itself
    # continue to inject their own fake Keychain implementation.
    from backend import app
    monkeypatch.setattr(app, 'create_credential_store', AppTestVault)


@pytest.fixture(autouse=True)
def isolate_loopback_ssh_test_configuration(monkeypatch):
    """Controlled test servers must not read the developer's own SSH config."""
    from backend.ssh import SSHService
    original = SSHService.arguments

    def arguments(service, host):
        args = original(service, host)
        if service.custom_known_hosts and host['target'] in ('127.0.0.1', 'localhost', '::1'):
            args = args[:-1]+['-F', os.devnull]+[args[-1]]
        return args

    monkeypatch.setattr(SSHService, 'arguments', arguments)
