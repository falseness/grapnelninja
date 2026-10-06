"""A local itch.io embed: the game CDN and the game page on two origins.

The game server plays html-classic.itch.zone: it serves the contents of the
itch zip (tools/build-itch-zip.py) under /html/<id>/ and, like the itch CDN,
matches paths case-sensitively and answers 403 (not 404) for folders and
missing files. The host server plays itch.io: it serves
tools/fixtures/fake-itch-host.html with the game URL filled in.

By default the zip is built from the tracked files as they are in the working
tree (so an uncommitted fix is what gets tested); pass rev to build from git.

Usage: python3 tools/itch_harness.py [--rev REV]  (prints both URLs, serves until ^C)
"""
import argparse
import importlib.util
import io
import mimetypes
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parent.parent
HOST_PAGE = Path(__file__).resolve().parent / 'fixtures' / 'fake-itch-host.html'
GAME_PREFIX = '/html/123456/'
GAME_QUERY = '?v=1782253839'

_spec = importlib.util.spec_from_file_location('build_itch_zip', ROOT / 'tools' / 'build-itch-zip.py')
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def worktree_tree(root=ROOT):
    """{path: bytes} of the files tracked at HEAD, read from the working tree."""
    tree = {}
    for path in builder.git_tree('HEAD', root):
        file = root / path
        if file.is_file():
            tree[path] = file.read_bytes()
    return tree


def zip_files(rev=None):
    """Build the itch zip and return its entries as {path: bytes}."""
    tree = builder.git_tree(rev) if rev else worktree_tree()
    blob, report = builder.build(tree)
    if blob is None:
        failed = {k: v['errors'] for k, v in report['checks'].items() if v['status'] == 'FAIL'}
        raise RuntimeError(f'itch zip build failed: {failed}')
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return {name: zf.read(name) for name in zf.namelist() if not name.endswith('/')}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_body(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()


class GameHandler(_Handler):
    """html-classic.itch.zone: exact-case files under GAME_PREFIX, else 403."""
    files = {}
    log = []

    def do_GET(self):
        path = urlsplit(self.path).path
        name = path[len(GAME_PREFIX):] if path.startswith(GAME_PREFIX) else None
        body = self.files.get(name) if name else None
        status = 200 if body is not None else 403
        self.log.append({'path': path, 'status': status})
        if body is None:
            self.send_body(403, b'<h1>403 Forbidden</h1>', 'text/html')
            return
        content_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        if content_type.startswith('text/') or content_type.endswith('javascript'):
            content_type += '; charset=utf-8'
        self.send_body(200, body, content_type)


class HostHandler(_Handler):
    """itch.io: the game page at / and /index.html, nothing else."""
    page = b''

    def do_GET(self):
        if urlsplit(self.path).path in ('/', '/index.html'):
            self.send_body(200, self.page, 'text/html; charset=utf-8')
        else:
            self.send_body(404, b'not found', 'text/plain')


def _serve(handler, add_cleanup):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    add_cleanup(server.server_close)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    add_cleanup(thread.join)
    add_cleanup(server.shutdown)
    return f'http://127.0.0.1:{server.server_port}'


def start_itch_embed(add_cleanup, rev=None):
    """Start both servers; return (host_url, game_origin, game_url, game_log)."""
    game = type('Game', (GameHandler,), {'files': zip_files(rev), 'log': []})
    game_origin = _serve(game, add_cleanup)
    game_url = game_origin + GAME_PREFIX + 'index.html' + GAME_QUERY
    page = HOST_PAGE.read_text().replace('{{GAME_URL}}', game_url).encode()
    host = type('Host', (HostHandler,), {'page': page})
    host_url = _serve(host, add_cleanup) + '/'
    return host_url, game_origin, game_url, game.log


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--rev')
    args = ap.parse_args()
    cleanups = []
    host_url, game_origin, game_url, _ = start_itch_embed(cleanups.append, args.rev)
    print(f'host  {host_url}\ngame  {game_url}', flush=True)
    try:
        Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        for cleanup in reversed(cleanups):
            cleanup()


if __name__ == '__main__':
    main()
