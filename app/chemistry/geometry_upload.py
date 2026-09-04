"""Multi-geometry XYZ parsing for uploaded files.

Mirrors `frontend/src/molecule/xyz.ts::parseMultiFrameXyz`'s frame-walking
algorithm (atom-count line, comment line, N atom lines, repeat -- standard
xmol multi-frame convention, no blank-line separator required) so a file
that renders as N frames in the viewer is the same N frames a job draft
sees. The frontend parser is intentionally lenient about a truncated final
frame -- correct for its own use (rendering an already-completed job's own
artifact, which only ever contains what the job itself wrote), but wrong
here: this module parses a file a user just handed the app, so a truncated
or malformed frame is a real input error, not something to silently drop
and carry on from. `parse_multi_frame_xyz` raises `ValueError` with a
message naming the problem instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.chemistry.molecule import _ATOM_LINE_RE


@dataclass
class GeometryFrame:
    name: str
    symbols: list[str] = field(default_factory=list)
    coords: list[list[float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "symbols": self.symbols, "coords": self.coords}


def parse_multi_frame_xyz(text: str) -> list[GeometryFrame]:
    """Parses a multi-frame xmol/XYZ file into one `GeometryFrame` per
    frame. Raises `ValueError` (naming the frame index and the problem) on
    anything short of a complete, well-formed file: a non-numeric or
    non-positive atom-count line, a truncated frame (fewer atom lines than
    declared), a malformed atom line, or a file with no frames at all.
    """
    lines = text.splitlines()
    frames: list[GeometryFrame] = []
    i = 0
    n_lines = len(lines)
    while i < n_lines:
        if not lines[i].strip():
            i += 1
            continue
        count_line = lines[i].strip()
        try:
            n = int(count_line)
        except ValueError:
            raise ValueError(
                f"frame {len(frames)}: expected an atom-count line, got {count_line!r}"
            )
        if n <= 0:
            raise ValueError(f"frame {len(frames)}: atom count must be positive, got {n}")
        if i + 1 >= n_lines:
            raise ValueError(f"frame {len(frames)}: missing comment line")
        comment = lines[i + 1].strip()
        atom_lines = lines[i + 2:i + 2 + n]
        if len(atom_lines) < n:
            raise ValueError(
                f"frame {len(frames)}: declared {n} atoms but only {len(atom_lines)} lines follow"
            )
        symbols: list[str] = []
        coords: list[list[float]] = []
        for j, atom_line in enumerate(atom_lines):
            m = _ATOM_LINE_RE.match(atom_line)
            if not m:
                raise ValueError(f"frame {len(frames)}: malformed atom line {j} ({atom_line!r})")
            sym, x, y, z = m.groups()
            symbols.append(sym)
            coords.append([float(x), float(y), float(z)])
        # Matches xyz.ts's own default exactly (`frame ${frames.length}`,
        # not a computed formula) -- a blank comment line is common and
        # unremarkable in real multi-frame xyz files (e.g. a trajectory
        # exporter that only names frame 0), so this stays consistent with
        # how the frontend already labels the same file.
        name = comment if comment else f"frame {len(frames)}"
        frames.append(GeometryFrame(name=name, symbols=symbols, coords=coords))
        i += 2 + n

    if not frames:
        raise ValueError("no frames found -- expected an atom-count line, a comment line, then atom lines")
    return frames


@dataclass
class GeometrySniff:
    """The classification an uploaded xyz file gets at upload time,
    driving Phase 3's attach semantics: 1 geometry becomes the active
    frame, 2 become a pair (interpolation/NEB endpoints), 3+ become a
    `geometry_set` job. Stored on the upload's file record so attach-time
    doesn't need to re-parse the file to know which branch to take."""
    n_geometries: int
    kind: str  # "single" | "pair" | "set"

    def to_dict(self) -> dict:
        return {"n_geometries": self.n_geometries, "kind": self.kind}


def sniff_xyz_upload(text: str) -> GeometrySniff:
    """Classifies an uploaded xyz file by frame count. Raises the same
    `ValueError` `parse_multi_frame_xyz` would -- sniffing is done by
    actually parsing, not by a cheaper heuristic, so a malformed upload is
    rejected at upload time rather than accepted and failing later at
    attach time."""
    frames = parse_multi_frame_xyz(text)
    n = len(frames)
    kind = "single" if n == 1 else "pair" if n == 2 else "set"
    return GeometrySniff(n_geometries=n, kind=kind)


def parse_pasted_multi_geometry(text: str) -> list[GeometryFrame]:
    """Every geometry in a block of text a user typed or pasted into chat.

    `parse_multi_frame_xyz` above reads a FILE, and holds it to the xmol
    convention exactly: an atom-count line, a comment line, then that many
    atom lines. What people paste into a chat message is not that. They
    paste what they have in front of them -- a title line and a run of
    coordinates, blank line, next title, next run -- with the atom counts
    nowhere, because a human reader does not need them:

        Torsion angle at 0
        C   0.665  0.000  0.000
        ...

        Torsion angle at 10
        C   0.665  0.000  0.000
        ...

    Held to the strict parser first, so a properly formed xmol block pasted
    into chat is read by the same code that reads the file, and only text
    that is not valid xmol is walked leniently here. The lenient walk takes
    each maximal run of atom lines as one geometry and the last non-blank
    line before it as that geometry's title, which is exactly the structure
    above and is also what the run has if the titles are absent (the frames
    are then unnamed, and the coordinate falls back to an image index).

    This exists because the app used to have no way to accept it. A user
    pasted nineteen titled geometries into the chat and was told to put
    them in a file and upload the file instead -- the coordinates were in
    the message being answered. Raises ValueError, like its strict sibling,
    when nothing parseable is there.
    """
    try:
        return parse_multi_frame_xyz(text)
    except ValueError:
        pass

    frames: list[GeometryFrame] = []
    pending_title = ""
    current: GeometryFrame | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if _ATOM_LINE_RE.match(line):
            parts = line.split()
            if current is None:
                current = GeometryFrame(name=pending_title)
                pending_title = ""
            current.symbols.append(parts[0])
            current.coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
            continue
        # Any non-atom line ends the run. A blank one carries no title; a
        # non-blank one is the next geometry's title, and replaces any
        # earlier candidate, so only the line immediately above a run is
        # ever used as its name.
        if current is not None:
            frames.append(current)
            current = None
        if line:
            pending_title = line
    if current is not None:
        frames.append(current)

    if not frames:
        raise ValueError("no coordinates found in this text")
    return frames
