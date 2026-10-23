"""Immutable native finishing keeps all operations; only explicit shader package literals move."""
import ast
import importlib.util
from pathlib import Path

import pytest

PATH=Path(__file__).parent/'native/prepare_gondola_native.py'
spec=importlib.util.spec_from_file_location('gondola_native_host_test',PATH)
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)


def test_selected_native_finishing_keeps_complete_body_and_order():
    source=(host.GAME/'unreal/Scripts/import_gondola.py').read_text()
    original=next(node for node in ast.parse(source).body if isinstance(node,ast.For) and isinstance(node.target,ast.Tuple))
    selected=ast.parse(host.finishing(source,'selected')).body[0]
    assert [ast.dump(node,include_attributes=False) for node in selected.body]==[ast.dump(node,include_attributes=False) for node in original.body]
    assert [arg.arg for arg in selected.args.args]==['folder','dest','names']


def test_shader_namespace_mapping_is_finite_and_reversible():
    source=(host.GAME/'unreal/Scripts/import_gondola.py').read_text()
    material=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='material')
    text=ast.unparse(material)
    actual=host.material_namespace(text,'/Game/AtelierValidation/GondolaAtomicNative_0123456789ab')
    assert '/Game/Gondola/' not in actual
    assert actual.count('/Game/AtelierValidation/GondolaAtomicNative_0123456789ab/Textures')==2
    with pytest.raises(ValueError,match='literals changed'):
        host.material_namespace(text.replace('/Game/Gondola/Materials','/Game/Other/Materials'),'/Game/Fixture')
