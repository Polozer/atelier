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
            root = Path(directory)
            catalog, web, output = root / 'catalog.json', root / 'web', root / 'output'
            catalog.write_text(json.dumps({'title': 'Test', 'seeds': [1], 'sounds': [
                {'category': 'Footsteps', 'label': 'Walking · smooth concrete',
                 'prompt': 'One walking sequence', 'seconds': 2}]}))
            web.mkdir()
            for name in ('index.html', 'review.js', 'review.css'):
                (web / name).write_text('test')
            manifest = review.prepare(catalog, output, web)
            raw = output / manifest['clips'][0]['file']
            raw.write_bytes(b'synthetic source fixture; decoding mocked below')
            manifest['clips'][0].update(status='ready', audio={'sha256': review.digest(raw)})
            review.write_json(output / 'manifest.json', manifest)
            signal = np.zeros(RATE * 2)
            t = np.arange(RATE // 5) / RATE
            burst = np.sin(2 * np.pi * 700 * t) * np.exp(-t * 35)
            for at in [.3, .9, 1.5]:
                signal[int(at * RATE):int(at * RATE) + len(burst)] = burst
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


if __name__ == '__main__':
    unittest.main()
