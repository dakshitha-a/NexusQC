# A geometry-oriented projection method for automatic active-space selection

**Status:** implemented 2026-09-02, `app/chemistry/cas/`. This document is the
method of record. It supersedes [`CAS_RECO_REDESIGN.md`](CAS_RECO_REDESIGN.md),
which describes the previous entropy-pilot design.

---

## 1. The problem

A CASSCF, CASPT2 or NEVPT2 calculation requires a choice of active space: a set
of $n$ orbitals holding $N$ electrons, within which the wavefunction is
expanded to full CI. The choice is not a convenience. Too small and the
qualitative physics is missing; too large and the calculation is intractable,
since the determinant count grows as $\binom{n}{N_\alpha}\binom{n}{N_\beta}$.
Choosing it well has traditionally required an expert, and automating that
choice is an active research problem with no settled solution — a recent
assessment of the leading fully automatic schemes reports 25–30% unsatisfactory
results across every variant tested [11].

This document describes the method implemented in NexusQC. The design target
was a selector that

1. is **cheap** enough to run interactively, so a user can ask for a
   recommendation and get one in seconds;
2. imposes **no ceiling** on the number of active orbitals;
3. gives the **same answer regardless of the basis set** and regardless of how
   the input geometry happens to be oriented;
4. is **robust to the character of the requested states** — π→π\*, n→π\* or
   Rydberg, bright or dark.

Points 3 and 4 are where the previous implementation failed, and they turn out
to be related: both are consequences of asking the wavefunction the wrong
question.

---

## 2. Relation to existing methods

It is worth stating plainly which parts of this method are new and which are
not.

**The projection step is AVAS's mathematics.** Sayfutyarova, Sun, Chan and
Knizia's atomic valence active space method [1] projects the molecular orbitals
onto a set of reference atomic orbitals drawn from a minimal basis, and
diagonalises the projector separately in the occupied and virtual blocks. That
eigenvalue problem is used here unchanged. What differs is the construction of
the reference set — see §4.

**The ranking is King and Gagliardi's APC.** The approximate pair coefficient
[2,3] estimates an orbital's correlation importance in closed form from the
Fock and exchange matrices. It is used here as published, via its PySCF
implementation, with one restriction on where it is applied (§5).

**The overall shape — atomic-orbital projection to pick candidates, an entropy
to order them — is AEGISS's idea** [4]. AEGISS obtains its entropies from a
partially converged DMRG calculation over a large frontier-orbital window,
which is where essentially all of its cost lies. Substituting a closed-form
entropy changes the cost by orders of magnitude and, as §7.3 shows, changes
what the entropy is *for*.

**What is new here** is threefold:

- **Geometric orientation of the reference orbitals** (§4). The reference set
  is built from directions derived from the molecular structure rather than
  named in the laboratory frame. This is what makes the result invariant to
  rotation and, in combination with the fixed minimal reference basis, to the
  choice of calculation basis. AVAS as published and as implemented in PySCF
  does not have this property; §7.2 measures the failure.
- **σ-completion as a correctness requirement** (§4.3), which removes the need
  for the hydride special-casing that a π/lone-pair-only target set forces.
- **State-driven augmentation with orbital-character classification** (§6),
  which selects on what the requested states are made of rather than on how
  many configurations a space can hold.

Methods this is *not*: it is not AutoCAS [5,6], which selects from DMRG orbital
entropies over a large preliminary space; it is not the Active Space Finder
family [11], which uses MP2 natural orbitals and a DMRG-CASCI cumulant
analysis; it is not a natural-orbital-occupation method [7]; and it does not
use machine learning.

---

## 3. Overview

Given a molecule and, optionally, a number of electronic states:

```
geometry ──▶ perception ──▶ oriented targets
                                  │
      converged SCF ──────────────┼──▶ projection ──▶ candidate pool
                                  │                        │
                                  │                   APC ranking
                                  │                        │
   (if states > 1) TDA ──▶ NTOs ──┴──▶ character ──▶ augmentation
                                                           │
                                                    tiers + cost
```

Everything except the optional TDA pass costs a fraction of a second on top of
one SCF. The engine never builds a `Mole` and never imports the application's
job registry, so the same code runs inside the job worker, inside the
benchmark harness, and in a bare script.

---

## 4. The oriented projector

### 4.1 Construction of the reference set

AVAS asks: *how much of this molecular orbital is oxygen 2p?* The reference
orbitals are named by their laboratory-frame components — `O 2px`, `C 2pz` —
and this is the origin of the problem. A chemist targeting the π system of a
planar molecule writes `C 2pz` because the molecule happens to lie in the *xy*
plane. Rotate the molecule and the same label names a different physical
orbital.

Instead, let $\hat{\mathbf{a}}_A$ be a unit vector at atom $A$ derived from the
geometry. The reference orbital is the corresponding combination of that atom's
minimal-basis $p$ functions,

$$
|t_A\rangle \;=\; a_x\,|p_x^A\rangle + a_y\,|p_y^A\rangle + a_z\,|p_z^A\rangle .
$$

Under a rotation $\mathbf{R}$ of the molecule, $\hat{\mathbf{a}}_A \to
\mathbf{R}\hat{\mathbf{a}}_A$ and the $p$ functions transform the same way, so
$|t_A\rangle$ is carried into itself. The selected space is invariant.

### 4.2 Where the directions come from

Three kinds of direction are derived, all from the geometry alone (bonds from
covalent radii [8]):

**π normals.** At an atom with exactly two neighbours, the normal to the plane
they define, $\hat{\mathbf{n}} \propto \mathbf{v}_1 \times \mathbf{v}_2$. At an
atom with three or more, the best-fit plane normal, obtained as the
right-singular vector of least variance of the centred neighbour
displacements. A fitted normal is accepted only if the centre is genuinely
planar,

$$
\max_i \left| \hat{\mathbf{v}}_i \cdot \hat{\mathbf{n}} \right| < 0.25 ,
$$

which is 0 for a planar centre, $\approx 0.37$ for pyramidal ammonia and
$\approx 0.577$ for a tetrahedral one. Without this test an SVD returns a
confident direction of least variance for an sp³ carbon, and every saturated
carbon in the molecule acquires a spurious π orbital.

**Lone pairs.** From the coordination geometry: for two neighbours, the
direction opposing their bisector and the normal to their plane; for three, the
direction opposing their sum. For a *terminal* heteroatom all three
non-bonding directions are emitted, because which of them is the true lone pair
depends on the bond order — a carbonyl oxygen's lone pairs are perpendicular to
C=O, a nitrile or dinitrogen nitrogen's lies along the axis — and bond orders
are not available from geometry alone. The projection discards whichever holds
no density, which is cheaper and more robust than perceiving bond orders.

**σ axes.** For every bond, the bond direction, emitted **on both atoms**. Both
ends are required: the bonding and antibonding combinations are what the
occupied/virtual split separates, and a target on one end only gives a pool
with no virtual partner.

A terminal atom inherits its π axis from the atom it is bonded to when that
atom has one. This is not cosmetic: without it a carbonyl oxygen's π direction
comes from an arbitrary perpendicular pair which, together with the axial lone
pair, spans the atom's *entire* p shell. The π and lone-pair target sets then
cover the same space and cannot be told apart — measured on formaldehyde, the
n→π\* hole projected 0.67 onto **both**. With inheritance it projects 0.67 onto
the lone pairs and 0.00 onto π.

### 4.3 Why σ targets are mandatory

A π/lone-pair-only target set is sufficient for conjugated and carbonyl
systems, and fails completely for anything else. Water has no π system. Its
pool consists of the two oxygen lone pairs: every orbital doubly occupied, one
configuration, no correlation described at all — measured as a full
$(4e, 2o)$. This is the same degenerate-pool failure the previous
implementation met from the other direction, and which it worked around with a
hydrogen-reseeding rule followed by a terminal error guard. Emitting σ targets
removes the failure at its source: water becomes $(8e, 6o)$, ammonia
$(8e, 7o)$ and methane $(8e, 7o)$, all with virtual orbitals, in every basis.

### 4.4 The projection

With $\mathbf{T}$ ($n_{\text{minao}} \times n_{\text{target}}$) holding the
oriented targets, $\mathbf{S}^{pp}$ the minimal-basis overlap,
$\mathbf{S}^{pc}$ the cross overlap with the calculation basis and
$\mathbf{C}$ the MO coefficients:

$$
\mathbf{S}^{2} = \mathbf{T}^{\dagger}\mathbf{S}^{pp}\mathbf{T},
\qquad
\mathbf{S}^{21} = \mathbf{T}^{\dagger}\mathbf{S}^{pc}\mathbf{C},
\qquad
\mathbf{A} = \left(\mathbf{S}^{21}\right)^{\dagger}
             \left(\mathbf{S}^{2}\right)^{+}\mathbf{S}^{21}
$$

$\mathbf{A}$ is the projector onto the target space in the MO basis. Its
occupied and virtual blocks are diagonalised separately — which is what keeps
the electron count well defined — and eigenvalues above $\tau = 0.2$ (AVAS's
own default, retained so the two remain comparable) define the active space.

The Moore–Penrose pseudo-inverse in $\left(\mathbf{S}^{2}\right)^{+}$ is
essential rather than defensive. The target set is deliberately over-complete:
σ targets on bonded neighbours overlap heavily, a lone-pair direction can be
near-parallel to a σ one, and a linear centre emits a degenerate pair. $
\mathbf{S}^{2}$ is therefore singular in general. The pseudo-inverse makes
$\mathbf{A}$ the projector onto the *span* of the targets, so the result
depends only on that span and never on the particular redundant, non-orthogonal
vectors chosen to describe it. This is also what makes the non-covariance of
the degenerate perpendicular pair harmless: an axially symmetric centre such as
N₂ admits no covariant choice of two perpendicular directions, but both members
are always emitted together and a projection onto a subspace does not care
which basis of it was supplied.

Open-shell references follow AVAS's `openshell_option=2` convention, with
singly occupied orbitals counted on the α side. ROHF is used rather than UHF,
by measurement rather than by argument: over four radicals and three basis sets
ROHF gives an identical space every time while UHF moves for the methyl
radical, its α and β sets relaxing differently.

---

## 5. Ranking

The projector answers *which orbitals are chemically relevant*. It does not
order them, and for a molecule of any size the σ-inclusive pool is larger than
anyone wants to correlate — benzene's is 25 orbitals.

The ordering uses the approximate pair coefficient [2]. For occupied $i$ and
virtual $a$, the coefficient of the doubly excited configuration
$|\Phi_{i\bar{i}}^{a\bar{a}}\rangle$ is estimated by the closed-form two-level
CI solution,

$$
c_{ia} = \frac{-K_{aa}/2}
              {\Delta_{ia} + \sqrt{\left(K_{aa}/2\right)^2 + \Delta_{ia}^2}},
\qquad
\Delta_{ia} = F_{aa} - F_{ii},
$$

and each orbital is assigned the von Neumann entropy of the resulting
normalised two-state population,

$$
\sigma_p = \frac{\sum_q c_{pq}^2}{1 + \sum_q c_{pq}^2},
\qquad
s_p = -\sigma_p \ln \sigma_p - (1-\sigma_p)\ln(1-\sigma_p).
$$

The APC-*N* variant [3] repeats the estimate, promoting the highest-entropy
virtual to singly occupied each round, so that one low-lying virtual cannot
dominate. $N = 2$ is used.

This requires only $\mathbf{F}$ and $\mathbf{K}$, both of which a converged SCF
has already built. No CASCI, no MP2, no DMRG, no iteration: measured at
$\approx 0.1$ s.

**The ranking is applied strictly within the projector's pool.** Raw APC over
all molecular orbitals is not basis independent — on pyrrole it returns
$(18e, 12o)$ in def2-SVP and $(22e, 13o)$ in def2-TZVP, because the virtual
manifold it ranks over grows with the basis and some of the orbitals it
promotes are artefacts of that manifold. Restricted to a pool fixed by the
geometry before the ranking sees it, the ordering inherits the pool's basis
independence.

---

## 6. The excited-state branch

### 6.1 What the previous approach could not do

When more states were requested than its space could hold, the previous
implementation widened by adding whichever remaining orbital maximised the
*configuration count*, with entropy as a tiebreak. No part of that rule can
know that a dark n→π\* state needs the heteroatom lone pair. If the lone pair
is absent the state is not merely inaccurate, it is missing, and nothing
reports it.

### 6.2 Asking the states

A TDA pass on a range-separated hybrid (CAM-B3LYP [9]) is run for at least
twice the requested number of roots. A range-separated functional is required:
TDA on a Hartree–Fock reference is CIS, which overestimates valence excitations
by of order an electron-volt and misorders them, and ordering is what this
branch depends on.

Each root's one-particle transition density matrix is decomposed into natural
transition orbitals [10],

$$
\mathbf{T} = \mathbf{U}\,\boldsymbol{\lambda}\,\mathbf{V}^{\dagger},
$$

collapsing a transition spread over many canonical pairs into one dominant
hole/particle pair $(u_1, v_1)$ of weight $\lambda_1^2$. NTOs rather than the
largest canonical amplitude are used because canonical orbitals mix arbitrarily
within degenerate sets and NTOs do not.

### 6.3 Character assignment

**Rydberg versus valence, by spatial extent.** The second moment of the
particle NTO is compared with the largest among the occupied orbitals, which
measures the molecule's own size:

$$
\rho = \frac{\langle v_1 | r^2 | v_1\rangle}
            {\max_i \langle \phi_i | r^2 | \phi_i \rangle}.
$$

Measured on formaldehyde in aug-cc-pVDZ, valence states give $\rho \approx
0.86$ and Rydberg states $\rho = 4.6$–$8.7$. The threshold is set at $\rho = 3$
with a factor-of-five margin on either side.

**n versus π versus σ, by projection onto the same oriented targets** used by
the ground-state projector — one definition of "lone pair" in the code, not
two.

**Bright versus dark, by oscillator strength.** This is reported and never used
to select. The dark states are precisely the ones a ground-state criterion
loses, so selecting on brightness would reintroduce the failure this branch
exists to remove.

### 6.4 Augmentation

For each requested state, the dominant hole and particle NTOs are projected
against the space already chosen; the residual is what the space cannot
describe. Where its norm exceeds 0.3, the residual is orthonormalised and
appended.

Rydberg particle orbitals are deliberately **not** added. They are diffuse,
they do not mix appreciably with the valence orbitals, and including them in a
CASSCF active space is a well-known route to convergence trouble without
improving the valence states. They are reported instead.

### 6.5 The one real basis dependence

Rydberg states cannot be represented at all without diffuse basis functions.
In cc-pVDZ no state is flagged Rydberg — which is correct — and the engine
says the basis could not look for them rather than returning a valence answer
that appears complete. Diffuse character is detected numerically, by smallest
basis exponent, rather than by basis-set name, since a basis may arrive as a
Basis Set Exchange payload with no recognisable label.

This is the single place where the method's basis independence genuinely ends,
and it is a property of the physics rather than of the selection.

---

## 7. Sizing, and the absence of a cap

The previous implementation refused any request above twelve active orbitals.
That ceiling was never a statement about chemistry: it existed because every
recommendation ended in a full state-averaged CASSCF, so the recommendation had
to fit inside what CASSCF could afford. This engine does not run that CASSCF,
and the ceiling goes with it.

What replaces it is a cost report. The determinant count is
$\binom{n}{N_\alpha}\binom{n}{N_\beta}$, but the quantity that sets the cost of
the spin-adapted CI actually used is the Weyl–Paldus dimension,

$$
N_{\mathrm{CSF}}(n, N, S) = \frac{2S+1}{n+1}
    \binom{n+1}{N/2 - S}\binom{n+1}{N/2 + S + 1},
$$

which for a singlet is smaller by roughly $N/2$ and, unlike a determinant
count, distinguishes spin states. A space too large for any configured engine
is reported with its size and a warning, never refused.

Three tiers are offered. **Recommended** is the projected valence space, and is
the invariant quantity the method's claims are about. **Maximal** adds the σ
framework. **Minimal** is a gap search over the APC profile — see §8.3.

---

## 8. Results

*(Benchmark section — populated from `scripts/casbench/run_bench.py`.)*

---

## References

[1] E. R. Sayfutyarova, Q. Sun, G. K.-L. Chan and G. Knizia, "Automated
Construction of Molecular Active Spaces from Atomic Valence Orbitals",
*J. Chem. Theory Comput.* **2017**, *13*, 4063–4078.
DOI: 10.1021/acs.jctc.7b00128.

[2] D. S. King and L. Gagliardi, "A Ranked-Orbital Approach to Select Active
Spaces for High-Throughput Multireference Computation",
*J. Chem. Theory Comput.* **2021**, *17*, 2817–2831.
DOI: 10.1021/acs.jctc.1c00037.

[3] D. S. King, M. R. Hermes, D. G. Truhlar and L. Gagliardi, "Large-Scale
Benchmarking of Multireference Vertical-Excitation Calculations via Automated
Active-Space Selection", *J. Chem. Theory Comput.* **2022**, *18*, 6065–6076.
DOI: 10.1021/acs.jctc.2c00630.

[4] AEGISS: "Atomic orbital and Entropy-based Guided Inference for Selecting
active Spaces", arXiv:2508.10671 (2025).

[5] C. J. Stein and M. Reiher, "Automated Selection of Active Orbital Spaces",
*J. Chem. Theory Comput.* **2016**, *12*, 1760–1771.
DOI: 10.1021/acs.jctc.6b00156.

[6] C. J. Stein and M. Reiher, "autoCAS: A Program for Fully Automated
Multiconfigurational Calculations", *J. Comput. Chem.* **2019**, *40*,
2216–2226.

[7] E. Keller, K. Boguslawski, T. Janowski, M. Reiher and P. Pulay, "Selecting
Active Space for Multiconfigurational Quantum Chemistry",
*J. Chem. Phys.* **2015**, *142*, 244104. See also
J. J. Bao and D. G. Truhlar, "Automatic Active Space Selection Based on Natural
Orbital Occupation Numbers", *J. Chem. Theory Comput.* **2019**, *15*, 5308.

[8] B. Cordero, V. Gómez, A. E. Platero-Prats, M. Revés, J. Echeverría,
E. Cremades, F. Barragán and S. Alvarez, "Covalent radii revisited",
*Dalton Trans.* **2008**, 2832–2838.

[9] T. Yanai, D. P. Tew and N. C. Handy, "A new hybrid exchange–correlation
functional using the Coulomb-attenuating method (CAM-B3LYP)",
*Chem. Phys. Lett.* **2004**, *393*, 51–57.

[10] R. L. Martin, "Natural transition orbitals",
*J. Chem. Phys.* **2003**, *118*, 4775–4777.

[11] "Performance of Automatic Active Space Selection for Electronic
Excitation Energies", arXiv:2511.05732 (2025). Assesses the Active Space
Finder (ASF) family; reports a best mean absolute error of 0.49 eV for
l-ASF(QRO) over 32 molecules in def2-TZVPD, and 25–30% unsatisfactory results
for every scheme in fully automatic mode.

[12] P.-F. Loos, A. Scemama, A. Blondel, Y. Garniron, M. Caffarel and
D. Jacquemin, "A Mountaineering Strategy to Excited States: Highly Accurate
Reference Energies and Benchmarks", *J. Chem. Theory Comput.* **2018**, *14*,
4360–4379.

[13] M. Véril, A. Scemama, M. Caffarel, F. Lipparini, M. Boggio-Pasqua,
D. Jacquemin and P.-F. Loos, "QUESTDB: A database of highly accurate excitation
energies for the electronic structure community",
*WIREs Comput. Mol. Sci.* **2021**, *11*, e1517.

[14] M. Schreiber, M. R. Silva-Junior, S. P. A. Sauer and W. Thiel,
"Benchmarks for electronically excited states: CASPT2, CC2, CCSD, and CC3",
*J. Chem. Phys.* **2008**, *128*, 134110.

[15] B. O. Roos, K. Andersson, M. P. Fülscher, P.-Å. Malmqvist,
L. Serrano-Andrés, K. Pierloot and M. Merchán, "Multiconfigurational
Perturbation Theory: Applications in Electronic Spectroscopy",
*Adv. Chem. Phys.* **1996**, *93*, 219–331.

[16] C. Angeli, "On the nature of the π→π\* ionic excited states: the V state
of ethene as a prototype", *J. Comput. Chem.* **2009**, *30*, 1319–1333.

[17] Q. Sun *et al.*, "Recent developments in the PySCF program package",
*J. Chem. Phys.* **2020**, *153*, 024109.

[18] C. Angeli, R. Cimiraglia, S. Evangelisti, T. Leininger and J.-P. Malrieu,
"Introduction of n-electron valence states for multireference perturbation
theory", *J. Chem. Phys.* **2001**, *114*, 10252.
