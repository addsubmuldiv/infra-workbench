"""Run with Linux Python too, to exercise actual POSIX cache protections."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.probe_cache import BOOTSTRAP


@unittest.skipUnless(os.name == 'posix', 'remote cache uses Linux ownership and O_NOFOLLOW')
class RemoteCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.source = b'import sys; print("IWB_JSON:"+str("--fast" in sys.argv))'
        self.digest = hashlib.sha256(self.source).hexdigest()
        self.path = self.home/'.cache'/'infra-workbench'/'probes'/(self.digest+'.py')

    def tearDown(self):
        self.temp.cleanup()

    def run_probe(self, install=False, slow=True):
        return subprocess.run([sys.executable, '-c', BOOTSTRAP, self.digest, str(int(install)), str(slow)],
                              input=self.source if install else b'', capture_output=True,
                              env=dict(os.environ, HOME=str(self.home)), timeout=5)

    def test_install_hit_fast_and_corruption(self):
        self.assertEqual(self.run_probe().returncode, 73)
        self.assertEqual(self.run_probe(True).stdout, b'IWB_JSON:False\n')
        self.assertEqual(self.run_probe(slow=False).stdout, b'IWB_JSON:True\n')
        self.path.write_text('raise RuntimeError("must never execute")')
        self.assertEqual(self.run_probe().returncode, 73)
        self.assertEqual(self.run_probe(True).returncode, 0)

    def test_symlink_is_not_executed_or_written_through(self):
        self.run_probe(True)
        target = self.home/'victim'
        target.write_text('untouched')
        self.path.unlink()
        self.path.symlink_to(target)
        self.assertEqual(self.run_probe().returncode, 73)
        self.assertEqual(self.run_probe(True).returncode, 0)
        self.assertEqual(target.read_text(), 'untouched')

    def test_writable_directory_and_file_rejected(self):
        self.run_probe(True)
        self.path.chmod(0o666)
        self.assertEqual(self.run_probe().returncode, 73)
        self.path.parent.chmod(0o777)
        self.assertEqual(self.run_probe(True).returncode, 73)


if __name__ == '__main__':
    unittest.main()
