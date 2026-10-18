"""Deliver mailbox notifications to an existing Codex session's active turn."""
import json
import os
import subprocess
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from websockets.sync.client import unix_connect
from websockets.exceptions import WebSocketException


class TransportError(RuntimeError):
    pass


class RpcError(TransportError):
    def __init__(self, error):
        super().__init__('Codex rejected the request; board delivery must retry.')
        self.error = error


class Client:
    """A bounded connection to the existing daemon, never a new agent or server."""
    def __init__(self, codex='codex', sock=None, home=None, budget=20):
        self.connection = ExitStack()
        try:
            if not sock:
                sock = daemon_socket(codex, home)
                if not sock:
                    raise TransportError('Codex daemon is unavailable; board cursor retained.')
            self.socket = self.connection.enter_context(
                unix_connect(str(sock), open_timeout=5, close_timeout=1, max_size=2*1024*1024))
        except (OSError, ValueError, KeyError, WebSocketException, subprocess.SubprocessError):
            self.connection.close()
            raise TransportError('Codex connection unavailable; board cursor retained.') from None
        self.sequence = 0
        self.deadline = time.monotonic()+budget

    def send(self, value):
        try:
            self.socket.send(json.dumps(value))
        except (OSError, WebSocketException):
            raise TransportError('Codex transport disconnected; board cursor retained.') from None

    def call(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.send({'id': request_id, 'method': method, 'params': params})
        while time.monotonic() < self.deadline:
            try:
                message = json.loads(self.socket.recv(timeout=max(0, self.deadline-time.monotonic())))
            except (OSError, ValueError, WebSocketException):
                raise TransportError('Codex transport disconnected; board cursor retained.') from None
            if message.get('id') != request_id:
                continue
            if 'error' in message:
                raise RpcError(message['error'])
            return message.get('result', {})
        raise TransportError('Codex delivery timed out; board cursor retained.')

    def __enter__(self):
        try:
            self.call('initialize', {'clientInfo': {'name': 'atelier_board', 'version': '0.1.0'},
                                     'capabilities': {'experimentalApi': True}})
            self.send({'method': 'initialized'})
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def __exit__(self, *_):
        self.close()


def daemon_socket(codex='codex', home=None):
    """The running app-server daemon's socket for one Codex home (default: the inherited one), or None."""
    env = dict(os.environ, CODEX_HOME=str(home)) if home else None
    result = subprocess.run([codex, 'app-server', 'daemon', 'version'], capture_output=True,
                            text=True, timeout=5, check=True, env=env)
    status = json.loads(result.stdout)
    return status['socketPath'] if status.get('status') == 'running' else None


def codex_homes():
    """Candidate Codex homes on this machine: the inherited one, ~/.codex, and ~/.codex-* daemon homes."""
    found = [Path(os.environ['CODEX_HOME'])] if os.environ.get('CODEX_HOME') else []
    found.append(Path.home() / '.codex')
    found += sorted(p for p in Path.home().glob('.codex-*') if (p / 'app-server-daemon').is_dir())
    return list(dict.fromkeys(p.expanduser().resolve() for p in found))


def locate(thread, codex='codex', homes=None):
    """@cc [owner:fontanierh,label:correctness] codex-thread-daemon
    Without an explicit socket or home, delivery MUST use the one running daemon that owns the thread.
    A daemon owns it when thread/read succeeds (any status, including notLoaded); other daemons reject
    it. No owner, or more than one, MUST fail with the board cursor retained, never guess a daemon.
    """
    owners, unreachable, seen = [], False, set()
    for home in codex_homes() if homes is None else homes:
        try:
            sock = daemon_socket(codex, home)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            sock = None
        if not sock:
            unreachable = True
            continue
        if sock in seen:
            continue
        seen.add(sock)
        try:
            # Short read-only probes keep discovery plus delivery inside the listener's 30 s command bound.
            with Client(codex, sock, budget=5) as client:
                client.call('thread/read', {'threadId': thread, 'includeTurns': False})
            owners.append(sock)
        except RpcError:
            continue
        except TransportError:
            unreachable = True
    if len(owners) > 1:
        raise TransportError('Codex thread found in more than one daemon; board cursor retained.')
    if not owners:
        raise TransportError('No running Codex daemon has this thread; board cursor retained.' if not unreachable
                             else 'Codex thread owner unavailable; board cursor retained.')
    return owners[0]


def connect(thread, codex='codex', sock=None, home=None, homes=None):
    """Client for the thread's daemon: an explicit socket, then an explicit home, then the discovered owner."""
    if sock:
        return Client(codex, sock)
    if home:
        return Client(codex, home=home)
    return Client(codex, locate(thread, codex, homes))


def notify(client, thread, message):
    """Steer a busy thread; wake a positively confirmed idle existing thread.

    Never interrupt, resume, spawn, or overwrite a session's settings. A turn
    ending between read and steer gets one fresh status check before retry.
    """
    message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, thread+'\n'+message))
    for attempt in range(2):
        metadata = client.call('thread/read', {'threadId': thread, 'includeTurns': False})['thread']
        status = metadata.get('status', {}).get('type')
        if status == 'active':
            page = client.call('thread/turns/list', {'threadId': thread, 'limit': 1,
                                                   'sortDirection': 'desc', 'itemsView': 'notLoaded'})
            turns = page.get('data', [])
            active = next((turn for turn in turns if turn.get('status') == 'inProgress'), None)
            if not active:
                continue
            try:
                client.call('turn/steer', {'threadId': thread, 'expectedTurnId': active['id'],
                                          'input': [{'type': 'text', 'text': message}], 'clientUserMessageId': message_id})
                return 'steered'
            except RpcError:
                if attempt == 0:
                    continue
                raise
        if status == 'idle':
            try:
                client.call('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': message}],
                                          'clientUserMessageId': message_id})
                return 'woke_idle'
            except RpcError:
                if attempt == 0:
                    continue
                raise
        raise TransportError('Codex session is unavailable; board cursor retained.')
    raise TransportError('Codex turn changed during delivery; board cursor retained for retry.')
