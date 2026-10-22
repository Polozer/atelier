"""Editor script commandlets keep FBX warnings in the log instead of opening the MessageLog tab."""
from pathlib import Path
from types import SimpleNamespace

from atelier import build


POPUP = '-ini:Engine:[ConsoleVariables]:MessageLog.DisablePopup=1'


def test_every_script_commandlet_starts_with_the_message_log_popup_disabled(tmp_path):
    # A fresh FBX create logs its warnings through FFbxLogger, which opens the MessageLog tab; on Mac the commandlet
    # has no Slate application and asserts CurrentApplication.IsValid(), so the launcher disables the popup.
    ctx = SimpleNamespace(unreal_cmd=tmp_path / 'UnrealEditor-Cmd', uproject=tmp_path / 'Game.uproject')
    for null_rhi in (False, True):
        command = build.UnrealScript(Path('import.py'), 'DONE', null_rhi=null_rhi)
        assert POPUP in command._argv(ctx, ctx.uproject, command.script)
