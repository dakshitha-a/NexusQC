"""A zip built as a stream of bytes rather than assembled in memory.

The two zips that already exist here both build in an io.BytesIO: the
single-job download in server/routes/jobs.py, and the whole-account export
in server/routes/auth.py. The per-job one explains its own choice: /data is
close to full, so writing the zip out to disk and serving the file is not
an option, and one job is small enough that holding it resident is fine.

A project is not one job. A single orbital cube in this repository's own
measurements runs to about seven megabytes, and a study-sized archive of a
dozen such jobs would sit resident in a FastAPI worker thread for the whole
length of the download, once per concurrent download. That is the one place
this feature could take the API process down, so the project download
streams instead: at most one file's worth of bytes is in memory at a time,
whatever the size of the archive.

No new dependency for this. Python's own zipfile already supports writing
to a non-seekable file object, in which case it emits data descriptors
after each member instead of seeking backwards to patch the local header.
All that is missing is an object to write into, which is what _Sink is: it
accumulates whatever zipfile hands it, and the generator drains it after
every step and yields it onward.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterable, Iterator, Union

# Files are read and forwarded in chunks of this size, so a single large
# member (an orbital cube, a BAGEL archive) is never fully resident either.
_CHUNK = 1 << 20


class _Sink:
    """The file-like object zipfile writes into.

    seekable() answering False is the load-bearing part: it is what makes
    zipfile choose the streaming encoding. tell() still has to be honest,
    because zipfile uses the running offset to build the central directory
    at the end, so this counts every byte that passes through.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._pos = 0

    def write(self, data: bytes) -> int:
        self._buf.extend(data)
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def flush(self) -> None:
        pass

    def seekable(self) -> bool:
        return False

    def drain(self) -> bytes:
        out = bytes(self._buf)
        del self._buf[:]
        return out


Entry = tuple[str, Union[bytes, Path]]


def stream_zip(entries: Iterable[Entry]) -> Iterator[bytes]:
    """Yields the bytes of a zip holding `entries`, which are (arcname,
    source) pairs where source is either literal bytes or a path to read.

    `entries` is consumed lazily and may itself be a generator, so a caller
    with a thousand jobs to package does not have to enumerate their paths
    up front.

    Compression is deflate, matching the two existing zips, so an archive
    unpacks identically to a per-job download. A member that disappears
    between being listed and being read is skipped rather than raising:
    quota eviction can remove a job directory at any moment, and a download
    that is already streaming cannot go back and change its status code.
    """
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, source in entries:
            if isinstance(source, (bytes, bytearray)):
                zf.writestr(arcname, bytes(source))
                yield sink.drain()
                continue
            try:
                handle = open(source, "rb")
            except OSError:
                continue
            try:
                with zf.open(arcname, "w") as member:
                    while True:
                        chunk = handle.read(_CHUNK)
                        if not chunk:
                            break
                        member.write(chunk)
                        # Drained inside the read loop, not after it: that
                        # is the whole point. Draining only per member would
                        # still hold an entire cube in the sink.
                        yield sink.drain()
            except OSError:
                continue
            finally:
                handle.close()
            yield sink.drain()
    # The central directory is written by ZipFile.__exit__, after the last
    # member, so this final drain is not optional -- without it the archive
    # streams every byte of content and is still unreadable.
    yield sink.drain()
