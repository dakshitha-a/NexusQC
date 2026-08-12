"""3D rendering helpers built on py3Dmol, returned as embeddable HTML."""
from __future__ import annotations

import py3Dmol

from app.chemistry.molecule import Molecule


def render_molecule_html(molecule: Molecule, width: int = 500, height: int = 400,
                          style: str = "stick", show_labels: bool = True) -> str:
    view = py3Dmol.view(width=width, height=height)
    view.addModel(molecule.to_xyz_block(), "xyz")
    if style == "stick":
        view.setStyle({"stick": {}, "sphere": {"scale": 0.25}})
    elif style == "ballstick":
        view.setStyle({"stick": {"radius": 0.15}, "sphere": {"scale": 0.3}})
    elif style == "spacefill":
        view.setStyle({"sphere": {}})
    if show_labels:
        # 1-based, matching the Z-matrix/coordinate-scan atom numbering
        # convention used everywhere else in the app.
        for i, (x, y, z) in enumerate(molecule.coords):
            view.addLabel(str(i + 1), {
                "position": {"x": x, "y": y, "z": z},
                "backgroundColor": "white", "backgroundOpacity": 0.6,
                "fontColor": "black", "fontSize": 11, "borderThickness": 0,
                "inFront": True, "showBackground": True,
            })
    view.zoomTo()
    view.setBackgroundColor("0xeeeeee")
    return view._make_html()


def render_cube_html(xyz_block: str, cube_path: str, width: int = 500, height: int = 400,
                      isoval: float = 0.04, color_pos: str = "blue", color_neg: str = "red") -> str:
    """Render a molecular-orbital isosurface from a Gaussian cube file."""
    with open(cube_path) as f:
        cube_data = f.read()
    view = py3Dmol.view(width=width, height=height)
    view.addModel(xyz_block, "xyz")
    view.setStyle({"stick": {}})
    view.addVolumetricData(
        cube_data, "cube",
        {"isoval": isoval, "color": color_pos, "opacity": 0.75},
    )
    view.addVolumetricData(
        cube_data, "cube",
        {"isoval": -isoval, "color": color_neg, "opacity": 0.75},
    )
    view.zoomTo()
    view.setBackgroundColor("0xeeeeee")
    return view._make_html()


def render_vibration_html(molecule: Molecule, mode_vectors: list[list[float]],
                           width: int = 500, height: int = 400) -> str:
    """Render a molecule with arrows depicting a normal-mode displacement."""
    view = py3Dmol.view(width=width, height=height)
    view.addModel(molecule.to_xyz_block(), "xyz")
    view.setStyle({"stick": {}, "sphere": {"scale": 0.25}})
    for (x, y, z), (dx, dy, dz) in zip(molecule.coords, mode_vectors):
        scale = 1.5
        view.addArrow({
            "start": {"x": x, "y": y, "z": z},
            "end": {"x": x + dx * scale, "y": y + dy * scale, "z": z + dz * scale},
            "radius": 0.05,
            "color": "green",
        })
    view.zoomTo()
    view.setBackgroundColor("0xeeeeee")
    return view._make_html()
