"""Paint a large, clean front portrait of a Haras Valley character from its face sheet, with Sunburst, once.

/usr/bin/python3 games/haras_valley/tools/face_portrait.py boy
The portrait is the source the face projection samples (tools/cleanup_face_hair.py --face): the face sheet's front
view is about 300 px across, the portrait about 900. Recorded in references/face-portrait.json before the paid call
(atelier.ai.ledger); never repainted while that record exists.
"""
import base64
import hashlib
import json
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'platform' / 'studio'))
from atelier.ai.ledger import run_once  # noqa: E402
from atelier.env import load, require  # noqa: E402

GAME = Path(__file__).resolve().parents[1]
MODEL, QUALITY, SIZE = 'gpt-image-2.5-sunburst', 'high', '1024x1536'
PROMPT = (
    'Redraw the front view of this character (the top-left face of the sheet) as one large head-and-shoulders '
    'portrait that fills the frame: the head about four fifths of the image width, facing the camera exactly '
    'straight on, perfectly symmetrical, eyes open and looking straight ahead, neutral mouth, the same face, '
    'the same hairstyle, the same colours and the same flat cel-shaded style with clean dark outlines. Both ears '
    'visible. Plain, even, light beige background with nothing else in the frame; no cast shadows, no text, '
    'no vignette.')


def main(character):
    folder = GAME / 'assets' / 'characters' / character / 'references'
    sheet = folder / 'face-six-views.png'
    record = folder / 'face-portrait.json'
    if record.exists():
        print(record, 'exists; the portrait is painted once', flush=True)
        return 0
    load()
    headers = {'Authorization': 'Bearer ' + require('OPENAI_API_KEY')}

    def paint():
        with httpx.Client(timeout=httpx.Timeout(900, connect=30)) as client:
            response = client.post('https://api.openai.com/v1/images/edits', headers=headers,
                                   data={'model': MODEL, 'prompt': PROMPT, 'size': SIZE, 'quality': QUALITY, 'n': '1'},
                                   files=[('image[]', (sheet.name, sheet.read_bytes(), 'image/png'))])
        body = response.json()
        if response.status_code >= 400 or not body.get('data'):
            raise RuntimeError(f'Sunburst HTTP {response.status_code}: {(body.get("error") or {}).get("message", "no image")}')
        png = base64.b64decode(body['data'][0]['b64_json'])
        (folder / 'face-portrait.png').write_bytes(png)
        return {'usage': body.get('usage'), 'output': 'face-portrait.png', 'png_sha256': hashlib.sha256(png).hexdigest()}

    run_once(record, {'model': MODEL, 'quality': QUALITY, 'size': SIZE, 'prompt': PROMPT,
                      'input': {sheet.name: hashlib.sha256(sheet.read_bytes()).hexdigest()},
                      'purpose': f'{character}: the clean front portrait the face projection samples'}, paint)
    print('painted', folder / 'face-portrait.png', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else 'boy'))
