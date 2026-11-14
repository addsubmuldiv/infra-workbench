"""Read bounded training files through the same scoped SSH service as probes."""
import base64
from collections import OrderedDict
import hashlib
import json
import posixpath
import re
import threading
from pathlib import Path

from .agent_errors import AgentError
from .chat_tools import scrub


class TrainingFiles:
    def __init__(self, probes):
        self.probes = probes
        self.source = Path(__file__).with_name('training_file_probe.py').read_text(encoding='utf-8')
        self.cursors = OrderedDict()
        self.lock = threading.RLock()

    async def read(self, host_id, root, path, identity, offset, allowed, *, expected_config=None):
        return await self._read(host_id, root, path, identity, offset, allowed, finalize=False, expected_config=expected_config)

    async def read_snapshot(self, host_id, root, path, allowed, *, expected_config=None):
        return await self._read(host_id, root, path, None, 0, allowed, finalize=True, expected_config=expected_config)

    async def stage(self, host_id, root, path, run_id, content, revision, allowed, *, expected_config=None):
        if (not isinstance(run_id, str) or re.fullmatch(r'[a-f0-9]{32}', run_id) is None
                or not isinstance(revision, str) or re.fullmatch(r'[a-f0-9]{64}', revision) is None
                or not isinstance(content, str) or not content or '\x00' in content
                or len(content.encode('utf-8')) > 65536):
            raise ValueError('invalid staged script')
        if scrub(content) != content or 'PRIVATE KEY-----' in content or '[已隐藏凭据]' in content:
            raise ValueError('script contains sensitive or redacted content')
        host = self.probes.host(host_id, allowed)
        raw = content.encode('utf-8')
        encoded = base64.b64encode(raw).decode('ascii')
        script = (self.source + '\nimport json\ntry:\n'
                  + ' print("IWB_TRAINING_FILE:"+json.dumps(stage_run_script('
                  + ','.join((repr(root), repr(path), repr(run_id),
                              'base64.b64decode(' + repr(encoded) + ')', repr(revision)))
                  + ')))\nexcept Exception as exc:\n'
                  + ' print("IWB_TRAINING_FILE:"+json.dumps({"error":str(exc)[:500]}))\n')
        if expected_config is not None:
            code, out, _ = await self.probes.ssh.run_bound(host, 'python3 -', script, expected_config)
        else:
            code, out, _ = await self.probes.ssh.run(host, 'python3 -', script)
        try:
            if code:
                raise ValueError('remote staging failed')
            line = next(line for line in reversed(out.splitlines()) if line.startswith('IWB_TRAINING_FILE:'))
            result = json.loads(line[len('IWB_TRAINING_FILE:'):])
            if (result.get('name') != '.iwb-run-' + run_id
                    or result.get('sha256') != hashlib.sha256(raw).hexdigest()):
                raise ValueError('remote staging was not verified')
            return dict(path=posixpath.join(posixpath.dirname(path), result['name']), sha256=result['sha256'])
        except (StopIteration, ValueError, KeyError, TypeError):
            raise AgentError('OPERATION_FAILED', 'Unable to stage or verify the training script') from None

    async def _read(self, host_id, root, path, identity, offset, allowed, *, finalize, expected_config=None):
        if (type(offset) is not int or offset < 0 or offset > 2**63 - 1
                or (identity is not None and
                    (not isinstance(identity, str) or re.fullmatch(r'[0-9]{1,20}:[0-9]{1,20}', identity) is None))):
            raise ValueError('invalid log cursor')
        host = self.probes.host(host_id, allowed)
        key = (host_id, root, path, identity, offset)
        if offset == 0:
            state = (b'', False, False)
        else:
            with self.lock:
                state = self.cursors.get(key)
            if state is None:
                raise ValueError('log cursor expired; restart from offset zero')
        args = dict(root=root, path=path, identity=identity, offset=offset, limit=65536)
        # Arguments are serialized into Python string literals rather than a shell.
        script = (self.source + '\nimport json\ntry:\n'
                  + ' print("IWB_TRAINING_FILE:"+json.dumps(read_run_file(**'
                  + repr(args) + ')))\n'
                  + 'except Exception as exc:\n'
                  + ' print("IWB_TRAINING_FILE:"+json.dumps({"error":str(exc)[:500]}))\n')
        if expected_config is not None:
            code, out, _ = await self.probes.ssh.run_bound(host, 'python3 -', script, expected_config)
        else:
            code, out, _ = await self.probes.ssh.run(host, 'python3 -', script)
        if code:
            raise AgentError('OPERATION_FAILED', 'Remote training file read failed')
        try:
            line = next(line for line in reversed(out.splitlines()) if line.startswith('IWB_TRAINING_FILE:'))
            result = json.loads(line[len('IWB_TRAINING_FILE:'):])
            if result.get('error'):
                raise ValueError('remote file unavailable')
            raw = base64.b64decode(result.pop('data'), validate=True)
            if len(raw) > 65536:
                raise ValueError('remote page exceeds limit')
            if (not isinstance(result.get('identity'), str)
                    or re.fullmatch(r'[0-9]{1,20}:[0-9]{1,20}', result['identity']) is None
                    or type(result.get('offset')) is not int
                    or type(result.get('next_offset')) is not int
                    or type(result.get('reset')) is not bool
                    or type(result.get('has_more')) is not bool
                    or result['offset'] != (0 if result['reset'] else offset)
                    or result['next_offset'] != result['offset'] + len(raw)):
                raise ValueError('invalid remote cursor')
        except (StopIteration, ValueError, KeyError, TypeError):
            raise AgentError('OPERATION_FAILED', 'Remote training file response is invalid') from None
        if result['reset']:
            state = (b'', False, False)
        pending, private, discarding = state
        data = pending + raw
        lines = data.split(b'\n')
        pending = lines.pop()
        final_unterminated = False
        if finalize and not result['has_more']:
            final_unterminated = bool(pending)
            if pending:
                lines.append(pending)
            pending = b''
        output = []
        for line in lines:
            if discarding:
                discarding = False
                continue
            text = line.decode('utf-8', 'replace')
            if '-----BEGIN ' in text and 'PRIVATE KEY-----' in text:
                private = True
                output.append('[Private key block omitted]')
            if private:
                if '-----END ' in text and 'PRIVATE KEY-----' in text:
                    private = False
                continue
            output.append(scrub(text))
        if len(pending) > 65536:
            pending = b''
            discarding = True
            # A private-key delimiter may have been hidden in the omitted
            # line. Fail closed until an explicit key ending or rotation.
            private = True
            output.append('[Overlong line omitted; subsequent content withheld]')
        result['content'] = '\n'.join(output) + ('\n' if output and not final_unterminated else '')
        if not finalize:
            next_key = (host_id, root, path, result['identity'], result['next_offset'])
            with self.lock:
                self.cursors[next_key] = (pending, private, discarding)
                self.cursors.move_to_end(next_key)
                while len(self.cursors) > 1024:
                    self.cursors.popitem(last=False)
        return result
