"""Offline release review: report locations only, never matched secret values.

Scans tracked working files and reachable Git blobs (all local refs). Findings are
review candidates, not proof of leaked/live credentials. Does not rewrite history.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

RULES = {
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'provider-token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})\b'),
    'credential-literal': re.compile(rb'''(?i)(?:api[_-]?key|password|passwd|secret|access[_-]?token)\s*[=:]\s*["']([^"'\r\n]{12,})["']'''),
    'personal-windows-path': re.compile(rb'(?i)[A-Z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|USERNAME\b)[A-Za-z0-9_.-]+'),
    'email-address': re.compile(rb'\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}\b'),
}


def git(*args, cwd=None):
    return subprocess.check_output(['git', *args], cwd=cwd)


def findings(data):
    return [rule for rule, pattern in RULES.items() if pattern.search(data)]


def scan(root, history=True):
    result = []
    def query(*args):
        return git(*args, cwd=root)
    for raw in query('ls-files', '-z').split(b'\0'):
        if not raw:
            continue
        path = raw.decode('utf-8', 'replace')
        target = root / path
        if target.is_file():
            for rule in findings(target.read_bytes()):
                result.append(dict(scope='working-tree', path=path, rule=rule))
    if history:
        objects = query('rev-list', '--objects', '--all').splitlines()
        branch_objects = {item.split(b' ', 1)[0] for item in query('rev-list', '--objects', '--branches', '--tags', '--remotes').splitlines()}
        proc = subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=root)
        try:
            for item in objects:
                oid, _, raw_path = item.partition(b' ')
                proc.stdin.write(oid + b'\n')
                proc.stdin.flush()
                header = proc.stdout.readline().split()
                if len(header) != 3:
                    raise RuntimeError('Unexpected git cat-file response')
                size = int(header[2])
                data = proc.stdout.read(size)
                proc.stdout.read(1)
                if header[1] != b'blob':
                    continue
                for rule in findings(data):
                    result.append(dict(scope='git-history', path=raw_path.decode('utf-8', 'replace'), blob=oid.decode(), reachability='branch-tag-remote' if oid in branch_objects else 'other-local-ref', rule=rule))
        finally:
            proc.stdin.close()
            proc.wait()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-history', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(git('rev-parse', '--show-toplevel').decode().strip())
    report = {'limitations': 'Heuristic offline scan; includes false positives; excludes unreachable objects, external refs, untracked files and credential stores. Does not establish whether a credential is live.',
              'findings': scan(root, not args.no_history)}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + '\n', encoding='utf-8')
    counts = {}
    for item in report['findings']:
        key = item['scope'] + ':' + item['rule']
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({'counts': counts, 'report': str(args.output) if args.output else None}, ensure_ascii=False))
    if not args.output:
        print(encoded)


if __name__ == '__main__':
    main()
