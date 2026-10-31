"""Single-threaded child: establish a controlling PTY, then replace self with ssh."""
import os
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv)<4 or argv[0]!='--fd' or argv[2]!='--':
        raise SystemExit(2)
    descriptor=int(argv[1])
    os.login_tty(descriptor)
    try:
        os.execvpe(argv[3],argv[3:],os.environ)
    except OSError as exc:
        # After login_tty(), stderr is the PTY seen by the user, not a server log.
        print('无法启动本机终端程序：'+str(exc),file=sys.stderr,flush=True)
        raise SystemExit(127) from None


if __name__=='__main__':main()
