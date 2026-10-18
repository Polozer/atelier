"""Cold saved-package verification; only this editor run publishes the runtime registry."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'world'))
import yori
import unreal as U

from soundbank_package_data import packages, preflight, publish, read, receipt, require
from soundbank_assets import verify


def main():
    plan = preflight(yori.OUT)
    identity = receipt(plan)
    folder = yori.OUT / 'soundbank_import'
    candidate = {**identity, 'packages': packages(yori.GAME / 'unreal/Content')}
    require(read(folder / 'candidate.json') == candidate, 'Missing or stale native import candidate')
    verify(plan)
    require(preflight(yori.OUT) == plan and receipt(plan) == identity
            and packages(yori.GAME / 'unreal/Content') == candidate['packages'], 'Soundbank inputs changed during cold verification')
    publish(folder / 'registry.json', {**{k: plan[k] for k in ('version', 'default', 'catalog_sha256')},
                                     'banks': [row['runtime'] for row in plan['banks']], 'native': candidate})
    U.log('SOUNDBANK VERIFY COMPLETE')


main()
