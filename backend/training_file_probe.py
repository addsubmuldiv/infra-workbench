"""Bounded descriptor-relative access for remote training files."""
import base64
import hashlib
import os
import re
import stat


def _open_parent(root, path):
    if not all(isinstance(value, str) and value.startswith('/') and '\x00' not in value
               for value in (root, path)):
        raise ValueError('absolute root and path required')
    root, path = os.path.abspath(root), os.path.abspath(path)
    if os.path.commonpath((root, path)) != root:
        raise ValueError('file is outside the approved root')
    parts = os.path.relpath(path, root).split(os.sep)
    if any(part in ('', '.', '..') for part in parts):
        raise ValueError('invalid relative path')
    for part in path.split(os.sep):
        name = part.lower()
        if (name == '.ssh' or name == '.env' or name.startswith('.env.')
                or name in ('shadow', 'gshadow', 'credentials', 'credentials.json')
                or name.startswith(('id_rsa', 'id_ed25519'))
                or name.endswith(('.key', '.pem', '.p12', '.pfx'))):
            raise ValueError('protected path')
    if path.startswith(('/dev/', '/proc/')):
        raise ValueError('protected system path')
    if not hasattr(os, 'O_NOFOLLOW') or not os.supports_dir_fd or os.open not in os.supports_dir_fd:
        raise ValueError('safe descriptor-relative file access is unavailable')
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    directory = os.open('/', flags | os.O_DIRECTORY)
    try:
        for part in [part for part in root.split(os.sep) if part] + parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        return directory, parts[-1]
    except BaseException:
        os.close(directory)
        raise


def _read_regular(directory, name, limit):
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(name, flags, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('not a regular file or file exceeds size limit')
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > limit:
                raise ValueError('file exceeds size limit')
        after = os.fstat(fd)
        if (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('file changed while reading')
        return b''.join(chunks)
    finally:
        os.close(fd)


def read_run_file(root, path, identity, offset, limit):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 65536:
        raise ValueError('invalid offset or limit')
    directory, name = _open_parent(root, path)
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = os.open(name, flags, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('not a regular file')
            current = str(info.st_dev) + ':' + str(info.st_ino)
            reset = identity is not None and (identity != current or offset > info.st_size)
            if reset:
                offset = 0
            os.lseek(fd, offset, os.SEEK_SET)
            data = os.read(fd, limit)
            result = dict(identity=current, reset=reset, offset=offset,
                          next_offset=offset + len(data), size=info.st_size,
                          modified=info.st_mtime, data=base64.b64encode(data).decode('ascii'),
                          has_more=offset + len(data) < info.st_size)
            if offset == 0 and not result['has_more']:
                after = os.fstat(fd)
                if (info.st_ino, info.st_size, info.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns):
                    result['sha256'] = hashlib.sha256(data).hexdigest()
            return result
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def stage_run_script(root, path, run_id, content, expected_digest):
    if not isinstance(run_id, str) or re.fullmatch(r'[a-f0-9]{32}', run_id) is None:
        raise ValueError('invalid run ID')
    if not isinstance(expected_digest, str) or re.fullmatch(r'[a-f0-9]{64}', expected_digest) is None:
        raise ValueError('invalid source revision')
    if not isinstance(content, bytes) or not content or len(content) > 65536 or b'\x00' in content:
        raise ValueError('invalid script content')
    directory, original_name = _open_parent(root, path)
    try:
        original = _read_regular(directory, original_name, 65536)
        if hashlib.sha256(original).hexdigest() != expected_digest:
            raise ValueError('source script changed since snapshot')
        name = '.iwb-run-' + run_id
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        try:
            fd = os.open(name, flags, 0o700, dir_fd=directory)
        except FileExistsError:
            if _read_regular(directory, name, 65536) != content:
                raise ValueError('staged script already exists with different content')
        else:
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                os.unlink(name, dir_fd=directory)
                raise
        return dict(name=name, sha256=hashlib.sha256(content).hexdigest())
    finally:
        os.close(directory)
