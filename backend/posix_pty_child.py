"""Single-threaded child: establish a controlling PTY, then replace self with ssh."""
import os
import sys


def main():
    if len(sys.argv)<5 or sys.argv[1]!='--fd' or sys.argv[3]!='--':
        raise SystemExit(2)
    descriptor=int(sys.argv[2])
    os.login_tty(descriptor)
    try:
        os.execvpe(sys.argv[4],sys.argv[4:],os.environ)
    except OSError as exc:
        # After login_tty(), stderr is the PTY seen by the user, not a server log.
        print('无法启动本机终端程序：'+str(exc),file=sys.stderr,flush=True)
        raise SystemExit(127) from None


if __name__=='__main__':main()
