"""Ancestry policy regressions against an isolated Git graph."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import build_playgama as builder


class BuilderTests(unittest.TestCase):
    def test_ancestry_policies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode().strip()
            git('init', '-b', 'playgama2')
            git('config', 'user.email', 'test@example.invalid')
            git('config', 'user.name', 'Test')
            (root/'index.html').write_text('<!doctype html>')
            (root/'playgama-bridge-config.json').write_text('{}')
            git('add', '.')
            git('commit', '-m', 'baseline')
            base = git('rev-parse', 'HEAD')
            git('checkout', '-b', 'repair')
            git('commit', '--allow-empty', '-m', 'repair')
            repair = git('rev-parse', 'HEAD')
            git('checkout', '-b', 'unrelated', base)
            git('commit', '--allow-empty', '-m', 'unrelated')
            unrelated = git('rev-parse', 'HEAD')
            with patch.object(builder, 'ROOT', root):
                self.assertEqual(builder.runtime(repair, base)[0], repair)
                print('PASS explicit baseline accepts repair descendant')
                for rejected in (unrelated, 'missing-baseline'):
                    with self.assertRaises(subprocess.CalledProcessError):
                        builder.runtime(repair, rejected)
                    print('PASS rejected baseline ' + rejected)
                self.assertEqual(builder.runtime(base)[0], base)
                with self.assertRaises(subprocess.CalledProcessError):
                    builder.runtime(repair)
                print('PASS default playgama2 behavior accepts contained revision and rejects repair descendant')

    def test_bundle_rejects_unsupported_local_references(self):
        config = {'playgama-bridge-config.json': b'{}'}
        head = '<meta charset="UTF-8"><script src="%s" async></script>' % builder.SDK_URL
        packed = builder.bundle({**config, 'index.html': (head + '<script src="a.js"></script>').encode(), 'a.js': b'A()'})
        self.assertEqual(packed['index.html'].decode(), head + '<script>\nA()\n</script>')
        print('PASS plain script src inlined; SDK URL kept external')
        for markup in ('<link rel="stylesheet" href="style.css">', '<script defer src="a.js"></script>',
                       '<script type="module" src="a.js"></script>', '<img src="a.png">'):
            files = {**config, 'index.html': (head + markup).encode(), 'a.js': b'A()', 'style.css': b'', 'a.png': b''}
            with self.assertRaises(ValueError) as raised:
                builder.bundle(files)
            print('PASS rejected ' + markup + ': ' + type(raised.exception).__name__ + ': ' + str(raised.exception))


if __name__ == '__main__':
    unittest.main()
