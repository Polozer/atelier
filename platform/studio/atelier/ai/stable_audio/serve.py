"""Serve only the listening page, manifest and WAVs on loopback, behind Tailscale Serve."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


class Handler(SimpleHTTPRequestHandler):
    """@cc [owner:fontanierh,label:security] review-file-boundary
    Requests MUST expose only the named page assets, manifest and generated clip
    WAVs within the review root. Logs, dotfiles, directories, symlink escapes and
    arbitrary filesystem paths MUST NOT be served. The listener MUST use loopback.
    """

    def send_head(self):
        requested = unquote(urlsplit(self.path).path).removeprefix('/') or 'index.html'
        allowed = requested in {'index.html', 'review.js', 'preview.js', 'review.css', 'manifest.json', 'prepared.json'}
        allowed = allowed or re.fullmatch(
            r'(audio/clip|samples/([0-9a-f]{64}/)?sample)-\d+\.wav', requested) is not None
        root = Path(self.directory).resolve()
        path = (root / requested).resolve()
        if not allowed or not path.is_relative_to(root) or not path.is_file():
            self.send_error(404)
            return None
        # Pass a normalized path to the standard handler, without query strings.
        self.path = '/' + requested
        return super().send_head()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; media-src 'self'; object-src 'none'; frame-ancestors 'none'")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8794)
    args = parser.parse_args()
    handler = partial(Handler, directory=str(args.root.resolve()))
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        print(f'Audio review listening on loopback port {args.port}', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
