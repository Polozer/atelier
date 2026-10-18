"""Contact timing and loop seams, using synthetic signals only."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import wave

import pytest

np = pytest.importorskip('numpy')
from atelier.ai.stable_audio.prepare_samples import RATE, contacts, loop_candidate, write_sample  # noqa: E402
from atelier.ai.stable_audio import prepare_samples, review  # noqa: E402


class PreparedAudioTests(unittest.TestCase):
    def write_raw(self, path, signal):
        times = np.arange(round(len(signal) * 44100 / RATE)) * RATE / 44100
        mono = np.interp(times, np.arange(len(signal)), signal)
        stereo = np.repeat(np.rint(mono * 30000).astype('<i2')[:, None], 2, axis=1)
        with wave.open(str(path), 'wb') as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(stereo.tobytes())
        return review.wav_details(path, len(signal) / RATE)

    def bank_fixture(self, directory):
        root = Path(directory)
        catalog, web, output = root / 'catalog.json', root / 'web', root / 'output'
        catalog.write_text(json.dumps({'title': 'Test', 'seeds': [1], 'sounds': [
            {'category': 'Footsteps', 'label': 'Walking · smooth concrete',
             'prompt': 'One walking sequence', 'seconds': 2}]}))
        web.mkdir()
        for name in ('index.html', 'review.js', 'preview.js', 'review.css'):
            (web / name).write_text('test')
        manifest = review.prepare(catalog, output, web)
        raw = output / manifest['clips'][0]['file']
        signal = np.zeros(RATE * 2)
        t = np.arange(RATE // 5) / RATE
        burst = np.sin(2 * np.pi * 700 * t) * np.exp(-t * 35)
        for at in [.3, .9, 1.5]:
            signal[int(at * RATE):int(at * RATE) + len(burst)] = burst
        manifest['clips'][0].update(status='ready', audio=self.write_raw(raw, signal))
        review.write_json(output / 'manifest.json', manifest)
        return output, raw, signal

    def test_each_contact_keeps_attack_and_excludes_following_step(self):
        samples = np.zeros(RATE * 3)
        times = [.3, .9, 1.5, 2.1]
        for at in times:
            t = np.arange(int(.2 * RATE)) / RATE
            samples[int(at * RATE):int(at * RATE) + len(t)] = .8 * np.sin(2 * np.pi * 800 * t) * np.exp(-35 * t)
        spans = contacts(samples)
        self.assertEqual(len(spans), 4)
        for (start, end, peak), at in zip(spans, times):
            self.assertLessEqual(start / RATE, at)
            self.assertLess(at - start / RATE, .015)
            self.assertGreater(peak, start)
            self.assertLess(end / RATE, at + .3)
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])))

    def test_silence_is_not_a_footfall_or_loop(self):
        samples = np.zeros(RATE * 4)
        self.assertEqual(contacts(samples), [])
        with self.assertRaises(ValueError):
            loop_candidate(samples, 2)

    def test_circular_crossfade_joins_adjacent_source_samples(self):
        t = np.arange(RATE * 5) / RATE
        samples = .4 * np.sin(2 * np.pi * 97.3 * t) + .1 * np.sin(2 * np.pi * 271.1 * t)
        loop, start, end, overlap = loop_candidate(samples, 2)
        self.assertEqual(len(loop), end - start - overlap)
        self.assertAlmostEqual(loop[0], samples[start + overlap])
        self.assertAlmostEqual(loop[-1], samples[start + overlap - 1])
        self.assertLess(abs(loop[0] - loop[-1]), .03)

    def test_one_shots_are_mono_48k_with_zero_edges_and_headroom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'contact.wav'
            t = np.arange(RATE // 3) / RATE
            samples = .2 + np.sin(2 * np.pi * 137 * t) * np.exp(-25 * t)
            result = write_sample(path, samples)
            with wave.open(str(path), 'rb') as handle:
                self.assertEqual((handle.getnchannels(), handle.getframerate(), handle.getsampwidth()), (1, 48000, 2))
                pcm = np.frombuffer(handle.readframes(handle.getnframes()), '<i2')
            self.assertEqual((pcm[0], pcm[-1]), (0, 0))
            self.assertLessEqual(np.abs(pcm.astype(float)).max(), 32767 * 10 ** (-3 / 20) + 1)
            self.assertEqual(result['frames'], len(samples))

    def test_interrupted_new_processor_preserves_published_bank_and_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            output, _, signal = self.bank_fixture(directory)
            with patch.object(prepare_samples, 'read_mono', return_value=signal):
                prepare_samples.prepare(output)
                previous = (output / 'prepared.json').read_bytes()
                bank = json.loads(previous)
                old_audio = {c['file']: review.digest(output / c['file']) for c in bank['clips']}
                real_digest = review.digest
                def different_processor(path):
                    return '1' * 64 if Path(path).suffix == '.py' else real_digest(path)
                with patch.object(prepare_samples, 'digest', side_effect=different_processor), \
                        patch.object(prepare_samples, 'write_sample', side_effect=RuntimeError('interrupted')) as writer:
                    with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                        prepare_samples.prepare(output)
                self.assertNotIn(writer.call_args.args[0].relative_to(output.resolve()).as_posix(), old_audio)
                self.assertEqual((output / 'prepared.json').read_bytes(), previous)
                self.assertEqual({p: real_digest(output / p) for p in old_audio}, old_audio)

    def test_changed_ready_audio_same_plan_cannot_overwrite_published_bank_on_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            output, raw, signal = self.bank_fixture(directory)
            with patch.object(prepare_samples, 'read_mono', return_value=signal):
                prepare_samples.prepare(output)
            previous = (output / 'prepared.json').read_bytes()
            bank = json.loads(previous)
            old_audio = {c['file']: review.digest(output / c['file']) for c in bank['clips']}
            manifest = json.loads((output / 'manifest.json').read_text())
            changed = signal.copy()
            t = np.arange(RATE // 5) / RATE
            changed[int(.3 * RATE):int(.5 * RATE)] = np.sin(2 * np.pi * 1700 * t) * np.exp(-t * 35)
            manifest['clips'][0]['audio'] = self.write_raw(raw, changed)
            review.verify_plan(manifest)  # Same prompt, seed, settings and plan.
            self.assertEqual(manifest['plan_hash'], bank['raw_plan_hash'])
            self.assertEqual(review.digest(Path(prepare_samples.__file__)), bank['processing_sha256'])
            review.write_json(output / 'manifest.json', manifest)
            original_write = prepare_samples.write_sample
            created = []
            def interrupt_after_first(path, samples, loop=False):
                if created:
                    raise RuntimeError('interrupted after publishing one new sample')
                created.append(path)
                return original_write(path, samples, loop=loop)
            with patch.object(prepare_samples, 'read_mono', return_value=changed), \
                    patch.object(prepare_samples, 'write_sample', side_effect=interrupt_after_first):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    prepare_samples.prepare(output)
            self.assertNotIn(created[0].relative_to(output.resolve()).as_posix(), old_audio)
            self.assertTrue(created[0].is_file())
            self.assertEqual((output / 'prepared.json').read_bytes(), previous)
            self.assertEqual({p: review.digest(output / p) for p in old_audio}, old_audio)

    def test_same_sample_identity_reuses_exact_bytes_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.wav'
            samples = np.sin(np.arange(RATE // 4) * .13)
            first = write_sample(path, samples)
            before = path.stat()
            self.assertEqual(write_sample(path, samples), first)
            self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns), (before.st_ino, before.st_mtime_ns))
            path.write_bytes(b'corrupted existing sample')
            with self.assertRaisesRegex(ValueError, 'immutable namespace'):
                write_sample(path, samples)
            self.assertEqual(path.read_bytes(), b'corrupted existing sample')


if __name__ == '__main__':
    unittest.main()
