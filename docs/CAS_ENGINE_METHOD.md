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
entropy changes the cost by orders of magnitude and, as §5.1 shows, changes
what the entropy is *for*.

**What is new here** is threefold:

- **Geometric orientation of the reference orbitals** (§4). The reference set
  is built from directions derived from the molecular structure rather than
  named in the laboratory frame. This is what makes the result invariant to
  rotation and, in combination with the fixed minimal reference basis, to the
  choice of calculation basis. AVAS as published and as implemented in PySCF
  does not have this property; §8.2 measures the failure.
- **σ-completion as a correctness requirement** (§4.3), which removes the need
  for the hydride special-casing that a π/lone-pair-only target set forces.
- **Orbital-character classification of the requested states** (§6), which
  reports and verifies against what each state is actually made of rather than
  against how many configurations a space can hold. The augmentation that would
  *act* on that classification is implemented but not yet wired into the
  shipped pipeline — see §6.4 and §8.8.

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

### 5.1 What the entropy is actually for here

Applying the ranking after the projection rather than before it changes its
role, and the change is measurable. Over water, formaldehyde, benzene, pyrrole
and butadiene, the relative APC entropies inside the projected pool span only
**0.55 to 1.00** — never an order of magnitude.

That is not a defect in the entropy. It is the projector having already made
the selection on chemical grounds, so every orbital that reaches the ranking is
genuinely relevant. In AutoCAS [5,6] and AEGISS [4] the entropy ranks a pool of
around a hundred frontier orbitals of which most are inert, and an absolute cut
at $S_{\max}/10$ discards the bulk of them. Applied to a pool that is already
tight, the same rule discards nothing — the right answer for the wrong reason.

A *gap* search says something meaningful about a flat profile: it fires only
where there is a real shoulder. At a relative gap of 0.15 it recovers the
classical small spaces — formaldehyde (4e,3o), the textbook n/π/π\* space, and
pyrrole (6e,5o), its textbook π space — while correctly declining to cut benzene
below (6e,6o) or butadiene below (4e,4o), where every π orbital genuinely
matters. That is what the minimal tier is.

The ranking's remaining jobs are ordering the maximal tier, which is large, and
supplying the repair rule that keeps a subset from being chemically
half-finished.

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

### 6.4 Augmentation — implemented, not yet wired

**What ships today.** The classification of §6.3 is used to *report* each state
and to *verify* that the recommended space contains it (§6.5 and `verify.py`).
The space itself is the valence projection of §4, and does not change with the
requested number of states.

**What is written but not connected.** `excited.augment()` projects each
requested state's dominant hole and particle NTOs against the space already
chosen, takes the residual as the part the space cannot describe, and where its
norm exceeds 0.3 orthonormalises and appends it. Rydberg particle orbitals are
deliberately excluded: they are diffuse, do not mix appreciably with the
valence orbitals, and including them in a CASSCF is a well-known route to
convergence trouble without improving the valence states.

It is not called by the runner. Its signature takes the projected pool while
the runner holds the assembled recommendation, and reconciling those is a
change that wants its own testing rather than one made at the end of a large
piece of work. On this benchmark set it would have changed nothing — §8.4's
verification finds every predicted valence state already present in the
projected space, which is *why* those numbers look as they do — but that is a
property of the molecules tested, not a demonstration that augmentation is
unnecessary. §8.8 records it.

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

All numbers below come from `scripts/casbench/run_bench.py`, run in process on
the geometries and reference values in `scripts/casbench/reference_data.py`.
Every reference value carries its citation there. The legacy column is the
previous engine's AVAS seeding and truncation, called directly, so what is
compared is the *space each method chooses*, not the CASSCF that used to follow
it.

### 8.1 The recommended space against the literature

Fourteen molecules with a well-established active space in the multireference
literature. "Exact" means the recommended tier matched; "tier" means one of the
three offered tiers matched.

| Molecule | Literature | Recommended | Minimal | Maximal | Match | Legacy | Time (s) |
|---|---|---|---|---|---|---|---|
| ethylene | (2,2) | **(2,2)** | (2,2) | (12,12) | exact | (10,7) | 0.09 |
| butadiene | (4,4) | **(4,4)** | (4,4) | (22,22) | exact | (16,12) | 0.21 |
| benzene | (6,6) | **(6,6)** | (6,6) | (30,30) | exact | (12,12) | 0.43 |
| formaldehyde | (6,4) | **(6,4)** | (4,3) | (12,10) | exact | (10,7) | 0.09 |
| acetone | (6,4) | **(6,4)** | (4,3) | (24,22) | exact | (18,12) | 0.23 |
| pyridine | (8,7) | **(8,7)** | (8,7) | (30,29) | exact | (12,12) | 0.47 |
| water | (8,6) | **(8,6)** | (8,6) | (8,6) | exact | (8,6) | 0.06 |
| pyrrole | (6,5) | (8,6) | **(6,5)** | (26,25) | tier | (14,12) | 0.29 |
| N₂ | (10,8) | (8,7) | (4,5) | **(10,8)** | tier | (8,7) | 0.28 |
| O₂ (triplet) | (12,8) | (10,7) | (6,5) | **(12,8)** | tier | *refused* | 0.06 |
| acrolein | (8,7) | (8,6) | (6,5) | (22,20) | differs | (14,12) | 0.19 |
| formamide | (8,7) | (10,6) | (10,6) | (18,15) | differs | (16,11) | 0.15 |
| furan | (6,5) | (8,6) | (8,6) | (26,24) | differs | (14,12) | 0.27 |
| *p*-benzoquinone | (12,10) | (16,12) | (16,12) | (40,36) | differs | (12,12) | 0.82 |

**Restated for 17 molecules (2026-09-02).** Fifteen carry a literature space;
o-nitrophenol and methane do not. **10/15 match exactly or as an offered tier.
Legacy matches 1/15** (water), and refuses O₂ outright because it declines
every open-shell molecule.

Uracil is the notable addition and the notable miss: the quick engine gives
CAS(22e,14o) against a literature (14e,10o), because it keeps all six
lone-pair-derived orbitals when three states use two of them. The refinement
tier of §9 takes it to (14e,9o). That is the clearest case in this benchmark of
the two tiers doing different jobs.

The four that differ share a pattern: all are heteroatom systems where the
engine includes the in-plane lone pairs that the π-only literature space omits.
For furan the engine gives (8,6) against the classical (6,5) π space; the extra
orbital is the oxygen in-plane lone pair. That is a defensible difference rather
than an error — it is precisely the orbital an n→π\* state needs — but it is a
difference, and §8.4 shows what it costs and buys. *p*-benzoquinone is the known
hard case in the automatic-selection literature [11]; the engine's (16,12)
against the reference (12,10) again reflects both carbonyl oxygens' lone pairs.

Recommending all fourteen took 3.6 s in total.

### 8.2 Invariance

Each molecule recommended in five basis sets (STO-3G, cc-pVDZ, def2-SVP,
def2-TZVP, aug-cc-pVDZ) and under five random rotations of its input geometry.

| | changes with the basis | changes under rotation |
|---|---|---|
| **This work** | **0 / 15** | **0 / 15** |
| Legacy | 2 / 15 | 0 / 15 |

Legacy's two basis-dependent cases are acrolein, which gives (16e,12o) in
STO-3G and (14e,12o) in every larger basis, and pyrrole, which alternates
between (14e,12o) and (12e,12o).

**Legacy's rotation invariance deserves an explanation, because it initially
looks like a contradiction.** §4.1 explains why stock AVAS is *not* rotation
invariant when given an axis-aligned label such as `C 2px`. Legacy avoids that
by targeting the whole p shell (`C 2p`), and a complete shell is invariant under
rotation. The price is that a whole shell cannot distinguish π from σ, which is
why legacy returns (16e,12o) for butadiene where the answer is (4e,4o), and then
has to truncate to a twelve-orbital cap.

So the previous design faced a genuine dilemma: name a single p component and
lose rotation invariance, or take the whole shell and lose chemical
discrimination. Orienting the target from the geometry is what escapes it, and
that is the central claim of this method.

### 8.3 State identification

TDA/CAM-B3LYP in aug-cc-pVDZ, ten roots, against the QUEST theoretical best
estimates [12,13]. Each reference state was matched to a computed state by
character, never by index.

**23 of 24 reference states located, mean absolute error 0.23 eV**, and every
located state's character matched the reference label. (Restated for 17
molecules; the 14-molecule figure was 21/22 at 0.22 eV.)

Individual results worth pointing at:

- **formaldehyde n→π\***, oscillator strength 0.0000 to four decimals: found at
  3.94 eV against 3.98. A dark state, located by what its orbitals are.
- ***p*-benzoquinone's two near-degenerate n→π\* states** (2.79 and 2.85 eV):
  both found, at 0.03 eV. This is the case the ASF study singles out as needing
  four-state averaging to get right [11].
- **acrolein**, a dark n→π\* at 3.58 eV (TBE 3.74) *below* a bright π→π\* at
  6.50 eV (TBE 6.68): both characters correct, ordering correct.
- The single miss is **formaldehyde's π→π\* at 9.22 eV**, which lies above the
  ten-root window.

### 8.4 End to end: SA-CASSCF then SC-NEVPT2 in the recommended space

The recommended space taken through a state-averaged CASSCF and strongly
contracted NEVPT2 [18] in cc-pVDZ. Reference states are matched to computed
roots by character, using the transition density matrix of each root — never by
index, which §8.6 shows was worth doing.

**SC-NEVPT2 MAE 0.32 eV over the 16 states whose CASSCF converged**, 0.55 eV
if the two non-converged molecules (p-benzoquinone, uracil) are included. Every
root is a singlet, which had not been true of any earlier run — see §11.1.

| Character | n | SC-NEVPT2 MAE | mean signed (eV) |
|---|---|---|---|
| n→π\* | 5 | **0.24** | — |
| π→π\* | 10 | 0.38 | — |
| **all converged** | **16** | **0.32** | — |

**The largest deviation in the whole set is +0.48 eV** (ethylene's π→π\*),
followed by pyridine +0.47, pyrrole +0.43, acrolein −0.41 and furan +0.40. That
flat tail is the result worth reading, not the mean.

**This replaces a figure of 0.29 eV that was not valid, and the difference is
instructive.** Earlier runs reported 0.29 eV and looked better. They were
matching QUEST *singlet* reference states against roots that were partly
triplets (§11.1), and they carried outliers of ±3 eV — formaldehyde's V state
at −2.99 eV, acrolein's π→π\* at −3.05 — which came and went depending on
which root a mislabelled character happened to match. The spin-correct set has
a slightly higher mean and **no outlier above half an electronvolt**. A tighter
distribution with a worse headline is the better result, and the headline moved
because the measurement was wrong before, not because the engine changed.

The V-state difficulty is not solved by any of this: an ionic π→π\* is hard for
a small valence π space in a double-zeta basis [16]. What changed is that
ethylene's and formaldehyde's are now described to within half an electronvolt
instead of appearing as multi-eV artifacts of a spin-contaminated state average.

**Two molecules do not converge**, and they are the two largest spaces:
p-benzoquinone CAS(16e,12o) and uracil CAS(22e,14o), both over six roots. They
are named in the output and excluded from the headline rather than averaged in.
Note that the three that failed before (formamide, furan, pyrrole) now converge
in a fifth of the time — a state average confined to one multiplicity is a
better-conditioned problem than one mixing two, so the spin constraint of §11.1
paid for itself in convergence as well as in correctness.

### 8.5 Against the published bar

The best fully automatic scheme in the current literature, l-ASF(QRO), reports
**0.49 eV MAE over 32 molecules in def2-TZVPD** [11], with 25–30% unsatisfactory
results across every scheme that study tested in fully automatic mode.

The 0.29 eV here is **not like-for-like** and should not be read as a win: a different and smaller
molecule set, a smaller basis, and a different downstream. What can be said is
that the two are of comparable magnitude, that this engine's failures are
concentrated in one identifiable and well-understood class of state, and that it
reaches that accuracy from a selection costing 0.26 s per molecule rather than
one requiring an MP2 natural-orbital pass followed by a DMRG-CASCI cumulant
analysis.

The comparison that *is* controlled is against legacy, and there the result is
unambiguous: 10/14 against 1/14 on literature spaces, 0/14 against 2/14 on basis
dependence, no orbital cap against a hard ceiling of twelve, and open-shell
molecules answered rather than refused.

### 8.6 The handoff

`tests/backend/cas_09_portable_spec.py` measures what happens when the space
recommended in def2-SVP is handed to a calculation in another basis. Pyrrole's
recommendation is CAS(8e,6o).

| Handoff into | by MO index (smallest principal cosine) | by specification |
|---|---|---|
| STO-3G | 0.000 | **(8,6)** |
| cc-pVDZ | 0.999 | **(8,6)** |
| def2-TZVP | 0.989 | **(8,6)** |
| aug-cc-pVDZ | **0.000** | **(8,6)** |

An index handoff nearly survives between two double-zeta bases, where the
orbital count and ordering happen to line up, and fails completely into
aug-cc-pVDZ because diffuse functions reshuffle the virtual manifold: the same
indices name an entirely orthogonal set of orbitals. Since a diffuse basis is
exactly what a user moves to when Rydberg states matter, this is not an edge
case. The specification reproduces the space in all four.

**This is measured, not yet delivered.** Every recommendation writes
`active_space_spec.json` and `spec.rebuild_in_basis` is what produces the right
column above, but no runner reads it yet: a follow-up CASSCF still reuses
orbitals through `initial_orbitals_job_id`, which is the molden path this table
shows to be basis-locked. What the table establishes is that the mechanism
works and that the problem it solves is real. Connecting it is listed in §8.8.

### 8.7 Cost

| Stage | Cost |
|---|---|
| SCF reference | ~0.2 s (def2-SVP, 10 heavy atoms) |
| Perception + projection | milliseconds |
| APC ranking | ~0.1 s |
| Whole ground-state recommendation | **0.26 s mean, 0.82 s max** over the 14 |
| TDA, 8 roots, pyrrole | 3 s (def2-SVP), 21 s (def2-TZVP) |
| Verification CASCI | seconds, skipped above 5×10⁵ CSFs |

For comparison, legacy's entropy pilot was an exact FCI over a pool capped at
twelve orbitals, or a DMRG pass capped at thirty, and every recommendation ended
in a full state-averaged CASSCF.

### 8.8 What is not established

- **The recommended space does not yet change with the state count.**
  `excited.augment()` exists and is described in §6.4; the runner does not call
  it. What the state count changes today is what is reported and what the
  verification checks for, not which orbitals are selected. On this benchmark
  set the projected valence space already contained every predicted valence
  state, so nothing here would have moved — but that is a fact about these
  molecules.
- **The portable specification is written but not consumed.** Every
  recommendation emits it and §8.6 shows it works; the follow-up CASSCF still
  takes the basis-locked `initial_orbitals_job_id` route.
- **The excited-state analysis was benchmarked in aug-cc-pVDZ**, while the
  engine's own default when states are requested and no basis is given is
  def2-SVPD. Both carry diffuse functions and the Rydberg detection works in
  both, but §8.3's specific energies are aug-cc-pVDZ numbers.
- **The job drawer's new panel is not browser-verified**, which this project
  requires for frontend work. It compiles under the production build and
  renders keys checked against a real runner call; nobody has looked at it.
- **Open-shell excited states.** The excited-state branch is closed-shell only.
  UKS natural transition orbitals are per-spin and spin-contaminated, and there
  is no QUEST-grade open-shell excited-state reference data in this set. The
  ground-state path works for open-shell molecules and is tested
  (`cas_04_open_shell.py`); the excited branch on top of it is not claimed.
- **Transition metals.** A `metal_d` target kind exists and emits the whole
  valence d shell unoriented, but no transition-metal complex is in the
  benchmark, so nothing about metal active spaces is established here.
- **The minimal tier is not basis-invariant**, and is not claimed to be. It
  comes from a gap search over an entropy profile, and pyrrole sits close enough
  to the threshold that cc-pVDZ and def2-TZVP disagree. The *recommended* tier
  is the invariant quantity and the one the method's claims are about.
- **DMRG verification above the CSF limit** is not implemented. block2 is
  installed and the route is understood, but an unrun check is not a check, so
  a space too large for exact CASCI is reported as unverified.
- **The literature comparison in §8.1 is against a convention, not ground
  truth.** "The" active space for a molecule is not unique; the reference column
  records what is commonly used, and where the engine differs the difference is
  described rather than scored as an error.

---

### 8.9 Verdict on the previous engine

The two runners this replaces are kept in `scripts/casbench/legacy_cas_reco.py`,
reachable only from the benchmark, so the comparison stays reproducible. On the
evidence above they can be deleted:

| | this work | legacy |
|---|---|---|
| Literature space matched | **10 / 15** | 1 / 15 |
| Space changes with the basis | **0 / 15** | 2 / 15 |
| Open-shell molecules | **answered** | refused |
| Orbital cap | **none** | 12, refused above |
| Recommendation cost | **0.26 s mean** | seconds to minutes, plus a full SA-CASSCF |
| States identified by character | **23 / 24, MAE 0.23 eV** | not attempted |
| Handoff survives a basis change | **yes** | no (§8.6) |

There is no axis on which the previous engine is ahead. The one property it has
that this work initially appeared to lack — rotation invariance — it has for a
reason that costs it everything else: it targets whole p shells, which cannot
distinguish π from σ, which is why it returns (16e,12o) for butadiene where the
answer is (4e,4o) and then truncates to its cap.

The recommendation to delete is therefore made, but deliberately not executed in
the same change that measures it. Keeping the file for one release costs
nothing, keeps the benchmark runnable by anyone who wants to check these
numbers, and means the deletion is a separate, reversible commit rather than
something bundled into the change that justified it.


## 9. The refinement tier

Everything above chooses a space *a priori*. The projector asks which orbitals
carry the chemistry, the APC entropy estimates which carry correlation, and no
CASSCF is ever run — which is what removes any ceiling on the space and keeps a
recommendation to about a quarter of a second. The cost is that nothing
measures what was predicted.

The refinement tier is the opposite trade, and it is opt-in: a separate job,
offered after a recommendation exists, taking minutes rather than a second
because it solves where the recommendation predicted.

### 9.1 What a converged CASSCF can see that an estimate cannot

**Orbitals rotate.** A CASSCF optimises orbitals as well as CI coefficients,
and the space it converges to need not be the space it was handed. The
verification of §6.5 cannot observe this: it is a CASCI, orbitals frozen, so by
construction the rotation is invisible to it.

**Occupations measure what the entropy estimated.** For a state-averaged
density with natural occupations $n_p$, an orbital with $n_p \to 2$ or
$n_p \to 0$ across every averaged root contributes to no configuration of
weight. That is a measurement; the APC entropy of §5 is a closed-form guess at
the same quantity.

### 9.2 The loop, and why its order is what it is

Per cycle: solve, audit, correct, prune, re-verify.

The **character audit** is computed over the subspace, not per orbital:

$$
W_{\mathcal{T}}(\mathcal{A}) \;=\;
\operatorname{Tr}\!\left[
\mathbf{P}_{\mathcal{A}}^{\dagger}\,\mathbf{P}_{\mathcal{A}}
\right],
\qquad
\mathbf{P}_{\mathcal{A}} = \tilde{\mathbf{X}}^{\dagger}\mathbf{S}^{pc}\mathbf{C}_{\mathcal{A}}
$$

with $\tilde{\mathbf{X}}$ the orthonormalised target set and
$\mathbf{C}_{\mathcal{A}}$ the active orbitals. $W$ counts orbitals' worth of
target character, and comparing it before and against after the optimisation
says how much left.

Per-orbital labelling would be the obvious alternative and is not usable, for a
structural reason rather than an empirical one: a CASSCF may rotate arbitrarily
*within* its active space, so "the character of active orbital $j$" is not
well defined — the same space relabels under such a rotation. A trace over a
projector is invariant to exactly those rotations, which
`tests/backend/cas_10_refinement.py` verifies by applying a random unitary to
the active block and checking $W$ is unchanged to $10^{-8}$ while the
per-orbital labels flip.

**The ordering constraint is the whole design, and it was arrived at by getting
it wrong first.** Firing a correction on character loss alone dead-ends:
uracil's recommended space gives back 4.3 orbitals' worth of lone-pair
character when asked for three states — because three states do not need six
lone pairs — and forcing it back fights the correct answer. Character leaving
has two meanings needing opposite responses, and it is the **state audit** that
distinguishes them:

| a predicted state is | character has | response |
|---|---|---|
| missing | left | the space lost what it needed → narrow, then re-seed |
| missing | not left | → augment with the state's NTOs |
| present | left | the space held orbitals no state uses → **prune** |

**A margin of extra roots is required.** A linear-response pass and a CASSCF do
not order states alike. TDA puts uracil's n→π\* at S₁; the two lowest CASSCF
excited roots of that space are both π→π\*. Solving for exactly the requested
number of roots reports the state missing forever. The loop solves for
$N_{\text{states}} + 3$ and records which root each predicted state landed on,
so "the n→π\* is root 3, three states will not reach it" is reported rather
than silently mishandled.

**Pruning is only ever kept against evidence.** A candidate set is dropped, the
space re-solved, and the cut accepted only if every predicted state survives
*and* no requested excitation moved by more than 0.2 eV. Presence alone is too
weak: a state can survive a smaller space and shift half an electron-volt.

### 9.3 The trap this is built around

On uracil, asked for three states, both carbonyl lone pairs converge to natural
occupations of about 2.00 and look perfectly inert. They are not. The n→π\*
state built on them is absent from the CASSCF roots entirely, and 4.3 orbitals'
worth of lone-pair character has left the active space. Pruning on occupation
alone discards both, that state becomes unreachable, and the calculation
appears to have proved it was never needed.

Two readings of this were wrong on the way, and are recorded because the
retraction matters more than the result:

- An early probe suggested a six-root average left one lone pair at 1.667,
  implying the root count was protective. **That run had not converged.** A
  converged six-root average puts both back at about 2.00. More roots do not
  rescue them; the state audit does.
- An early note claimed every converged π orbital reports a σ weight of 0.98,
  as the argument against per-orbital labelling. **Not reproducible** — about
  0.98 on state-averaged natural orbitals, about 0.00 on canonical ones. The
  invariance argument of §9.2 is the one that holds.

### 9.4 Where to start, settled by measurement

Whether to start from the largest space and let evidence cut it down, or the
smallest and grow. Measured on four molecules in cc-pVDZ, all three tiers:

| | formaldehyde | pyrrole | furan | uracil |
|---|---|---|---|---|
| maximal tier | 13,860 CSFs | 3.9×10¹² | 9.3×10¹¹ | 3.3×10¹⁸ |
| maximal runnable? | yes | **no** | **no** | **no** |
| from recommended | (6,4)→(6,4), 0.5 s | (8,6)→**(6,5)**, 26 s | (8,6)→(4,4), 28 s | 33 min, unchanged |
| from maximal | (12,10)→(12,10), **197 s, unconverged** | fell back | fell back | fell back |

**Maximal is wrong decisively.** For three of four it is unreachable by six to
thirteen orders of magnitude, so requesting it merely falls back. Where it can
be run it was 400 times slower, did not converge, and pruned nothing: in a
large space correlation spreads thinly and no orbital reaches the inert
threshold, so starting big does not in fact cut anything down.

**Minimal is inert rather than wrong.** Its only path to growing is a missing
state, so where it is already right it confirms cheaply and where it is too
small it stays too small. The asymmetry that matters is not speed: recommended
can shrink on evidence, minimal cannot grow without one.

Honest limitation of this table: only formaldehyde and pyrrole actually
distinguish minimal from recommended. For furan and uracil the two tiers are
the same space, so those columns are the same run reported twice.

The default is therefore the **recommended** tier, with a CSF budget of $10^6$
— a budget sized for one affordable CASSCF is the wrong scale for a loop that
runs several, and every refinement that did useful work ran well under it.

### 9.5 Narrowing, and what it fixed

Uracil exposed that the expensive failure was the *recommendation*, not the
refinement. Its CAS(22e,14o) carries all six lone-pair-derived orbitals, four
of which no requested state touches, and those dilute the state average the
missing state has to be found in. Refining from there ran 33 minutes and
returned the space it started with.

So a missing state now triggers a narrowing before the re-seed loop — keep the
π system plus the orbitals the requested states occupy — and uracil goes to
**CAS(14e,10o) automatically**, the space derived by hand when this feature was
scoped, at 4,950 CSFs against 41,405. The whole refinement then takes 928 s
rather than 33 minutes.

### 9.6 What it returns

A refined $(N, n)$ is not reproducible on its own, so the result carries an
ordered **rotation trail**: every narrow, re-seed, augment and prune, with the
orbital and the occupation or character that justified it. Plus the converged
orbitals as a molden, so a production CASSCF starts exactly where refinement
finished, and a regenerated `active_space_spec.json`.

### 9.7 Results

`scripts/casbench/run_bench.py --set refine`, all 17 benchmark molecules,
cc-pVDZ, starting from the recommended tier, with a ten-minute cap per
molecule. **All 17 finished inside the cap.** Median refinement 6 s against a
median recommendation of 0.27 s; the whole set took 989 s.

| Molecule | literature | quick | refined | what happened | time |
|---|---|---|---|---|---|
| pyrrole | (6,5) | (8,6) | **(6,5)** | prune | 14 s |
| *p*-benzoquinone | (12,10) | (16,12) | **(12,10)** | prune ×2 | 176 s |
| uracil | (14,10) | (22,14) | (14,9) | narrow, reseed ×2, augment ×2 | 429 s |
| O₂ | (12,8) | (10,7) | (8,6) | prune | 2 s |
| water | (8,6) | (8,6) | (4,4) | prune ×2 | 3 s |
| o-nitrophenol | — | (24,18) | (12,10) | narrow | 30 s |
| acetone, acrolein, benzene, butadiene, ethylene, formaldehyde, formamide, furan, methane, N₂, pyridine | | | *unchanged* | no change | 0.6–47 s |

**Eleven of seventeen come back unchanged.** That is the honest headline:
refinement mostly confirms the recommendation rather than improving it, and a
tier that spends minutes to tell you the quick answer was already right is
worth having only because you cannot know that in advance.

**Where it moves, it mostly moves toward the literature.** Pyrrole reaches
(6e,5o) and *p*-benzoquinone (12e,10o), both exactly the space the
multireference literature uses, from starts of (8,6) and (16,12). Uracil goes
from (22,14) to (14,9), one orbital short of the (14,10) established for it.
o-Nitrophenol, which has no literature space, narrows from an intractable
(24,18) to (12,10).

**Two cases move away from the literature convention, and both are
ground-state-only.** O₂ goes to (8,6) against a full-valence (12,8), and water
to (4,4) against (8,6). Neither had a predicted excited state to protect, so
the only evidence available was occupations and the ground-state energy — and
in both the cut cost under 5 mHartree, meaning those orbitals genuinely carry
almost no correlation. Whether that makes (4,4) a legitimate reduction for
water or the 5 mHartree tolerance too loose is not something this benchmark
settles, and it is reported rather than resolved. What can be said is that
refinement is at its weakest exactly where it has the least evidence: a request
with no excited states gives it nothing to protect.

**The guard is doing work.** N₂ is the case that shows it: an unguarded prune
took CAS(8e,7o) to CAS(4e,4o), dropping the σ framework a triple bond needs.
With the ground-state check the cut is rejected — it would have raised the
energy 51 mHartree, 1.39 eV — and the space comes back at (8,7) with that as
the stated reason.

**Cost.** Nine molecules refine in under 10 s. Three are over 100 s
(*p*-benzoquinone 176 s, uracil 429 s, and o-nitrophenol 30 s only because the
narrowing rescued it from a 72-million-CSF start). The distribution is what
motivates the approval gate: the median case is cheap, and the expensive tail
is exactly the large conjugated systems a user is most likely to ask about.

### 9.8 What refinement does not do

- **It cannot find a state the CASSCF does not place in its window.** Uracil's
  n→π\* is not located even after narrowing and re-seeding; the engine reports
  it missing rather than returning a space chosen for a state it never saw.
- **It is minutes to tens of minutes**, against a quarter-second
  recommendation, and on the largest spaces it will not finish inside a
  ten-minute cap at all. That is why it is opt-in and why the approval card
  states the cost first.
- **Its thresholds are not calibrated across chemistry.** The [0.02, 1.98]
  occupation window and the 0.2 eV drift tolerance are defensible defaults, not
  values fitted to a benchmark.

---

## 10. The reference directions: a lone pair is an sp hybrid

Section 4 builds one oriented reference direction per perceived target. For a
σ bond that direction is an sp hybrid, and section 2B records why: a p-only
reference misses the s-derived σ and σ\*, which on N₂ is the difference between
the (10e,7o) a p-only set finds and the (10e,8o) full valence space the
literature uses.

**Lone pairs were built as pure p lobes.** The asymmetry was never deliberate,
and it is wrong for the same reason. A carbonyl oxygen's in-plane lone pair is
an sp hybrid that carries real s character and delocalises into the adjacent σ
framework; its overlap with a pure oriented p function is partial by
construction. Measured on uracil's refined space, **an orbital scoring 0.715
lone-pair character against an sp reference scores 0.019 against a pure p
one** — a factor of 39.

That single omission produced three separate failures, none of which raised an
error:

1. The projector could not see the orbitals, so the pool and every re-seed
   built from it were blind to them.
2. `_root_characters` could not recognise an sp lone-pair hole, so an n→π\*
   root was reported as π→π\*.
3. A refined uracil space was reported as holding no lone pair at all, and its
   n→π\* state as missing, when the space held about one orbital's worth.

### 10.1 Why an *oriented* hybrid, and what the alternatives cost

Three variants were measured on the fifteen molecules carrying a literature
space:

| lone-pair reference | literature spaces | that uracil orbital scores |
|---|---|---|
| pure oriented p (before) | 10 / 15 | 0.019 |
| bare valence s | 9 / 15 | 0.715 |
| two oriented references (p and sp) | 9 / 15 | 0.715 |
| **one oriented sp hybrid** | **10 / 15** | 0.327 |

A **bare valence s has no direction**, so it overlaps an atom's σ-bonding
hybrids exactly as well as its lone pair. Adding one pulled the deep σ
framework into the pool: formaldehyde fell from an exact (6e,4o) to (8e,5o) and
uracil's *minimal* tier grew from (14e,10o) to (30e,18o).

The two-reference variant is the informative failure. It detects identically to
the bare s and inflates identically, which isolates the mechanism: **the pool
grows with the number of targets that clear the projector threshold, not with
their orientation.** Detection and pool size are coupled through that
threshold, so there is no variant that is simultaneously more sensitive and
equally selective. The single oriented sp hybrid is the choice that improves
detection seventeen-fold over a pure p lobe while leaving every benchmark space
where it was.

### 10.2 Reporting character, and the n/σ band

A per-orbital label is not invariant to rotations within the active space, so
it can never be a selection criterion — that is why the audits of section 9
measure a subspace trace. But the orbitals a result *reports* are one specific
named set, and for that set a label is well defined and is what lets a user
rebuild the space by hand.

Two rules follow from the physics rather than from convenience. The π, n and σ
reference sets are each over-complete and mutually non-orthogonal, so the
weights do not sum to one and **an orbital can score highly on two of them at
once**: four of uracil's occupied orbitals score n ≈ 0.92 and σ ≈ 0.98
simultaneously, and a plain argmax hands all four to σ on a margin of about
0.06. So the continuous weights are published beside every label, never
instead of it; and a lone pair beats σ from 0.50 rather than having to win
outright, because uracil emits 44 σ targets against 6 lone-pair ones and σ
spans more by set size before any chemistry is considered. An orbital that is
substantially both is labelled `n/sigma`.

### 10.3 The orbital table is a second, independent classifier

`app/chemistry/jobs/molden.py` labels the orbitals of every CASSCF job and
shares no code with the engine above. It had the same fault in a different
form: an orbital was called `n` only if **one** atom carried more than 0.6 of
the population. A nitro, carboxyl or carboxylate group holds its lone pairs as
the symmetric and antisymmetric combinations across two equivalent oxygens, so
each carries about 0.45 and neither clears the bar; the orbital then fell
through to the shape test, where an in-plane lone pair is symmetric about the
molecular plane exactly as a σ bond is, and came back `sigma`.

The discriminator is that **a σ bond sits on a bonded pair**. Two nitro oxygens
are each bonded to the nitrogen and not to each other. A group of mutually
non-bonded heteroatoms holding an occupied orbital between them is a lone-pair
combination.

Verified against an SA-5 CASSCF(14,10) on o-nitrophenol run before any of this:
exactly two labels change, both the intended ones, and every π and π\* is left
alone. The space then reads 5π + 2n + 3π\*, and the corresponding CAS(12,9)
reads 4π + 2n + 3π\* — the assignment its S1 and S2 n→π\* states require.

## 11. How reproducible these numbers are

### 11.1 The state average was not confined to one multiplicity

Everything in §8 was measured twice, and the first set of measurements was
wrong for a reason worth stating plainly.

PySCF's plain FCI solver returns the lowest roots of **any** multiplicity.
Asking for five states of a closed-shell molecule therefore does not give five
singlets. Measured on o-nitrophenol's CAS(12e,9o) at five roots:

| root | eV | ⟨S²⟩ | 2S+1 |
|---|---|---|---|
| 0 | 0.000 | 0.000 | 1 |
| 1 | 3.735 | 2.000 | **3** |
| 2 | 4.495 | 2.000 | **3** |
| 3 | 4.826 | 2.000 | **3** |
| 4 | 6.095 | 0.000 | 1 |

Three of the five are triplets. **A triplet's one-particle transition density
from the singlet ground state is zero by spin**, so the natural transition
orbitals built from it in §6.3 are numerical noise and the character assigned
to them means nothing. That is precisely how o-nitrophenol's two n→π\* singlets
came to be reported as π→π\*, and why requested states kept coming back
"missing": the singlet being asked about had been pushed out of the root count
by triplets nobody asked for.

The production job runner has constrained this since the overhaul, using a CSF
solver rather than `fix_spin_`, and its own notes record the same discovery.
This engine, the verification CASCI of §5 and the benchmark harness were all
written afterwards and none of them did — so the engine was recommending and
verifying against a different wavefunction from the one the job would run.

Constrained to singlets, o-nitrophenol's five roots are all singlets, S1 becomes
n→π\* as the reference has it, and the excitation energies move by 0.5 to
2.3 eV. It also converges better: formamide, furan and pyrrole all failed to
converge before and now converge in roughly a fifth of the time, a state average
confined to one multiplicity being a better-conditioned problem than one mixing
two.

**Every excited-state number in this document predating that fix was
contaminated**, including two intermediate SC-NEVPT2 figures reported during
development. §8.4 carries the corrected measurement.

### 11.2 Repeat runs of the same molecule



**Less than their precision suggests, and this bounds every per-state figure in
section 8.** Three identical repeats of acrolein's SA-CASSCF, same code, same
geometry, same basis:

| | trial 1 | trial 2 | trial 3 |
|---|---|---|---|
| E₀ (Hartree) | −190.82451658 | −190.82452598 | −190.82442026 |
| root 1 (eV) | 3.080 | 3.073 | 3.201 |
| root 5 (eV) | 6.457 | 6.446 | 6.740 |
| converged | no | yes | yes |

The root nearest acrolein's 6.68 eV reference moves **0.29 eV** between
identical runs, which is enough to change which root the reference matches and
therefore to move an aggregate mean. A state average that stops without
converging still returns energies, and they enter a mean looking like results.

This was found while investigating an apparent regression: the SC-NEVPT2 mean
absolute error drifted 0.29 → 0.43 → 0.56 eV across three benchmark runs, and
the obvious reading was that the change to the reference directions had cost
0.14 eV. It had not. One of those runs differed from the next only in the
reference-state *matcher*, which cannot affect the roots, yet acrolein's root
characters changed anyway. **The drift is apparatus noise, not a result.**

What survives the noise is the split by character:

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| n→π\* (8 states) | 0.205 | 0.226 | **0.225** |
| π→π\* (11 states) | 0.378 | 0.603 | 0.854 |

The n→π\* figure is flat to 0.02 eV. All of the movement is in π→π\*, where the
set includes formaldehyde's and acrolein's ionic V states — the known-hard
cases section 8.4 already attributes to the size of a valence space and the
basis rather than to how the space was chosen. Their root assignment is exactly
what a 0.3 eV wobble flips.

**The resolution: converge properly and the drift disappears.** With tightened
energy and gradient tolerances and a second-order retry, the same benchmark
returns **0.29 eV overall, n→π\* 0.23, π→π\* 0.33** — the π→π\* figure slightly
better than the 0.378 eV measured before any of §10's changes, and both −3 eV
outliers gone. Three molecules still fail to converge (formamide, furan,
pyrrole); they are named in the output and a converged-rows-only mean of 0.28 eV
is printed beside the headline, rather than stopped-early energies being
averaged in as results.

The harness now converges harder before reporting (tighter energy and gradient
tolerances, a second-order retry keeping whichever attempt is better), names any
molecule that did not converge, prints a converged-rows-only mean beside the
headline, and states this spread in its own output. **Treat any difference
below about 0.3 eV per state, or below roughly 0.1 eV in an aggregate over
twenty states, as not measured.**

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

[19] K. Ruedenberg, M. W. Schmidt, M. M. Gilbert and S. T. Elbert, "Are atoms
intrinsic to molecular electronic wavefunctions? I. The FORS model",
*Chem. Phys.* **1982**, *71*, 41-49. The origin of selecting an active space by
occupation of the optimised natural orbitals, which is what section 9's prune
step measures.

[20] P. Pulay and T. P. Hamilton, "UHF natural orbitals for defining and
starting MCSCF calculations", *J. Chem. Phys.* **1988**, *88*, 4926-4933. The
standard reference for natural-occupation thresholds as an active-space
criterion; the [0.02, 1.98] window used here is of the same family.

[21] J. Olsen, "The CASSCF method: A perspective and commentary",
*Int. J. Quantum Chem.* **2011**, *111*, 3267-3272. On why an active space that
is correct at the starting guess need not remain so under orbital optimisation
-- the rotation problem section 9.1 measures.
