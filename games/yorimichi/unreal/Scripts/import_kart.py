"""Import the go-kart (assets/vehicles/kart) into /Game/Japan/Kart on M_Village.

UDrivingComponent loads the three meshes: the body with its origin on the ground, one wheel whose axle is +Y, and
the steering wheel whose hub is the origin and whose plane faces +X.
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'world')); import yori  # noqa: E402  (build/yorimichi = yori.OUT)
import json
import sys
from pathlib import Path

import unreal

HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
from import_village import import_mesh

OUT = yori.OUT / 'kart'
unreal.SystemLibrary.execute_console_command(None, 'Interchange.FeatureFlags.Import.FBX 0')
material = unreal.EditorAssetLibrary.load_asset('/Game/Japan/Materials/M_Village'); assert material
manifest = json.loads((OUT / 'manifest.json').read_text())
report = {}
for name in ('SM_Kart_Body', 'SM_Kart_Seat', 'SM_Kart_Wheel', 'SM_Kart_SteeringWheel'):
    entry = manifest[name]
    mesh = import_mesh(OUT / 'assets' / (name + '.fbx'), '/Game/Japan/Kart', name); mesh.set_material(0, material)
    b = mesh.get_bounding_box()
    assert abs(b.max.x - entry['max'][0] * 100) < .3, (name, 'axis/scale', b.max)
    unreal.EditorAssetLibrary.save_loaded_asset(mesh)
    report[name] = {'min': [b.min.x, b.min.y, b.min.z], 'max': [b.max.x, b.max.y, b.max.z],
                    'triangles': entry['triangles']}
(OUT / 'import-report.json').write_text(json.dumps(report, indent=2) + '\n')
unreal.log('KART IMPORT COMPLETE')
