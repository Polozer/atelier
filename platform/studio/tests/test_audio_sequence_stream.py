"""Real HTTP byte ranges, immutable caching and the existing file boundary."""
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from atelier.ai.stable_audio.serve import Handler


@pytest.fixture
def stream():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        name = 'sequences/' + 'a' * 64 + '/sequence-0001.m4a'
        path = root / name
        path.parent.mkdir(parents=True)
        payload = bytes(range(256)) * 4
        path.write_bytes(payload)
        (root / 'sequences.json').write_text('{}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=folder))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}', name, payload
        finally:
            server.shutdown(); thread.join(); server.server_close()


def test_full_head_partial_and_suffix_are_exact(stream):
    base, name, payload = stream
    with urlopen(base + '/' + name) as response:
        assert response.status == 200
        assert response.read() == payload
        assert response.headers['Content-Type'] == 'audio/mp4'
        assert response.headers['Accept-Ranges'] == 'bytes'
        assert 'immutable' in response.headers['Cache-Control']
    for selected, start, end in [('bytes=3-15', 3, 15), ('bytes=1000-', 1000, 1023), ('bytes=-12', 1012, 1023)]:
        with urlopen(Request(base + '/' + name, headers={'Range': selected})) as response:
            assert response.status == 206
            assert response.read() == payload[start:end + 1]
            assert response.headers['Content-Range'] == f'bytes {start}-{end}/1024'
            assert int(response.headers['Content-Length']) == end - start + 1
    with urlopen(Request(base + '/' + name, method='HEAD', headers={'Range': 'bytes=0-1'})) as response:
        assert response.status == 206
        assert response.read() == b''
        assert response.headers['Content-Length'] == '2'


@pytest.mark.parametrize('selected', ['bytes=1024-', 'bytes=5-2', 'bytes=-0', 'bytes=0-1,4-5', 'bytes=-', 'bytes=' + '9' * 100 + '-'])
def test_invalid_ranges_refuse_without_unrelated_bytes(stream, selected):
    base, name, _ = stream
    with pytest.raises(HTTPError) as error:
        urlopen(Request(base + '/' + name, headers={'Range': selected}))
    assert error.value.code == 416
    assert error.value.headers['Content-Range'] == 'bytes */1024'
    assert error.value.read() == b''


def test_cache_revalidation_if_range_and_mutable_manifest(stream):
    base, name, payload = stream
    with urlopen(base + '/' + name) as response:
        tag = response.headers['ETag']
    with pytest.raises(HTTPError) as error:
        urlopen(Request(base + '/' + name, headers={'If-None-Match': tag}))
    assert error.value.code == 304
    with urlopen(Request(base + '/' + name, headers={'Range': 'bytes=0-1', 'If-Range': '"other"'})) as response:
        assert response.status == 200
        assert response.read() == payload
    with urlopen(base + '/sequences.json') as response:
        assert response.headers['Cache-Control'] == 'no-store'
    for path in ('/.sequence-provenance.json', '/sequences/' + 'a' * 64 + '/secret.m4a', '/preview.js'):
        with pytest.raises(HTTPError) as error:
            urlopen(base + path)
        assert error.value.code == 404
