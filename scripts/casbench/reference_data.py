"""Geometries, reference active spaces and theoretical best estimates.

Offline by design. The QUEST database is not distributed as a bulk download,
and this repository's existing discipline for reference data -- the Basis Set
Exchange integration is fully offline -- is the same: what the benchmark
measures against is committed here, with a citation per value, so a run is
reproducible without a network and a reviewer can check any number against its
source.

Every excitation energy is a vertical transition from the ground-state
geometry given here, in eV.

Sources
-------
[QUEST]   Loos, Scemama, Blondel, Garniron, Caffarel and Jacquemin,
          "A Mountaineering Strategy to Excited States: Highly Accurate
          Reference Energies and Benchmarks", J. Chem. Theory Comput. 2018,
          14, 4360-4379.
[QUESTDB] Veril, Scemama, Caffarel, Lipparini, Boggio-Pasqua, Loos and
          Jacquemin, "QUESTDB: A database of highly accurate excitation
          energies for the electronic structure community", WIREs Comput.
          Mol. Sci. 2021, 11, e1517.
[Thiel]   Schreiber, Silva-Junior, Sauer and Thiel, "Benchmarks for
          electronically excited states: CASPT2, CC2, CCSD, and CC3",
          J. Chem. Phys. 2008, 128, 134110.
[Roos]    Roos, Andersson, Fulscher, Malmqvist, Serrano-Andres, Pierloot and
          Merchan, "Multiconfigurational Perturbation Theory: Applications in
          Electronic Spectroscopy", Adv. Chem. Phys. 1996, 93, 219-331.
[Ang]     Angeli, "On the nature of the pi->pi* ionic excited states",
          J. Comput. Chem. 2009, 30, 1319-1333.

The "reference space" column is the active space most commonly used for the
molecule in the multireference literature, not a unique right answer. It is
what the recommendation is compared against, and where sources disagree the
disagreement is noted rather than resolved.
"""
from __future__ import annotations

# name -> (symbols, coords in angstrom, charge, multiplicity)
GEOMETRIES = {
    "water": (
        ["O", "H", "H"],
        [[0.0000, 0.0000, 0.1173], [0.0000, 0.7572, -0.4692],
         [0.0000, -0.7572, -0.4692]], 0, 1),
    "methane": (
        ["C", "H", "H", "H", "H"],
        [[0.0, 0.0, 0.0], [0.6276, 0.6276, 0.6276], [-0.6276, -0.6276, 0.6276],
         [-0.6276, 0.6276, -0.6276], [0.6276, -0.6276, -0.6276]], 0, 1),
    "N2": (["N", "N"], [[0, 0, 0], [0, 0, 1.0977]], 0, 1),
    "O2": (["O", "O"], [[0, 0, 0], [0, 0, 1.2075]], 0, 3),
    "ethylene": (
        ["C", "C", "H", "H", "H", "H"],
        [[0.0, 0.0, 0.6695], [0.0, 0.0, -0.6695], [0.0, 0.9289, 1.2321],
         [0.0, -0.9289, 1.2321], [0.0, 0.9289, -1.2321], [0.0, -0.9289, -1.2321]],
        0, 1),
    "butadiene": (
        ["C", "C", "C", "C", "H", "H", "H", "H", "H", "H"],
        [[-1.8300, -0.3600, 0.0], [-0.6100, 0.1800, 0.0], [0.6100, -0.1800, 0.0],
         [1.8300, 0.3600, 0.0], [-2.7100, 0.2700, 0.0], [-2.0000, -1.4300, 0.0],
         [-0.4400, 1.2500, 0.0], [0.4400, -1.2500, 0.0], [2.0000, 1.4300, 0.0],
         [2.7100, -0.2700, 0.0]], 0, 1),
    "benzene": (
        ["C", "H"] * 6,
        [[1.3970, 0.0000, 0.0], [2.4810, 0.0000, 0.0],
         [0.6985, 1.2098, 0.0], [1.2405, 2.1486, 0.0],
         [-0.6985, 1.2098, 0.0], [-1.2405, 2.1486, 0.0],
         [-1.3970, 0.0000, 0.0], [-2.4810, 0.0000, 0.0],
         [-0.6985, -1.2098, 0.0], [-1.2405, -2.1486, 0.0],
         [0.6985, -1.2098, 0.0], [1.2405, -2.1486, 0.0]], 0, 1),
    "formaldehyde": (
        ["C", "O", "H", "H"],
        [[0.0, 0.0, -0.5295], [0.0, 0.0, 0.6755], [0.0, 0.9400, -1.1000],
         [0.0, -0.9400, -1.1000]], 0, 1),
    "acetone": (
        ["C", "O", "C", "C", "H", "H", "H", "H", "H", "H"],
        [[0.0000, 0.0000, 0.5900], [0.0000, 0.0000, 1.8100],
         [0.0000, 1.2900, -0.1900], [0.0000, -1.2900, -0.1900],
         [0.0000, 2.1100, 0.5300], [0.8800, 1.3600, -0.8400],
         [-0.8800, 1.3600, -0.8400], [0.0000, -2.1100, 0.5300],
         [0.8800, -1.3600, -0.8400], [-0.8800, -1.3600, -0.8400]], 0, 1),
    "acrolein": (
        ["C", "C", "C", "O", "H", "H", "H", "H"],
        [[-1.8110, -0.1930, 0.0], [-0.5460, 0.3800, 0.0], [0.6200, -0.4300, 0.0],
         [1.7770, -0.0640, 0.0], [-2.6970, 0.4310, 0.0], [-1.9200, -1.2710, 0.0],
         [-0.4390, 1.4610, 0.0], [0.4460, -1.5210, 0.0]], 0, 1),
    "formamide": (
        ["N", "C", "O", "H", "H", "H"],
        [[-1.1450, 0.2000, 0.0], [0.0000, -0.4700, 0.0], [1.0900, 0.1100, 0.0],
         [-0.0900, -1.5600, 0.0], [-1.1800, 1.2100, 0.0], [-2.0100, -0.3100, 0.0]],
        0, 1),
    "pyrrole": (
        ["N", "C", "C", "C", "C", "H", "H", "H", "H", "H"],
        [[0.0, 0.0, 1.1400], [0.0, 1.1210, 0.3390], [0.0, -1.1210, 0.3390],
         [0.0, 0.7130, -0.9660], [0.0, -0.7130, -0.9660], [0.0, 0.0, 2.1490],
         [0.0, 2.1250, 0.7370], [0.0, -2.1250, 0.7370], [0.0, 1.3560, -1.8330],
         [0.0, -1.3560, -1.8330]], 0, 1),
    "furan": (
        ["O", "C", "C", "C", "C", "H", "H", "H", "H"],
        [[0.0, 0.0, 1.1630], [0.0, 1.0980, 0.3450], [0.0, -1.0980, 0.3450],
         [0.0, 0.7130, -0.9450], [0.0, -0.7130, -0.9450], [0.0, 2.0210, 0.9010],
         [0.0, -2.0210, 0.9010], [0.0, 1.3580, -1.8120],
         [0.0, -1.3580, -1.8120]], 0, 1),
    "pyridine": (
        ["N", "C", "C", "C", "C", "C", "H", "H", "H", "H", "H"],
        [[0.0, 0.0, 1.4160], [0.0, 1.1400, 0.7100], [0.0, -1.1400, 0.7100],
         [0.0, 1.1950, -0.6820], [0.0, -1.1950, -0.6820], [0.0, 0.0, -1.3800],
         [0.0, 2.0500, 1.2900], [0.0, -2.0500, 1.2900], [0.0, 2.1400, -1.2100],
         [0.0, -2.1400, -1.2100], [0.0, 0.0, -2.4650]], 0, 1),
    # Uracil and o-nitrophenol were added on 2026-09-02, after they were used
    # as a spot check and turned into the motivating cases for the refinement
    # tier. Both are kept so the feature keeps being tested against what
    # prompted it. Planar heavy-atom frames, from PubChem.
    # uracil (O=c1cc[nH]c(=O)[nH]1): C4 N2 O2 H4, 58 electrons, heavy-atom
    # out-of-plane RMS 0.0000 A. PubChem, rotated so the ring lies in z=0.
    "uracil": (
        ["C", "C", "N", "C", "O", "N", "C", "O", "H", "H", "H", "H"],
        [[-1.1968, 1.0690, 0.0], [-0.0222, 1.7033, 0.0], [1.1520, 1.0044, 0.0],
         [1.2208, -0.3635, 0.0], [2.2924, -0.9595, 0.0], [0.0193, -1.0143, 0.0],
         [-1.2053, -0.4080, 0.0], [-2.2602, -1.0314, 0.0], [-2.1512, 1.5774, 0.0],
         [0.0525, 2.7860, 0.0], [2.0427, 1.4890, 0.0], [0.0409, -2.0215, 0.0]],
        0, 1),
    # o-nitrophenol (O=[N+]([O-])c1ccccc1O): C6 N O3 H5, 72 electrons, heavy-atom
    # out-of-plane RMS 0.0000 A -- the nitro group is coplanar with the ring,
    # held there by the intramolecular hydrogen bond, which is what makes its
    # pi system larger than the ring's alone.
    "o-nitrophenol": (
        ["C", "C", "C", "C", "C", "C", "N", "O", "O", "O", "H", "H", "H", "H", "H"],
        [[-1.8296, -1.4121, 0.0], [-2.4997, -0.1891, 0.0], [-1.7788, 1.0066, 0.0],
         [-0.3836, 0.9887, 0.0], [0.2914, -0.2400, 0.0], [-0.4337, -1.4434, 0.0],
         [1.7545, -0.2983, 0.0], [2.3704, 0.7804, 0.0], [2.2955, -1.4128, 0.0],
         [0.2136, 2.2201, 0.0], [-2.3955, -2.3413, 0.0], [-3.5873, -0.1643, 0.0],
         [-2.3073, 1.9575, 0.0], [0.0699, -2.4083, 0.0], [1.1888, 2.1176, 0.0]],
        0, 1),
    "p-benzoquinone": (
        ["C", "C", "C", "C", "C", "C", "O", "O", "H", "H", "H", "H"],
        [[0.0000, 0.0000, 1.4750], [0.0000, 1.2360, 0.7060],
         [0.0000, -1.2360, 0.7060], [0.0000, 1.2360, -0.7060],
         [0.0000, -1.2360, -0.7060], [0.0000, 0.0000, -1.4750],
         [0.0000, 0.0000, 2.6960], [0.0000, 0.0000, -2.6960],
         [0.0000, 2.1690, 1.2560], [0.0000, -2.1690, 1.2560],
         [0.0000, 2.1690, -1.2560], [0.0000, -2.1690, -1.2560]], 0, 1),

    # Non-planar heteroatoms, added 2026-09-04. Every molecule above carrying a
    # lone pair is planar and carries it on a carbonyl or nitro oxygen, and the
    # two constants that decide whether an orbital is called a lone pair or a
    # sigma bond (LONE_PAIR_OVER_SIGMA and LONE_PAIR_AMBIGUOUS in
    # `app/chemistry/cas/refine.py`) were set against exactly two of them. The
    # user who raised the problem put it as: some n orbitals appear as a mix of
    # n and sigma, so a mathematical threshold may miss them and label them
    # something else. These are the cases that threshold has never seen.
    #
    # A pyramidal nitrogen and a bent divalent sulfur are the point. Measured
    # here, the planarity test at the heteroatom gives 0.373 for ammonia and
    # 0.451 for methylamine, both well past the 0.25 cut, so neither emits a pi
    # target at all and the whole pool is lone pairs and sigma bonds. Sulfur
    # additionally puts the lone pair in a second-row valence shell, where the
    # sp-hybrid reference of section 4.3 was reasoned about for first-row
    # atoms only.
    #
    # Geometries optimised at RHF/def2-SVP with geomeTRIC from an RDKit
    # starting structure, so they are stationary points at a stated level
    # rather than force-field guesses. They are not taken from a paper, and
    # nothing here is scored against an excitation energy, so that is
    # sufficient: what these molecules test is which orbitals get selected and
    # what they are called.
    "hydrogen_sulfide": (
        ["S", "H", "H"],
        [[0.0109, 0.6066, 0.0000], [-0.9813, -0.2857, 0.0000],
         [0.9704, -0.3209, 0.0000]], 0, 1),
    "ammonia": (
        ["N", "H", "H", "H"],
        [[0.0022, 0.0049, 0.2815], [0.9216, -0.1421, -0.0985],
         [-0.5835, -0.7301, -0.0766], [-0.3403, 0.8673, -0.1064]], 0, 1),
    "methanethiol": (
        ["C", "S", "H", "H", "H", "H"],
        [[-0.4963, 0.0000, -0.0287], [1.1665, -0.7205, -0.1591],
         [-1.1948, -0.7838, -0.3155], [-0.6190, 0.8418, -0.7068],
         [-0.7172, 0.3081, 0.9910], [1.8608, 0.3544, 0.2190]], 0, 1),
    "dimethyl_sulfide": (
        ["C", "S", "C", "H", "H", "H", "H", "H", "H"],
        [[-1.3789, -0.0365, -0.1667], [0.0875, -0.9843, -0.6378],
         [1.3816, 0.0057, 0.1467], [-1.4945, 0.0020, 0.9163],
         [-1.3410, 0.9766, -0.5668], [-2.2410, -0.5479, -0.5920],
         [1.4038, 1.0186, -0.2551], [1.2503, 0.0439, 1.2280],
         [2.3322, -0.4780, -0.0727]], 0, 1),
    "methylamine": (
        ["C", "N", "H", "H", "H", "H", "H"],
        [[-0.5647, 0.0334, -0.0230], [0.8544, -0.0628, -0.2849],
         [-1.0770, -0.8312, -0.4481], [-0.9707, 0.9185, -0.5154],
         [-0.8371, 0.0908, 1.0392], [1.3464, 0.7304, 0.0852],
         [1.2487, -0.8790, 0.1470]], 0, 1),

    # Diradicals and a stretched bond, added 2026-09-04. The set had exactly
    # one open-shell molecule, O2, and nothing at a geometry where a single
    # determinant fails outright. This is where an active space matters most
    # and where the previous engine refused to go at all.
    #
    # These geometries are constructed rather than optimised, and deliberately.
    # For each of them the symmetry IS the chemistry, and an optimiser removes
    # it: square cyclobutadiene relaxes to a rectangle to escape its own
    # degeneracy, twisted ethylene relaxes back to planar, and a stretched bond
    # is by definition not a stationary point. So each is written down exactly
    # with its reason.
    #
    # Square cyclobutadiene, D4h: the antiaromatic singlet whose two
    # configurations are exactly degenerate, which is the reason the real
    # molecule distorts.
    # Corners at (+-s/2, +-s/2) for a C-C side of s = 1.45 A, hydrogens 1.09 A
    # further out along each diagonal. Worth stating explicitly because the
    # first attempt put the corners at s/sqrt(2), which makes the side 2.05 A,
    # past the 1.98 A the covalent-radius test allows for C-C. Every carbon was
    # then bonded only to its own hydrogen, each looked like a terminal atom
    # and emitted a degenerate perpendicular PAIR of pi targets, and the engine
    # returned (10e,10o) for what should be a four-orbital pi space. The engine
    # was behaving correctly on a molecule that was not connected.
    "cyclobutadiene_square": (
        ["C", "C", "C", "C", "H", "H", "H", "H"],
        [[0.7250, 0.7250, 0.0000], [-0.7250, 0.7250, 0.0000],
         [-0.7250, -0.7250, 0.0000], [0.7250, -0.7250, 0.0000],
         [1.4957, 1.4957, 0.0000], [-1.4957, 1.4957, 0.0000],
         [-1.4957, -1.4957, 0.0000], [1.4957, -1.4957, 0.0000]], 0, 1),
    # Trimethylenemethane, D3h: four pi electrons in four pi orbitals with two
    # exactly degenerate, so the ground state is a triplet and no closed-shell
    # reference exists at all.
    "trimethylenemethane": (
        ["C", "C", "C", "C", "H", "H", "H", "H", "H", "H"],
        [[0.0000, 0.0000, 0.0000], [1.4000, 0.0000, 0.0000],
         [-0.7000, 1.2124, 0.0000], [-0.7000, -1.2124, 0.0000],
         [2.2790, 0.6275, 0.0000], [2.2790, -0.6275, 0.0000],
         [-1.6829, 1.6599, 0.0000], [-0.5960, 2.2874, 0.0000],
         [-0.5960, -2.2874, 0.0000], [-1.6829, -1.6599, 0.0000]], 0, 3),
    # Ethylene twisted 90 degrees about the C=C axis: the pi bond is broken and
    # the two electrons are degenerate. Planar ethylene is already in the set,
    # so this is the same molecule at the geometry where one determinant fails.
    "ethylene_twisted": (
        ["C", "C", "H", "H", "H", "H"],
        [[0.0000, 0.0000, 0.6695], [0.0000, 0.0000, -0.6695],
         [0.0000, 0.9289, 1.2321], [0.0000, -0.9289, 1.2321],
         [0.9289, 0.0000, -1.2321], [-0.9289, 0.0000, -1.2321]], 0, 1),
    # N2 stretched to 1.60 A, about 1.46 times equilibrium, where all three
    # bonding and antibonding pairs are strongly correlated and a space that
    # drops the sigma framework is visibly wrong.
    #
    # 1.60 rather than something longer for a measured reason. The engine
    # returns a correct (10e,8o) out to 1.80 A and then fails outright at
    # 1.85 A, because `geometry.perceive_bonds` calls a pair bonded within
    # BOND_TOLERANCE = 1.30 times the sum of covalent radii, and for N-N that
    # product is 1.85 A. Past it the atoms are not bonded, no sigma axis is
    # emitted, a two-atom molecule has no atom with two neighbours so no pi
    # normal is emitted either, and the target list is empty. A dissociation
    # curve therefore hits a cliff before it finishes dissociating. That is a
    # real limitation and it is recorded in the tracker; this entry stays on
    # the near side of it so that what it measures is the space rather than the
    # cliff.
    "N2_stretched": (["N", "N"], [[0.0, 0.0, 0.0], [0.0, 0.0, 1.60]], 0, 1),
    # Ozone, C2v: a closed-shell singlet with substantial diradical character in
    # its own ground state, and the standard hard case for any single-reference
    # method. No reference space is recorded, because the published choices
    # range from the (12e,9o) valence 2p space to (18e,12o) including 2s, and
    # picking one would be scoring the engine against a preference.
    "ozone": (
        ["O", "O", "O"],
        [[0.0000, 0.0000, 0.0000], [1.0885, 0.6697, 0.0000],
         [-1.0885, 0.6697, 0.0000]], 0, 1),
    # Larger conjugated systems and charged species, added 2026-09-04 for P2.3.
    #
    # Two axes the set could not see. Every molecule in it was neutral, so the
    # charge bookkeeping -- ncore, nelecas, and the occupation-derived electron
    # count in _tier_from_pool that P2.2 already had to correct once for open
    # shells -- had never been exercised at all. And the largest pi system was
    # uracil's five, where section 11 records the state audit as unreliable on
    # large planar spaces, so the axis a known weakness lives on was the axis
    # with the least evidence under it.
    #
    # The allyl pair is the load-bearing part of the charged group and is why
    # both signs are carried rather than one. Same geometry, same three pi
    # orbitals, two electrons apart. If the engine returns the same electron
    # count for the cation and the anion then the charge is being dropped
    # somewhere, and no neutral molecule in this file can show that. The two
    # aromatic ions test the other direction, a charge that changes which
    # orbitals are occupied rather than only how many electrons they hold, and
    # pyridinium tests a charge that changes the PERCEPTION: protonating the
    # nitrogen gives it a third neighbour, so no lone-pair target is emitted
    # and the space should drop from pyridine's (8e,7o) to the six ring pi.
    #
    # Geometries optimised at RHF/def2-SVP with geomeTRIC from an RDKit
    # starting structure, the same protocol as the non-planar group above.
    # The ions are optimised rather than constructed: unlike square
    # cyclobutadiene, which distorts to escape its own degeneracy, the
    # aromatic ions are closed shells with fully occupied degenerate HOMOs and
    # RHF holds their symmetry on its own. Allyl comes back delocalised, with
    # both CC bonds at 1.375 A, from a localised C=C-CH2+ SMILES start.
    "naphthalene": (
        ["C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "H", "H", "H",
         "H", "H", "H", "H", "H"],
        [[-2.4916, 0.3638, 0.1529], [-2.2986, -1.0379, 0.0535],
         [-1.0423, -1.5532, -0.0448], [0.0956, -0.6982, -0.0495],
         [1.4216, -1.2053, -0.1509], [2.4916, -0.3634, -0.1529],
         [2.2993, 1.0384, -0.0535], [1.0423, 1.5520, 0.0447],
         [-0.0961, 0.6977, 0.0495], [-1.4218, 1.2057, 0.1509],
         [-3.4956, 0.7601, 0.2305], [-3.1576, -1.6960, 0.0563],
         [-0.8935, -2.6228, -0.1207], [1.5673, -2.2753, -0.2267],
         [3.4956, -0.7598, -0.2305], [3.1580, 1.6969, -0.0562],
         [0.8931, 2.6216, 0.1207], [-1.5673, 2.2758, 0.2267]], 0, 1),
    "hexatriene": (
        ["C", "C", "C", "C", "C", "C", "H", "H", "H", "H", "H", "H", "H",
         "H"],
        [[1.8233, 0.3930, 0.2356], [3.0526, 0.2986, -0.2560],
         [0.6164, -0.0488, -0.4659], [-0.6160, 0.0487, 0.0330],
         [-1.8235, -0.3929, -0.6680], [-3.0528, -0.2986, -0.1766],
         [1.6783, 0.8230, 1.2216], [3.9126, 0.6407, 0.3045],
         [3.2433, -0.1239, -1.2358], [0.7575, -0.4795, -1.4526],
         [-0.7568, 0.4794, 1.0197], [-1.6786, -0.8229, -1.6539],
         [-3.2436, 0.1239, 0.8032], [-3.9127, -0.6408, -0.7373]], 0, 1),
    "octatetraene": (
        ["C", "C", "C", "C", "C", "C", "C", "C", "H", "H", "H", "H", "H",
         "H", "H", "H", "H", "H"],
        [[3.0456, -0.6251, 0.4555], [4.2597, -0.0997, 0.5661],
         [1.8262, 0.1507, 0.2249], [0.6091, -0.3852, 0.1150],
         [-0.6091, 0.3852, -0.1150], [-1.8262, -0.1507, -0.2249],
         [-3.0456, 0.6251, -0.4555], [-4.2597, 0.0997, -0.5661],
         [2.9246, -1.7005, 0.5383], [4.4273, 0.9685, 0.4900],
         [5.1297, -0.7201, 0.7367], [1.9423, 1.2269, 0.1414],
         [0.4956, -1.4616, 0.1988], [-0.4956, 1.4616, -0.1988],
         [-1.9423, -1.2269, -0.1414], [-2.9246, 1.7005, -0.5383],
         [-4.4273, -0.9685, -0.4900], [-5.1297, 0.7201, -0.7367]], 0, 1),
    "anthracene": (
        ["C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C", "C",
         "C", "H", "H", "H", "H", "H", "H", "H", "H", "H", "H"],
        [[3.7038, -0.2175, 0.1120], [3.5163, 1.1780, -0.1593],
         [2.2729, 1.6921, -0.2815], [1.1115, 0.8550, -0.1430],
         [-0.1821, 1.3565, -0.2637], [-1.2978, 0.5344, -0.1272],
         [-2.6396, 1.0380, -0.2492], [-3.7042, 0.2175, -0.1120],
         [-3.5167, -1.1779, 0.1593], [-2.2729, -1.6913, 0.2814],
         [-1.1110, -0.8550, 0.1430], [0.1824, -1.3569, 0.2638],
         [1.2979, -0.5345, 0.1272], [2.6395, -1.0384, 0.2493],
         [4.7088, -0.6076, 0.2059], [4.3831, 1.8170, -0.2655],
         [2.1309, 2.7454, -0.4863], [-0.3236, 2.4102, -0.4686],
         [-2.7804, 2.0914, -0.4540], [-4.7091, 0.6078, -0.2059],
         [-4.3833, -1.8172, 0.2655], [-2.1309, -2.7446, 0.4862],
         [0.3239, -2.4106, 0.4687], [2.7804, -2.0918, 0.4541]], 0, 1),
    "allyl_cation": (
        ["C", "C", "C", "H", "H", "H", "H", "H"],
        [[-1.0849, 0.4758, -0.1515], [-0.0484, -0.4077, -0.3445],
         [1.1151, -0.2226, 0.3654], [-1.0036, 1.3062, 0.5418],
         [-2.0228, 0.3733, -0.6869], [-0.1463, -1.2307, -1.0399],
         [1.2297, 0.5972, 1.0665], [1.9613, -0.8914, 0.2492]], 1, 1),
    "allyl_anion": (
        ["C", "C", "C", "H", "H", "H", "H", "H"],
        [[-1.1693, 0.5001, -0.1733], [-0.0343, -0.2908, -0.2456],
         [1.1986, -0.2496, 0.3847], [-1.2271, 1.3677, 0.4819],
         [-2.0445, 0.2732, -0.7762], [-0.1326, -1.1258, -0.9507],
         [1.4503, 0.5199, 1.1126], [1.9588, -0.9948, 0.1666]], -1, 1),
    "cyclopentadienyl_anion": (
        ["C", "C", "C", "C", "C", "H", "H", "H", "H", "H"],
        [[1.1399, 0.3073, -0.1883], [0.0248, 1.1537, -0.3124],
         [-1.1246, 0.4057, -0.0048], [-0.7198, -0.9030, 0.3095],
         [0.6797, -0.9638, 0.1961], [2.1758, 0.5866, -0.3594],
         [0.0473, 2.2021, -0.5963], [-2.1465, 0.7743, -0.0092],
         [-1.3740, -1.7235, 0.5907], [1.2973, -1.8396, 0.3742]], -1, 1),
    "tropylium": (
        ["C", "C", "C", "C", "C", "C", "C", "H", "H", "H", "H", "H", "H",
         "H"],
        [[-0.0377, 1.6004, 0.0872], [1.2294, 1.0260, 0.0811],
         [1.5707, -0.3211, 0.0139], [0.7293, -1.4264, -0.0638],
         [-0.6613, -1.4575, -0.0934], [-1.5539, -0.3912, -0.0527],
         [-1.2764, 0.9698, 0.0277], [-0.0632, 2.6811, 0.1462],
         [2.0595, 1.7187, 0.1358], [2.6313, -0.5379, 0.0232],
         [1.2218, -2.3895, -0.1069], [-1.1078, -2.4417, -0.1565],
         [-2.6032, -0.6553, -0.0883], [-2.1383, 1.6246, 0.0464]], 1, 1),
    "pyridinium": (
        ["C", "C", "C", "N", "C", "C", "H", "H", "H", "H", "H", "H"],
        [[0.5098, 1.2831, -0.0207], [1.3720, 0.1962, 0.1021],
         [0.8359, -1.0685, 0.1198], [-0.4881, -1.2286, 0.0199],
         [-1.3425, -0.2066, -0.0992], [-0.8645, 1.0811, -0.1228],
         [0.9092, 2.2885, -0.0370], [2.4407, 0.3284, 0.1827],
         [1.4313, -1.9653, 0.2118], [-0.8596, -2.1637, 0.0350],
         [-2.3919, -0.4526, -0.1727], [-1.5521, 1.9082, -0.2188]], 1, 1),
}

# name -> list of (label, character, TBE in eV, source tag)
EXCITATIONS = {
    "formaldehyde": [
        ("1 1A2", "n->pi*", 3.98, "QUEST"),
        ("2 1A1", "n->Rydberg 3s", 7.30, "QUEST"),
        ("1 1B2", "pi->pi*", 9.22, "QUEST"),
    ],
    "acetone": [
        ("1 1A2", "n->pi*", 4.48, "QUEST"),
        ("1 1B2", "n->Rydberg 3s", 6.69, "QUEST"),
    ],
    "acrolein": [
        ("1 1A''", "n->pi*", 3.74, "QUEST"),
        ("2 1A'", "pi->pi*", 6.68, "QUEST"),
    ],
    "formamide": [
        ("1 1A''", "n->pi*", 5.66, "QUEST"),
        ("2 1A'", "pi->pi*", 7.66, "QUEST"),
    ],
    "pyrrole": [
        ("1 1A2", "pi->Rydberg 3s", 5.24, "QUEST"),
        ("1 1B2", "pi->pi*", 6.33, "QUEST"),
    ],
    "furan": [
        ("1 1A2", "pi->Rydberg 3s", 6.00, "QUEST"),
        ("1 1B2", "pi->pi*", 6.37, "QUEST"),
    ],
    "pyridine": [
        ("1 1B1", "n->pi*", 4.96, "QUEST"),
        ("1 1B2", "pi->pi*", 5.10, "QUEST"),
    ],
    "ethylene": [
        ("1 1B1u", "pi->pi*", 7.93, "QUEST"),
    ],
    "butadiene": [
        ("1 1Bu", "pi->pi*", 6.22, "QUEST"),
        ("2 1Ag", "pi->pi* (doubly excited)", 6.50, "Ang"),
    ],
    "benzene": [
        ("1 1B2u", "pi->pi*", 5.06, "QUEST"),
        ("1 1B1u", "pi->pi*", 6.680, "QUEST"),
    ],
    "uracil": [
        ("1 1A''", "n->pi*", 4.80, "QUEST"),
        ("1 1A'", "pi->pi*", 5.25, "QUEST"),
    ],
    # o-Nitrophenol has NO QUEST entry and no settled literature active space,
    # which is exactly why it was an open question when it was raised. It is
    # deliberately given no reference energies rather than being scored against
    # a number that does not exist: it contributes space stability, CASSCF
    # convergence, timing and state-character results, and is excluded from
    # every energy statistic. See `MOLECULES_WITHOUT_REFERENCE_ENERGIES`.
    "p-benzoquinone": [
        # The known-hard case in the automatic-selection literature: the two
        # lowest singlets are within ~0.2 eV and swap under state averaging.
        ("1 1B1g", "n->pi*", 2.79, "QUEST"),
        ("1 1Au", "n->pi*", 2.85, "QUEST"),
    ],
}

# name -> ((n_electrons, n_orbitals), description, source tag)
# The active space most commonly used in the multireference literature.
REFERENCE_SPACES = {
    "ethylene": ((2, 2), "the pi/pi* pair", "Roos"),
    "butadiene": ((4, 4), "the four pi orbitals", "Roos"),
    "benzene": ((6, 6), "the six pi orbitals", "Roos"),
    "formaldehyde": ((6, 4), "pi, pi* and the two oxygen lone pairs; the "
                             "smaller (4,3) n/pi/pi* space is also standard",
                     "Roos"),
    "pyrrole": ((6, 5), "the five pi orbitals of the ring", "Thiel"),
    "furan": ((6, 5), "the five pi orbitals of the ring", "Thiel"),
    "pyridine": ((8, 7), "the six ring pi orbitals plus the nitrogen lone pair",
                 "Thiel"),
    "N2": ((10, 8), "the full valence space", "Roos"),
    "O2": ((12, 8), "the full valence space", "Roos"),
    "water": ((8, 6), "the valence space; there is no pi system", "Roos"),
    "acrolein": ((8, 7), "the four pi orbitals plus the oxygen lone pair and "
                         "the carbonyl pi system", "Thiel"),
    # The description and the count disagree, and the disagreement is worth
    # recording rather than chasing. "The amide pi system plus the oxygen lone
    # pairs" names FIVE orbitals: N-C=O gives three pi MOs of which only one is
    # virtual, plus two oxygen lone pairs, holding eight electrons. That is
    # CAS(8e,5o), and it is what this engine produces -- verified orbital by
    # orbital: both kept lone pairs sit on the oxygen (0.69 and 0.96 of their
    # population) and the nitrogen lone pair is dropped.
    #
    # As of 2026-09-04 the QUICK tier returns (8e,5o) too, where it used to
    # return (8e,7o) with two electrons too many and the wrong orbital count.
    # The amide nitrogen is planar and three-coordinate, so it was being handed
    # an in-plane lone-pair target it has no lone pair to fill; withdrawing
    # that target is what brought the quick answer onto the description. So the
    # sentence above is now true of both tiers rather than of the refinement
    # alone, and the two-orbital gap against the RECORDED count is unchanged.
    #
    # The recorded space is CAS(8e,7o): the same eight electrons in two more
    # orbitals, which must therefore be virtuals the description does not name.
    # An amide pi system has no second pi* to offer, so those two are sigma* or
    # diffuse. A refinement that returns (8e,5o) here is reproducing the
    # chemistry as stated; treat the two-orbital gap as unexplained reference
    # detail rather than as the engine under-selecting.
    "formamide": ((8, 7), "the amide pi system plus the oxygen lone pairs; the "
                          "description names five orbitals and the count is "
                          "seven -- see the note above",
                  "Thiel"),
    "acetone": ((6, 4), "the carbonyl pi system and the oxygen lone pairs",
                "Thiel"),
    "uracil": ((14, 10), "five pi, both carbonyl lone pairs and three pi*. "
                        "One lone pair is not enough: with 5pi+1n+3pi* an "
                        "SA-CASSCF over six roots produces no n->pi* state at "
                        "all, because the n->pi* hole is a combination of both "
                        "oxygens' lone pairs", "Thiel"),
    "p-benzoquinone": ((12, 10), "the ring and carbonyl pi systems plus the "
                                 "oxygen lone pairs", "Thiel"),

    # The full valence space by convention, built exactly as water's (8e,6o)
    # above is: every bond's sigma and sigma*, plus the lone pairs. Tagged
    # `convention` rather than borrowing a neighbouring citation, because no
    # particular paper is being pointed at and pretending otherwise would make
    # the source column worth less everywhere else in this table.
    #
    # The other three molecules in the non-planar group get no reference space
    # at all, the same treatment methane and o-nitrophenol have. They are here
    # to exercise the lone-pair versus sigma labelling on a second-row
    # heteroatom and a pyramidal nitrogen, and inventing a "correct" size for
    # them would test the invention rather than the classifier.
    "hydrogen_sulfide": ((8, 6), "the full valence space: two S-H sigma, two "
                                 "sulfur lone pairs and two sigma*, the same "
                                 "shape as water's", "convention"),
    "ammonia": ((8, 7), "the full valence space: three N-H sigma, the nitrogen "
                        "lone pair and three sigma*", "convention"),

    # The diradicals. Each of these is a pi space nobody disagrees about, which
    # is why they are scored at all where ozone is not: the whole point of the
    # molecule is that its pi system is degenerate, so the pi system is the
    # space and there is no judgement left to make about its size.
    "cyclobutadiene_square": ((4, 4), "the four pi orbitals; the square "
                                      "geometry's degeneracy is the reason "
                                      "the molecule distorts", "convention"),
    "trimethylenemethane": ((4, 4), "the four pi orbitals, two of them exactly "
                                    "degenerate, which is why the ground "
                                    "state is a triplet", "convention"),
    "ethylene_twisted": ((2, 2), "the broken pi bond, the textbook two-electron "
                                 "two-orbital biradicaloid", "convention"),
    "N2_stretched": ((10, 8), "the full valence space, which at a stretched "
                              "geometry is the only defensible answer: every "
                              "bonding and antibonding pair of a breaking "
                              "triple bond is strongly correlated",
                     "convention"),

    # Larger conjugated systems. The full pi space is the standard choice for
    # all four and the first three are in the Thiel benchmark set; anthracene
    # is not, so it is tagged by convention rather than borrowing that
    # citation. These are where the count metric is most likely to degrade,
    # because a fourteen-orbital pi system is where selecting by projection
    # has the most room to pick a defensible space that is not the usual one.
    "naphthalene": ((10, 10), "the ten pi orbitals", "Thiel"),
    "hexatriene": ((6, 6), "the six pi orbitals of the all-trans chain",
                   "Thiel"),
    "octatetraene": ((8, 8), "the eight pi orbitals of the all-trans chain",
                     "Thiel"),
    "anthracene": ((14, 14), "the fourteen pi orbitals", "convention"),

    # Charged species. Every one of these is a Huckel pi count with no other
    # defensible reading, which is the same standard water's (8e,6o) and
    # ammonia's (8e,7o) are tagged under.
    #
    # The allyl pair is the point: identical geometry, identical three-orbital
    # pi system, two electrons apart. An engine that drops the charge returns
    # the same electron count for both.
    "allyl_cation": ((2, 3), "the three-centre pi system, two electrons in "
                             "three orbitals", "convention"),
    "allyl_anion": ((4, 3), "the same three pi orbitals as the cation, with "
                            "two more electrons", "convention"),
    "cyclopentadienyl_anion": ((6, 5), "the five ring pi orbitals of the "
                                       "aromatic six-pi anion", "convention"),
    "tropylium": ((6, 7), "the seven ring pi orbitals of the aromatic six-pi "
                          "cation", "convention"),
    # Not (8e,7o). Protonating the nitrogen gives it a third neighbour, so
    # geometry.perceive emits no lone-pair target for it and the space is the
    # six ring pi orbitals alone. That is the whole reason this molecule is
    # here: it is a charge that changes the PERCEPTION rather than only the
    # electron count, and pyridine sits beside it as the unprotonated control.
    "pyridinium": ((6, 6), "the six ring pi orbitals; unlike pyridine there is "
                           "no nitrogen lone pair to add, because the "
                           "protonated nitrogen has no lone pair left",
                   "convention"),
}

# The published bar for a fully automatic scheme. Not like-for-like with this
# work -- a different molecule set, def2-TZVPD, and a different downstream --
# so it is a soft reference, not a target.
# Molecules carried for everything except energy accuracy. Reporting a mean
# error over a molecule with no reference is worse than reporting nothing, so
# these are excluded from every energy statistic and included in all the rest.
# Which class of test each molecule belongs to, for P2.4's scoring.
#
# One table with a class column and per-class subtotals, rather than separate
# ledgers per phase. The set has grown twice mid-plan -- P2.1 added the
# non-planar heteroatoms, P2.2 the diradicals, P2.3 the large conjugated
# systems and the ions -- so an overall fraction alone is not comparable
# across runs and a reader cannot tell whether a change came from the engine
# or from the denominator. Subtotals make both visible at once, and every
# quoted fraction still names what it is over.
#
# Anything absent from this map is `core`: the original planar closed-shell
# organics the engine was built and published against.
MOLECULE_CLASSES = {
    "hydrogen_sulfide": "non-planar", "ammonia": "non-planar",
    "methanethiol": "non-planar", "dimethyl_sulfide": "non-planar",
    "methylamine": "non-planar", "methane": "non-planar",
    "water": "non-planar",

    "cyclobutadiene_square": "diradical", "trimethylenemethane": "diradical",
    "ethylene_twisted": "diradical", "N2_stretched": "diradical",
    "ozone": "diradical", "O2": "diradical",

    "naphthalene": "conjugated", "anthracene": "conjugated",
    "hexatriene": "conjugated", "octatetraene": "conjugated",

    "allyl_cation": "charged", "allyl_anion": "charged",
    "cyclopentadienyl_anion": "charged", "tropylium": "charged",
    "pyridinium": "charged",
}

CLASS_ORDER = ("core", "non-planar", "diradical", "conjugated", "charged")


def molecule_class(name: str) -> str:
    return MOLECULE_CLASSES.get(name, "core")


MOLECULES_WITHOUT_REFERENCE_ENERGIES = frozenset({
    "o-nitrophenol",
    # P2.3's nine. They carry reference SPACES and no excitation energies,
    # which is exactly what this set is for. No TBE is invented for them: the
    # phase asks whether the space is right, and section 10.4's downstream
    # numbers must not move because the molecule set grew underneath them.
    "naphthalene", "hexatriene", "octatetraene", "anthracene",
    "allyl_cation", "allyl_anion", "cyclopentadienyl_anion", "tropylium",
    "pyridinium",
})

# Reference state CHARACTERS, in order, for molecules that have no reference
# energies. A space can be scored on whether it produces the right states in
# the right order even when no one has published a number for them, and for
# o-nitrophenol that is the only check available.
#
# Source: the user's own SA-CASSCF calculations, reported 2026-09-02. Both
# CAS(12,9) and CAS(14,10) at five equally weighted states give S1 and S2 as
# n->pi* and S3 and S4 as pi->pi*. Two different spaces agreeing is worth more
# than either alone. There is no QUEST entry for this molecule.
REFERENCE_STATE_CHARACTERS = {
    "o-nitrophenol": ["n->pi*", "n->pi*", "pi->pi*", "pi->pi*"],
}

# How many states each reference was determined under, where it matters.
#
# An active space is only valid for the state-averaging protocol it was chosen
# for, so scoring a recommendation against a reference means matching that
# protocol first. o-Nitrophenol's spaces come from a five-state equally
# weighted average and uracil's from three; running either at a different root
# count produces a different answer that is not evidence about the reference.
# Absent here means the benchmark's own default applies.
PROTOCOL_STATES = {
    "o-nitrophenol": 5,
    "uracil": 3,
}

LITERATURE_BAR = {
    "scheme": "l-ASF(QRO)",
    "mae_ev": 0.49,
    "n_molecules": 32,
    "basis": "def2-TZVPD",
    "source": (
        "Kollmar, Sivalingam and Neese, as assessed in "
        "'Performance of Automatic Active Space Selection for Electronic "
        "Excitation Energies', arXiv:2511.05732 (2025). The same study reports "
        "25-30% unsatisfactory results for every scheme it tested in fully "
        "automatic mode."
    ),
}

SOURCES = {
    "QUEST": "Loos et al., J. Chem. Theory Comput. 2018, 14, 4360.",
    "QUESTDB": "Veril et al., WIREs Comput. Mol. Sci. 2021, 11, e1517.",
    "Thiel": "Schreiber et al., J. Chem. Phys. 2008, 128, 134110.",
    "Roos": "Roos et al., Adv. Chem. Phys. 1996, 93, 219.",
    "Ang": "Angeli, J. Comput. Chem. 2009, 30, 1319.",
    "convention": ("Not a publication. The full valence space as conventionally "
                   "constructed for a small hydride: every bond's sigma and "
                   "sigma*, plus the lone pairs. Recorded as a convention so "
                   "the source column keeps meaning what it says elsewhere."),
}


def molecule(name):
    return GEOMETRIES[name]


def all_names():
    return sorted(GEOMETRIES)
