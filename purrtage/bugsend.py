# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sending bug reports to the relay, and the outbox that holds them meanwhile.

The game only ever talks to one address, the relay's. The relay decides where
a report goes next — an issue, a Discord channel, an e-mail — so a service can
be plugged in or dropped without shipping a new build, and no service key ever
sits inside the game, whose code is public.

A report is always written to disk first (`bugreport.save`). Sending it then
leaves a small ticket in `outbox/`, next to the reports; the ticket goes away
once the relay has taken the report, or has refused it for good. Whatever is
still in the outbox is tried again on the next launch: a player without a
connection loses nothing.

Everything here runs on a background thread and never touches the game: the
results come back through `results()`, which the main loop polls.

Every attempt is written to `send.log`, next to the reports: when a report
does not arrive, that file tells whether it left, and what the relay said.
"""

import datetime
import json
import os
import platform
import queue
import ssl
import threading
import urllib.error
import urllib.request
import uuid

from . import __version__, bugreport, i18n, paths
from .settings import BUG_REPORT_URL

OUTBOX = "outbox"
TIMEOUT = 20                    # seconds, per report
TICKET_EXT = ".json"
LOG_NAME = "send.log"
LOG_MAX = 256 * 1024            # bytes; the previous log is kept as send.log.1

# The outcomes of one attempt.
SENT = "sent"                   # the relay has it
QUEUED = "queued"               # no answer: it stays in the outbox
REJECTED = "rejected"           # the relay refused it: retrying would not help

_results = queue.Queue()
_lock = threading.Lock()        # one ticket is never sent twice at once
_log_lock = threading.Lock()


def log(message):
    """Append one line to `send.log`. Never fails: it is only a diagnosis."""
    try:
        with _log_lock:
            path = os.path.join(bugreport.report_dir(), LOG_NAME)
            if os.path.isfile(path) and os.path.getsize(path) > LOG_MAX:
                os.replace(path, path + ".1")
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("%s  %s\n" % (stamp, message))
    except Exception:
        pass


def _receipt(text):
    """The relay's answer to a report it took: JSON with the report's id."""
    try:
        return bool(json.loads(text).get("id"))
    except Exception:
        return False


def _answer_text(answer):
    """The start of the relay's answer, on one line, for the log."""
    try:
        return answer.read(300).decode("utf-8", "replace").replace("\n", " ")
    except Exception:
        return ""


def report_url():
    """The relay's address. Empty: reports stay on the player's disk.

    `PURRTAGE_REPORT_URL` overrides the built-in one, to try a relay out
    without rebuilding the game. The built-in one only serves the packaged
    game: from the sources, nothing leaves without that variable.
    """
    override = os.environ.get("PURRTAGE_REPORT_URL")
    if override is not None:
        return override.strip()
    return BUG_REPORT_URL.strip() if paths.is_frozen() else ""


def enabled():
    return bool(report_url())


def outbox_dir():
    path = os.path.join(bugreport.report_dir(), OUTBOX)
    os.makedirs(path, exist_ok=True)
    return path


def queue_report(txt_path, png_path, description):
    """Leave a ticket for a report already on disk. Returns its path."""
    name = os.path.splitext(os.path.basename(txt_path))[0]
    ticket = {
        "id": name,
        "report": os.path.basename(txt_path),
        "screenshot": os.path.basename(png_path) if png_path else None,
        "meta": {
            "version": __version__,
            "language": i18n.language(),
            "system": "%s %s" % (platform.system(), platform.release()),
            "install": "frozen" if paths.is_frozen() else "sources",
            "description": (description or "").strip(),
        },
    }
    path = os.path.join(outbox_dir(), name + TICKET_EXT)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ticket, fh, ensure_ascii=False, indent=1)
    return path


def pending():
    """The tickets still waiting, oldest first."""
    folder = outbox_dir()
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
            if n.endswith(TICKET_EXT)]


def _multipart(fields, files):
    """A multipart/form-data body, built by hand: no dependency for one form."""
    boundary = "purrtage-" + uuid.uuid4().hex
    out = []
    for name, value in fields:
        out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\""
                    "\r\n\r\n" % (boundary, name)).encode("utf-8"))
        out.append(value.encode("utf-8") + b"\r\n")
    for name, filename, ctype, data in files:
        out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; "
                    "filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                    % (boundary, name, filename, ctype)).encode("utf-8"))
        out.append(data + b"\r\n")
    out.append(("--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(out), "multipart/form-data; boundary=" + boundary


def _ssl_context():
    """The system's certificates, or certifi's when the package bundles it.

    A packaged Python does not always find the certificates of the system it
    lands on; certifi, when present, carries its own.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def certificate_count():
    """How many certificate authorities HTTPS can check the relay against.

    Zero means every report would fail with "certificate verify failed":
    `--verification` refuses such a package.
    """
    try:
        return _ssl_context().cert_store_stats().get("x509_ca", 0)
    except Exception:
        return 0


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def send(ticket_path, url=None):
    """One attempt at sending one ticket. Returns SENT, QUEUED or REJECTED."""
    url = url or report_url()
    name = os.path.splitext(os.path.basename(ticket_path))[0]
    with _lock:
        if not os.path.isfile(ticket_path):
            return SENT             # another thread got there first
        try:
            with open(ticket_path, encoding="utf-8") as fh:
                ticket = json.load(fh)
            folder = os.path.dirname(os.path.dirname(ticket_path))
            files = [("report", ticket["report"], "text/plain; charset=utf-8",
                      _read(os.path.join(folder, ticket["report"])))]
            shot = ticket.get("screenshot")
            if shot and os.path.isfile(os.path.join(folder, shot)):
                files.append(("screenshot", shot, "image/png",
                              _read(os.path.join(folder, shot))))
        except (OSError, ValueError, KeyError) as exc:
            # The report itself is gone or the ticket is unreadable: there
            # is nothing left to send, ever.
            log("%s: dropped, unreadable (%s)" % (name, exc))
            _discard(ticket_path)
            return REJECTED

        body, ctype = _multipart(
            [("meta", json.dumps(ticket.get("meta", {}), ensure_ascii=False))],
            files)
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": ctype,
            "User-Agent": "Purrtage/%s" % __version__,
        })
        try:
            context = _ssl_context() if url.startswith("https:") else None
            with urllib.request.urlopen(request, timeout=TIMEOUT,
                                        context=context) as answer:
                status, detail = answer.status, _answer_text(answer)
        except urllib.error.HTTPError as exc:
            detail = _answer_text(exc)
            exc.close()
            # 4xx: the relay looked at it and said no — too big, malformed.
            # Except "too many requests" and "timeout", which pass with time.
            if 400 <= exc.code < 500 and exc.code not in (408, 429):
                log("%s: refused by %s, HTTP %d %s" % (name, url, exc.code, detail))
                _discard(ticket_path)
                return REJECTED
            log("%s: kept, %s answered HTTP %d %s" % (name, url, exc.code, detail))
            return QUEUED
        except Exception as exc:
            # no network, DNS, timeout, certificate...
            log("%s: kept, %s unreachable (%s: %s)" % (
                name, url, type(exc).__name__, exc))
            return QUEUED
        # A 200 alone proves nothing: a wrong address, or the login page of a
        # hotel Wi-Fi, answers 200 too. Only the relay hands back an id.
        if not _receipt(detail):
            log("%s: kept, %s answered HTTP %d but is not the relay: %s"
                % (name, url, status, detail))
            return QUEUED
        log("%s: sent to %s, HTTP %d %s" % (name, url, status, detail))
        _discard(ticket_path)
        return SENT


def _discard(ticket_path):
    try:
        os.remove(ticket_path)
    except OSError:
        pass


def _worker(tickets):
    for path in tickets:
        _results.put((path, send(path)))


def send_async(tickets):
    """Send these tickets on a background thread, one after the other."""
    if not enabled() or not tickets:
        return None
    thread = threading.Thread(target=_worker, args=(list(tickets),),
                              name="bug-report-sender", daemon=True)
    thread.start()
    return thread


def flush_async():
    """Retry whatever the outbox still holds: called once at startup."""
    if not enabled():
        return None
    try:
        tickets = pending()
    except OSError:
        return None
    if tickets:
        log("startup: %d report(s) left in the outbox, sending again" % len(tickets))
    return send_async(tickets)


def results():
    """The (ticket, outcome) pairs finished since the last call."""
    done = []
    while True:
        try:
            done.append(_results.get_nowait())
        except queue.Empty:
            return done
