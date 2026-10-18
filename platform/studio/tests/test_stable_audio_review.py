"""Listening-library integrity and served-file boundaries, without model inference."""

from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
import wave

from atelier.ai.stable_audio import review
from atelier.ai.stable_audio.serve import Handler


class AudioReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = self.root / 'catalog.json'
        self.catalog.write_text(json.dumps({'title': 'Test', 'seeds': [1, 2], 'sounds': [
            {'label': 'Wood', 'category': 'Footsteps', 'prompt': 'Walking on wood', 'seconds': 1}]}))
        self.web = self.root / 'web'
        self.web.mkdir()
        for name in ('index.html', 'clips.html', 'review.js', 'sequences.js', 'review.css'):
            (self.web / name).write_text('test')
        self.output = self.root / 'library'

    def test_plan_is_repeatable_but_cannot_relabel_existing_audio(self):
        first = review.prepare(self.catalog, self.output, self.web)
        self.assertEqual(first, review.prepare(self.catalog, self.output, self.web))
        self.assertEqual([c['file'] for c in first['clips']], ['audio/clip-0001.wav', 'audio/clip-0002.wav'])
        data = json.loads(self.catalog.read_text())
        data['sounds'][0]['prompt'] = 'Different sound'
        self.catalog.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'different plan'):
            review.prepare(self.catalog, self.output, self.web)

    def make_wav(self, name='sample.wav', frames=44100):
        target = self.root / name
        with wave.open(str(target), 'wb') as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(b'\x01\x00\xff\xff' * frames)
        return target

    def test_modified_seed_or_settings_cannot_be_relabelled_as_original_plan(self):
        manifest = review.prepare(self.catalog, self.output, self.web)
        manifest['clips'][0]['seed'] = 912
        with self.assertRaisesRegex(ValueError, 'modified'):
            review.verify_plan(manifest)
        manifest['steps'] = 99
        with self.assertRaisesRegex(ValueError, 'settings'):
            review.verify_plan(manifest)

    def test_wav_rejects_short_wrong_format_or_truncated_takes(self):
        target = self.make_wav()
        self.assertEqual(review.wav_details(target, 1)['frames'], 44100)
        with self.assertRaisesRegex(ValueError, 'duration'):
            review.wav_details(target, 2)
        target.write_bytes(target.read_bytes()[:-4])
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            review.wav_details(target, 1)

    def test_resume_checks_ready_bytes_and_does_not_replay_failed_takes(self):
        manifest = review.prepare(self.catalog, self.output, self.web)
        target = self.make_wav()
        clip = manifest['clips'][0]
        clip.update(status='ready', audio=review.wav_details(target, 1))
        (self.output / clip['file']).write_bytes(target.read_bytes())
        manifest['clips'][1]['status'] = 'failed'
        review.write_json(self.output / 'manifest.json', manifest)
        with patch.object(review, 'validate_runtime', return_value={}), patch.object(review.subprocess, 'Popen') as child:
            with self.assertRaisesRegex(ValueError, 'requires diagnosis'):
                review.generate(self.output, self.root, self.root / 'logs')
            child.assert_not_called()
            (self.output / clip['file']).write_bytes(self.make_wav('changed.wav').read_bytes()[:-4])
            with self.assertRaisesRegex(ValueError, 'Truncated'):
                review.generate(self.output, self.root, self.root / 'logs')
            child.assert_not_called()

    def completed_library(self):
        manifest = review.prepare(self.catalog, self.output, self.web)
        source = self.make_wav()
        for clip in manifest['clips']:
            (self.output / clip['file']).write_bytes(source.read_bytes())
            clip.update(status='ready', audio=review.wav_details(source, 1))
        review.write_json(self.output / 'manifest.json', manifest)
        return manifest

    def test_complete_resume_skips_runtime_and_manifest_publication(self):
        self.completed_library()
        before = (self.output / 'manifest.json').read_bytes()
        with patch.object(review, 'validate_runtime', side_effect=AssertionError('runtime accessed')), \
                patch.object(review, 'write_json', side_effect=AssertionError('manifest rewritten')), \
                patch.object(review.subprocess, 'Popen', side_effect=AssertionError('inference launched')):
            review.generate(self.output, self.root / 'absent-runtime', self.root / 'logs')
        self.assertEqual((self.output / 'manifest.json').read_bytes(), before)

    def test_ready_validation_reads_only_and_rejects_later_corruption(self):
        manifest = self.completed_library()
        before = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        with patch.object(review, 'validate_runtime', side_effect=AssertionError('runtime accessed')), \
                patch.object(review, 'write_json', side_effect=AssertionError('write')), \
                patch.object(review.subprocess, 'Popen', side_effect=AssertionError('subprocess')):
            result = review.validate_ready(self.output)
        self.assertEqual(result['ready'], 2)
        self.assertEqual(before, {p.relative_to(self.output): p.read_bytes()
                                 for p in self.output.rglob('*') if p.is_file()})
        target = self.output / manifest['clips'][-1]['file']
        target.write_bytes(target.read_bytes()[:-2] + b'\x00\x00')
        with self.assertRaisesRegex(ValueError, 'Previously generated take changed'):
            review.validate_ready(self.output)

    def test_ready_validation_caps_bytes_and_requires_complete_library(self):
        review.prepare(self.catalog, self.output, self.web)
        with self.assertRaisesRegex(ValueError, 'every take'):
            review.validate_ready(self.output)
        self.completed_library()
        with patch.object(review, 'MAX_VALIDATION_BYTES', 1), \
                patch.object(review, 'wav_details', side_effect=AssertionError('decoded over budget')):
            with self.assertRaisesRegex(ValueError, 'total byte budget'):
                review.validate_ready(self.output)

    def test_ready_validation_rejects_manifest_symlink(self):
        self.completed_library()
        path = self.output / 'manifest.json'
        original = self.root / 'saved-manifest.json'
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaises(OSError):
            review.validate_ready(self.output)

    def test_ready_validation_detects_manifest_change(self):
        self.completed_library()
        path = self.output / 'manifest.json'
        original = review.wav_details
        def changed(*args):
            details = original(*args)
            path.write_bytes(path.read_bytes() + b' ')
            return details
        with patch.object(review, 'wav_details', changed):
            with self.assertRaisesRegex(ValueError, 'manifest changed'):
                review.validate_ready(self.output)

    def test_streamed_wav_validation_never_reads_a_complete_large_take(self):
        target = self.make_wav(frames=44100 * 3)
        original = wave.Wave_read.readframes
        sizes = []
        def read(handle, count):
            sizes.append(count)
            return original(handle, count)
        with patch.object(wave.Wave_read, 'readframes', read):
            details = review.wav_details(target, 3)
        self.assertEqual(details['frames'], 44100 * 3)
        self.assertTrue(len(sizes) > 1 and max(sizes) <= 16384)

    def test_server_rejects_logs_directories_traversal_and_symlink_escape(self):
        review.prepare(self.catalog, self.output, self.web)
        (self.output / 'private.log').write_text('private')
        (self.output / 'audio/clip-9999.wav').symlink_to(self.catalog)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(self.output)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        for asset in ['/', '/clips.html', '/sequences.js']:
            with urlopen(base + asset, timeout=2) as response:
                self.assertEqual(response.status, 200)
        for path in ['/private.log', '/audio/', '/../catalog.json', '/%2e%2e/catalog.json', '/audio/clip-9999.wav', '/.writer.lock']:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(base + path, timeout=2)
            self.assertEqual(error.exception.code, 404)

    def test_limited_resume_checks_later_ready_take_before_any_generation_or_manifest_write(self):
        catalog = json.loads(self.catalog.read_text())
        catalog['seeds'] = [1, 2, 3]
        self.catalog.write_text(json.dumps(catalog))
        manifest = review.prepare(self.catalog, self.output, self.web)
        source = self.make_wav()
        later = manifest['clips'][2]
        later.update(status='ready', audio=review.wav_details(source, 1))
        target = self.output / later['file']
        target.write_bytes(source.read_bytes()[:-2] + b'\x00\x00')
        review.write_json(self.output / 'manifest.json', manifest)
        before = (self.output / 'manifest.json').read_bytes()
        with patch.object(review, 'validate_runtime', return_value={}), patch.object(review.subprocess, 'Popen') as child:
            with self.assertRaisesRegex(ValueError, 'Previously generated take changed'):
                review.generate(self.output, self.root, self.root / 'logs', limit=1)
            child.assert_not_called()
        self.assertEqual((self.output / 'manifest.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
