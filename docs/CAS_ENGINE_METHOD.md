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

**7/14 exact, 10/14 exact or as an offered tier. Legacy matches 1/14** (water),
and refuses O₂ outright because it declines every open-shell molecule.

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
| **This work** | **0 / 14** | **0 / 14** |
| Legacy | 2 / 14 | 0 / 14 |

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

**21 of 22 reference states located, mean absolute error 0.22 eV**, and every
located state's character matched the reference label.

| Character | n | MAE (eV) |
|---|---|---|
| n→π\* | 7 | **0.10** |
| Rydberg | 4 | 0.20 |
| π→π\* | 10 | 0.31 |

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

**All 11 CASSCF calculations converged. SC-NEVPT2 MAE 0.43 eV over 18 states.**

| Character | n | MAE (eV) | mean signed (eV) |
|---|---|---|---|
| n→π\* | 7 | **0.15** | −0.01 |
| π→π\* | 11 | 0.60 | −0.12 |
| π→π\* excluding formaldehyde's V state | 10 | 0.37 | — |
| **all, excluding that one state** | **17** | **0.28** | — |

The n→π\* result is the one to note: 0.15 eV mean absolute error with a mean
*signed* error of −0.01 eV, i.e. no systematic bias. These are exactly the
states a ground-state selection criterion loses, and they are the best-described
states in the set.

One state dominates the aggregate. **Formaldehyde's ¹B₂ π→π\* comes out 2.99 eV
low.** This is not a failure of active-space selection: the V state of a
carbonyl or an alkene is strongly ionic, and its description is a well-known
difficulty for a small valence π space in a double-zeta basis, requiring both
σ-correlation and a more diffuse description than CAS(6,4)/cc-pVDZ has [16].
Ethylene's analogous V state is the second-worst π→π\* case here, at +0.41 eV
after NEVPT2 — and note the SA-CASSCF value for it is +2.30 eV, so the
perturbative correction is doing most of the work. Reporting the aggregate
without this decomposition would attribute a known limitation of the *method
that follows* to the selection that preceded it.

### 8.5 Against the published bar

The best fully automatic scheme in the current literature, l-ASF(QRO), reports
**0.49 eV MAE over 32 molecules in def2-TZVPD** [11], with 25–30% unsatisfactory
results across every scheme that study tested in fully automatic mode.

The 0.43 eV here (0.28 eV excluding the one ionic outlier) is **not
like-for-like** and should not be read as a win: a different and smaller
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
