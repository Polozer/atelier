"""Serve named listening pages, indexes and candidate media on loopback."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


class Handler(SimpleHTTPRequestHandler):
    """@cc [owner:fontanierh,label:security] review-file-boundary
    Requests MUST expose only named page assets/indexes, generated clip WAVs and
    versioned sequence M4As within the review root. Logs, dotfiles, directories,
    symlink escapes and arbitrary filesystem paths MUST NOT be served. The
    listener MUST use loopback.
    """

    def send_head(self):
        self.media_range = None
        self.immutable = False
        requested = unquote(urlsplit(self.path).path).removeprefix('/') or 'index.html'
        allowed = requested in {'index.html', 'clips.html', 'review.js', 'sequences.js', 'review.css',
                                'manifest.json', 'prepared.json', 'sequences.json'}
        encoded = re.fullmatch(r'sequences/[0-9a-f]{64}/sequence-\d{4}\.m4a', requested) is not None
        allowed = allowed or encoded
        allowed = allowed or re.fullmatch(
            r'(audio/clip|samples/([0-9a-f]{64}/)?sample)-\d+\.wav', requested) is not None
        root = Path(self.directory).resolve()
        path = (root / requested).resolve()
        if not allowed or not path.is_relative_to(root) or not path.is_file():
            self.send_error(404)
            return None
        if encoded:
            return self.sequence_head(path, requested)
        # Pass a normalized path to the standard handler, without query strings.
        self.path = '/' + requested
        return super().send_head()

    def sequence_head(self, path, requested):
        """@cc [owner:fontanierh,label:correctness] streamed-sequence-bytes
        Immutable encoded sequences MUST support bounded single byte ranges and
        cache validation. Invalid/unsatisfiable ranges MUST NOT return unrelated
        bytes. Full and partial bodies MUST match their advertised lengths.
        """
        handle = path.open('rb')
        try:
            return self.sequence_response(handle, requested)
        except BaseException:
            handle.close()
            raise

    def sequence_response(self, handle, requested):
        size = os.fstat(handle.fileno()).st_size
        tag = '"' + requested.replace('/', '-') + '"'
        self.immutable = True
        if self.headers.get('If-None-Match') == tag:
            handle.close()
            self.send_response(304)
            self.send_header('ETag', tag)
            self.end_headers()
            return None
        start, end = 0, size - 1
        selected = self.headers.get('Range')
        if self.headers.get('If-Range', tag) != tag:
            selected = None
        if selected:
            match = re.fullmatch(r'bytes=(\d{0,20})-(\d{0,20})', selected)
            valid = match is not None and any(match.groups())
            if valid:
                first, last = match.groups()
                if first:
                    start, end = int(first), min(int(last), size - 1) if last else size - 1
                else:
                    start, end = max(0, size - int(last)), size - 1
                    valid = int(last) > 0
                valid = valid and 0 <= start <= end < size
            if not valid:
                handle.close()
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return None
            self.media_range = (start, end)
        self.send_response(206 if selected else 200)
        self.send_header('Content-Type', 'audio/mp4')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('ETag', tag)
        if selected:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        handle.seek(start)
        return handle

    def copyfile(self, source, outputfile):
        if self.media_range is None:
            return super().copyfile(source, outputfile)
        remaining = self.media_range[1] - self.media_range[0] + 1
        while remaining:
            block = source.read(min(65536, remaining))
            if not block:
                break
            outputfile.write(block)
            remaining -= len(block)

    def end_headers(self):
        self.send_header('Cache-Control', 'public, max-age=31536000, immutable'
                         if getattr(self, 'immutable', False) else 'no-store')
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
