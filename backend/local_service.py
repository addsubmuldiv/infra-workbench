"""Fast bounded TCP preflight before a full local HTTP health check."""
import socket

def loopback_listening(port=8765,timeout=.1):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=timeout):return True
    except OSError:return False
