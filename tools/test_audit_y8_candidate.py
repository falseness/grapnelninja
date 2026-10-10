"""Regression checks for historical candidate source binding (no browsers)."""
import contextlib
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from audit_y8_candidate import audit_source


class SourceBindingTest(unittest.TestCase):
    def test_source_binding(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                def git(*args):
                    return subprocess.check_output(['git', *args], stderr=subprocess.PIPE, text=True).strip()
                def commit():
                    git('add', 'a', 'b')
                    git('-c', 'user.name=Audit test', '-c', 'user.email=audit@example.invalid',
                        'commit', '-m', 'fixture')
                    return git('rev-parse', 'HEAD')
                def hashes():
                    return {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ('a', 'b')}
                git('init')
                Path('a').write_text('base'); Path('b').write_text('base')
                base = commit()
                Path('a').write_text('captured'); Path('b').write_text('captured')
                recorded = hashes()
                manifest = {'source_revision': base, 'dirty_file_sha256': recorded}
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    audit_source(manifest)
                self.assertIn('match current files', output.getvalue())
                captured = commit()
                Path('a').write_text('later'); commit()
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    audit_source(manifest)
                self.assertIn('match ancestor ' + captured, output.getvalue())
                # Each blob exists in history, but no single tree contains this pair.
                mixed = {'a': hashlib.sha256(b'base').hexdigest(), 'b': recorded['b']}
                with self.assertRaisesRegex(AssertionError, 'one ancestor tree'):
                    audit_source(dict(manifest, dirty_file_sha256=mixed))
                tampered = dict(recorded, a='0' * 64)
                with self.assertRaisesRegex(AssertionError, 'one ancestor tree'):
                    audit_source(dict(manifest, dirty_file_sha256=tampered))
                print('PASS current bytes, historical tree, mixed-revision rejection, tampered-hash rejection')
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
