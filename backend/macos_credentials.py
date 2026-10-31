"""App-owned JSON credentials in the explicitly selected macOS Keychain backend."""
import json
import re


MAX_CREDENTIAL_BYTES = 2560


def _load_backend():
    # Never use keyring.get_keyring(): automatic selection can choose a file backend.
    from keyring.backends.macOS import Keyring
    backend = Keyring()
    # The backend imports its native API lazily and reports framework availability here.
    backend.priority
    return backend


def _invalid_json_number(value):
    raise ValueError('invalid JSON number')


class MacOSCredentialStore:
    def __init__(self, namespace='InfraWorkbench/sudo/', *, backend=None):
        if not isinstance(namespace, str) or not re.fullmatch(r'InfraWorkbench/(?:[A-Za-z0-9_-]+/)+', namespace):
            raise ValueError('无效的应用凭据命名空间')
        self.namespace = namespace
        self.backend = backend
        self.supported = True
        self.error = None
        if self.backend is None:
            try:
                self.backend = _load_backend()
            except ImportError:
                self.supported = False
                self.error = 'macOS 钥匙串组件未安装，无法确认已保存的凭据；请安装依赖后重试'
            except Exception:
                self.error = '无法初始化 macOS 钥匙串，请检查系统权限并重试'

    @staticmethod
    def account(key):
        if not isinstance(key, str) or not key or not key.isascii() or not key.isalnum() or len(key) > 128:
            raise ValueError('无效的机器标识')
        return key

    def _require_backend(self):
        if self.backend is None:
            raise ValueError(self.error or 'macOS 钥匙串暂不可用，请重试') from None
        return self.backend

    def _read(self, account):
        backend = self._require_backend()
        try:
            return backend.get_password(self.namespace, account)
        except Exception:
            raise ValueError('无法读取 macOS 钥匙串，请解锁钥匙串并允许本应用访问') from None

    def get(self, key):
        raw = self._read(self.account(key))
        if raw is None:
            return None
        try:
            if not isinstance(raw, str):
                raise ValueError('invalid data')
            value = json.loads(raw, parse_constant=_invalid_json_number)
            if not isinstance(value, dict):
                raise ValueError('invalid data')
            return value
        except (TypeError, ValueError):
            raise ValueError('macOS 钥匙串中的应用凭据格式不正确，请重新保存') from None

    def put(self, key, value):
        account = self.account(key)
        backend = self._require_backend()
        try:
            if not isinstance(value, dict):
                raise ValueError('invalid data')
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
            size = len(raw.encode('utf-8'))
        except (TypeError, ValueError):
            raise ValueError('凭据格式不正确，无法保存到 macOS 钥匙串') from None
        if size > MAX_CREDENTIAL_BYTES:
            raise ValueError('密码超过凭据存储容量')
        try:
            backend.set_password(self.namespace, account, raw)
        except Exception:
            raise ValueError('无法保存到 macOS 钥匙串，请解锁钥匙串并允许本应用访问') from None

    def delete(self, key):
        account = self.account(key)
        # A denied read must not look like a missing entry or lead to deletion.
        if self._read(account) is None:
            return
        try:
            self._require_backend().delete_password(self.namespace, account)
        except Exception:
            raise ValueError('无法删除 macOS 钥匙串中的应用密码，请检查访问权限') from None
