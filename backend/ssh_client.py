"""AsyncSSH callbacks for authentication timing and imported host keys."""
import logging
import time

from asyncssh import SSHClient


class ConnectionTrace(SSHClient):
    """Record handshake/auth boundaries without logging credentials."""

    def __init__(self, host_id, host_keys=None):
        self.host_id = host_id
        self.started = time.monotonic()
        self.auth_started = False
        self.host_keys = host_keys

    def validate_host_public_key(self, host, addr, port, key):
        return bool(self.host_keys and self.host_keys.validate(host, addr, port, key))

    def begin_auth(self, username):
        self.auth_started = True
        logging.info('SSH handshake completed host_id=%s elapsed=%.3fs',
                     self.host_id, time.monotonic() - self.started)

    def auth_completed(self):
        logging.info('SSH authentication completed host_id=%s elapsed=%.3fs',
                     self.host_id, time.monotonic() - self.started)
