"""Native OpenSSH on a local POSIX PTY, without preexec_fn in the web server."""
import asyncio
import codecs
import contextlib
import errno
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
from .desktop_runtime import pty_arguments


class PosixTerminal:
    def __init__(self,args,cols,rows):
        # These modules do not exist on Windows; importing this module stays safe.
        import pty
        self.master=None
        self.process=None
        self.closed=False
        self.close_task=None
        self.decoder=codecs.getincrementaldecoder('utf-8')('replace')
        self.write_lock=asyncio.Lock()
        master,slave=pty.openpty()
        try:
            self._size(slave,cols,rows)
            os.set_blocking(master,False)
            environment=dict(os.environ,TERM='xterm-256color')
            helper=str(Path(__file__).with_name('posix_pty_child.py'))
            # A fresh, single-threaded interpreter acquires the controlling TTY.
            # Never run Python preexec_fn/pty.fork() inside a threaded ASGI server.
            self.process=subprocess.Popen(
                pty_arguments(sys.executable,helper,slave,args),
                pass_fds=(slave,),close_fds=True,start_new_session=False,
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,env=environment)
            self.master=master
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)

    @staticmethod
    def _size(descriptor,cols,rows):
        import fcntl
        import termios
        if type(cols) is not int or type(rows) is not int or not 2<=cols<=500 or not 2<=rows<=200:
            raise ValueError('终端尺寸无效')
        fcntl.ioctl(descriptor,termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,0,0))

    @classmethod
    async def spawn(cls,args,cols,rows):
        # No await between allocating resources and returning their owner:
        # cancellation cannot abandon a background constructor holding a PTY.
        return cls(args,cols,rows)

    async def read(self):
        while not self.closed:
            try:
                data=os.read(self.master,4096)
            except BlockingIOError:
                await asyncio.sleep(.01)
                continue
            except OSError as exc:
                # Linux PTYs report EIO on slave closure; macOS returns EOF.
                if exc.errno!=errno.EIO:raise
                data=b''
            if not data:
                return self.decoder.decode(b'',final=True)
            text=self.decoder.decode(data)
            if text:return text
        return ''

    async def write(self,data):
        async with self.write_lock:
            pending=memoryview(data.encode('utf-8'))
            while pending and not self.closed:
                try:
                    written=os.write(self.master,pending[:65536])
                except BlockingIOError:
                    await asyncio.sleep(.01)
                    continue
                if written<=0:raise OSError('PTY input closed')
                pending=pending[written:]
                if pending:await asyncio.sleep(0)

    async def resize(self,cols,rows):
        if not self.closed:self._size(self.master,cols,rows)

    def _signal_owned(self,sig):
        process=self.process
        # Do not poll()/wait() before signalling: an unreaped PID is reserved to
        # this child, whereas a reaped PID may already identify an unrelated app.
        if process is None or process.returncode is not None:return
        try:
            if os.getpgid(process.pid)==process.pid:
                os.killpg(process.pid,sig)
            else:
                # The helper may not yet have called login_tty()/setsid(). Never
                # signal the inherited web server process group during startup.
                os.kill(process.pid,sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin may reject killpg when the last live group member exits
            # between getpgid and killpg. The unreaped child PID is still ours.
            try:
                os.kill(process.pid,sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Reap only on this failure path. returncode prevents every
                # later signal from targeting a PID that could now be reused.
                if process.poll() is None:
                    raise

    async def _close(self):
        descriptor=self.master
        self.master=None
        if descriptor is not None:
            with contextlib.suppress(OSError):os.close(descriptor)
        self._signal_owned(signal.SIGTERM)
        await asyncio.sleep(.15)
        self._signal_owned(signal.SIGKILL)
        if self.process is not None:
            # The only reaping operation follows the final signal, so cleanup
            # cannot accidentally target a PID recycled after an earlier wait.
            await asyncio.to_thread(self.process.wait,timeout=3)

    async def close(self):
        if self.close_task is None:
            self.closed=True
            self.close_task=asyncio.create_task(self._close())
        try:
            await asyncio.shield(self.close_task)
        except asyncio.CancelledError:
            await self.close_task
            raise
