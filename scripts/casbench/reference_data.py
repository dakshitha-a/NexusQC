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
    # CAS(8e,5o), and it is what this engine's narrowing produces -- verified
    # orbital by orbital: both kept lone pairs sit on the oxygen (0.69 and 0.96
    # of their population) and the nitrogen lone pair is dropped.
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
}

# The published bar for a fully automatic scheme. Not like-for-like with this
# work -- a different molecule set, def2-TZVPD, and a different downstream --
# so it is a soft reference, not a target.
# Molecules carried for everything except energy accuracy. Reporting a mean
# error over a molecule with no reference is worse than reporting nothing, so
# these are excluded from every energy statistic and included in all the rest.
MOLECULES_WITHOUT_REFERENCE_ENERGIES = frozenset({"o-nitrophenol"})

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
