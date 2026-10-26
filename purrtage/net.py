# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Network transport for games on a local network.

Length-prefixed JSON messages over TCP: a reliable, ordered link, which is
exactly what lockstep needs, and what a local network offers effortlessly.

The host also advertises itself over UDP broadcast, so the other machine finds
it without having to type an address.
"""

import json
import socket
import struct
import threading
import time

from . import i18n

try:
    import queue
except ImportError:                      # pragma: no cover
    import Queue as queue

PORT = 50507                 # game port (TCP)
BEACON_PORT = 50508          # advertisement port (UDP, broadcast)
BEACON_PERIOD = 1.0
# A flat refusal when the two versions differ. 2: the start message names the
# map size, and carries the whole map when the host plays one of its own.
# 3: stone, ramparts and tower levels change the simulation itself.
# 4: the handshake exchanges the chosen faction (start carries the host's, the
# client answers with a "hello" carrying its own) before the game starts.
PROTOCOL = 4

# The game signature in the UDP advertisements. The game was called "catwar"
# up to version 1.0; the signature stays the same so that a 1.0 host and a
# newer client keep seeing each other on the local network. This is not a
# leftover from before the rename: it is wire format, and renaming it would
# make the two versions deaf to each other.
#
# Same reasoning for the French keys in the payloads below ("jeu",
# "protocole", "nom"): they belong to the wire format, not to the code.
BEACON_GAME = "catwar"
MAX_MESSAGE = 1 << 20        # guard rail: 1 MiB per message

HEADER = struct.Struct("!I")


def local_ip():
    """This machine's address on the local network, to show it to the other one."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no data is ever sent
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        s.close()


# --------------------------------------------------------------------- link --
class Link(object):
    """An established connection. Reads happen in a separate thread so that
    the game loop never blocks on the network."""

    def __init__(self, sock, peer=None):
        self.sock = sock
        self.peer = peer or sock.getpeername()[0]
        self.inbox = queue.Queue()
        self.alive = True
        self.error = None
        self._send_lock = threading.Lock()
        self._thread = threading.Thread(target=self._read_loop)
        self._thread.daemon = True
        self._thread.start()

    # ------------------------------------------------------------ reading ---
    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _read_loop(self):
        try:
            while self.alive:
                head = self._recv_exact(HEADER.size)
                if head is None:
                    break
                (size,) = HEADER.unpack(head)
                if size <= 0 or size > MAX_MESSAGE:
                    raise ValueError("invalid message size: %d" % size)
                body = self._recv_exact(size)
                if body is None:
                    break
                self.inbox.put(json.loads(body.decode("utf-8")))
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.alive = False

    # ------------------------------------------------------------ writing ---
    def send(self, message):
        if not self.alive:
            return False
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        try:
            with self._send_lock:
                self.sock.sendall(HEADER.pack(len(body)) + body)
            return True
        except Exception as exc:
            self.error = str(exc)
            self.alive = False
            return False

    def poll(self):
        """Every message received since the last call."""
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                return out

    def recv(self):
        """One message if one is waiting, else None. Never blocks.

        The handshake reads a single control message this way and leaves the
        rest of the FIFO untouched, so the first lockstep messages behind it
        are later handed to the session by `poll` instead of being dropped.
        """
        try:
            return self.inbox.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# --------------------------------------------------------------------- host --
class Host(object):
    """Wait for an opponent and advertise on the local network."""

    def __init__(self, name=None, port=PORT, announce=True):
        self.name = name or i18n.t("lan.default_host_name")
        self.port = port
        self.link = None
        self.error = None
        self.ip = local_ip()
        self._stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", port))
        self.sock.listen(1)
        self.sock.settimeout(0.2)
        self._accept = threading.Thread(target=self._accept_loop)
        self._accept.daemon = True
        self._accept.start()
        self._beacon = None
        if announce:
            self._beacon = threading.Thread(target=self._beacon_loop)
            self._beacon.daemon = True
            self._beacon.start()

    def _accept_loop(self):
        while not self._stop.is_set() and self.link is None:
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue
            except Exception as exc:
                self.error = str(exc)
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.link = Link(conn, addr[0])

    def _beacon_loop(self):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # French keys: wire format, see BEACON_GAME above.
        payload = json.dumps({"jeu": BEACON_GAME, "protocole": PROTOCOL,
                              "nom": self.name, "port": self.port}).encode("utf-8")
        while not self._stop.is_set() and self.link is None:
            try:
                udp.sendto(payload, ("255.255.255.255", BEACON_PORT))
            except Exception:
                pass
            self._stop.wait(BEACON_PERIOD)
        udp.close()

    @property
    def connected(self):
        return self.link is not None and self.link.alive

    def close(self):
        self._stop.set()
        try:
            self.sock.close()
        except Exception:
            pass
        if self.link:
            self.link.close()


# ------------------------------------------------------------------- client --
def connect(address, port=PORT, timeout=5.0):
    """Join a host. Returns a link, or raises an explicit error."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((address, port))
    sock.settimeout(None)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return Link(sock, address)


class Browser(object):
    """Listen to the advertisements of the hosts on the local network."""

    def __init__(self, port=BEACON_PORT):
        self.found = {}                   # ip -> {name, port, protocol, seen}
        self.error = None
        self._stop = threading.Event()
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("", port))
            self.sock.settimeout(0.3)
        except Exception as exc:
            self.sock = None
            self.error = str(exc)
            return
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception:
                return
            try:
                info = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if info.get("jeu") != BEACON_GAME:
                continue
            self.found[addr[0]] = {"name": info.get("nom", "?"),
                                   "port": int(info.get("port", PORT)),
                                   "protocol": info.get("protocole"),
                                   "seen": time.time()}

    def hosts(self, max_age=4.0):
        """The hosts seen recently, from the newest to the oldest."""
        now = time.time()
        out = [(ip, d) for ip, d in self.found.items() if now - d["seen"] <= max_age]
        out.sort(key=lambda item: item[0])
        return out

    def close(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
