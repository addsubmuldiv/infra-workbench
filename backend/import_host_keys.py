"""Trust on first use for batch imports, preserving existing host-key pins."""
import threading

import asyncssh


_lock = threading.RLock()


class ImportHostKeys:
    def __init__(self, path):
        self.path = path
        self.pending = None

    def _matches(self, host, addr, port):
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            data = b''
        return asyncssh.match_known_hosts(data, host, addr, port)

    def validate(self, host, addr, port, key):
        with _lock:
            matches = self._matches(host, addr, port)
            if key in matches[2]:
                return False
            if key in matches[0]:
                return True
            # A different key (even a different algorithm), CA, or revocation
            # record is an existing identity, never a first-use candidate.
            if any(matches):
                return False
            self.pending = (host, addr, port, key)
            return True

    def save(self):
        # Called only after AsyncSSH has verified the signature and completed
        # authentication. Invalid handshakes must not poison known_hosts.
        if self.pending is None:
            return
        host, addr, port, key = self.pending
        with _lock:
            if not self.validate(host, addr, port, key):
                raise asyncssh.HostKeyNotVerifiable('Host key changed during import')
            if key in self._matches(host, addr, port)[0]:
                return
            name = host if port == 22 else f'[{host}]:{port}'
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a+', encoding='utf-8', newline='\n') as stream:
                stream.seek(0)
                previous = stream.read()
                if previous and not previous.endswith('\n'):
                    stream.write('\n')
                stream.write(name+' '+key.export_public_key().decode('ascii').strip()+'\n')
