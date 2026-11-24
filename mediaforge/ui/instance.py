"""One MediaForge at a time. A second launch (Open with, files dropped on the icon or shortcut) hands its files
to the running window and exits, instead of opening a second window that would fight over the same queue file."""
from __future__ import annotations

import getpass
import json
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name() -> str:
    """Per user, so two people signed in to the same PC each get their own MediaForge."""
    return "MediaForge-" + re.sub(r"[^A-Za-z0-9_.-]", "_", getpass.getuser() or "user")


def hand_over(paths: list, name: str | None = None) -> bool:
    """True if a MediaForge is already running and took `paths` (an empty list just brings it forward)."""
    sock = QLocalSocket()
    sock.connectToServer(name or server_name())
    if not sock.waitForConnected(500):
        return False
    sock.write(json.dumps([str(p) for p in paths]).encode("utf-8") + b"\n")
    sock.waitForBytesWritten(2000)
    # Wait for the reply before hanging up: on Windows a pipe closed straight after writing can lose the data.
    sock.waitForReadyRead(3000)
    sock.disconnectFromServer()
    return True


class Listener(QObject):
    """In the first MediaForge: receives what later launches hand over. opened(list of paths)."""
    opened = Signal(list)

    def __init__(self, name: str | None = None) -> None:
        super().__init__()
        self.server = QLocalServer(self)
        name = name or server_name()
        if not self.server.listen(name):
            QLocalServer.removeServer(name)            # a crash can leave a stale socket file behind (macOS/Linux)
            self.server.listen(name)
        self.server.newConnection.connect(self._accept)

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            buf = bytearray()
            sock.readyRead.connect(lambda s=sock, b=buf: self._read(s, b))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock, buf: bytearray) -> None:
        buf.extend(bytes(sock.readAll()))
        if b"\n" not in buf:
            return                                     # one JSON line per launch; wait for the rest
        sock.write(b"ok\n")                           # tells the other launch it may hang up now
        sock.flush()
        try:
            paths = json.loads(bytes(buf).split(b"\n", 1)[0].decode("utf-8") or "[]")
        except ValueError:
            return
        if isinstance(paths, list):
            self.opened.emit([str(p) for p in paths if isinstance(p, str)])
