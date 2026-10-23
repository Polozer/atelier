"""Tiny real Python job for the independent harness adapter; stdlib and declared slots only.

The independent Rust oracle computes its own framed byte workload. This job reads the staged
files and computes that workload itself; it never imports the oracle or its expected bytes.
"""
import json
import os


def run(context):
    def framed(value):
        if isinstance(value, str):
            value = value.encode('utf-8')
        return len(value).to_bytes(8, 'big') + value

    payload = framed('atelier-harness-work/1') + framed(context.params['fixture_params'])
    for name, spec in sorted(context.params['fixture_inputs'].items()):
        payload += framed(name)
        path = context.inputs[name]
        if spec['role'] == 'file':
            payload += framed('absent') if path is None else framed('present') + framed(path.read_bytes())
        elif spec['role'] == 'item':
            payload += framed('item')
            for member in sorted(spec['files']):
                payload += framed((path / member).read_bytes())
        elif spec['role'] == 'reference':
            reference = json.loads(path.read_text(encoding='utf-8'))
            payload += framed('reference') + framed(reference['logical_path']) + framed(reference['class'])
        else:
            raise ValueError('unsupported fixture input role')

    if context.params.get('fixture_fail', False):
        raise RuntimeError('explicit fixture failure')
    for output in context.params['fixture_outputs']:
        value = payload + framed(output['logical_path']) + framed(output['class']) + framed(output['path'])
        target = context.output(output['path'])
        target.write_bytes(value)
        os.chmod(target, output['mode'])
