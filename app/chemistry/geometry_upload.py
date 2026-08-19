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
