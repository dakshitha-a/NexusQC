# Geometry-Oriented Projection with Entropy Ranking for Automated Active-Space Selection

**Method of record for NexusQC's CAS recommendation engine.**

---

## Abstract

Choosing a complete active space (CAS) is the step at which a multireference
calculation is usually won or lost, and it is normally done by hand. We
describe a fully automatic selection scheme built on three ideas: candidate
orbitals are identified by projecting a converged mean field onto *oriented
target directions* derived from the molecular geometry and expressed in a fixed
minimal reference basis; the resulting pool is ordered by approximate
pair-coefficient (APC) entropy; and, when particular electronic states are
requested, the space is narrowed to the orbitals those states are actually
built from, using natural transition orbitals from a linear-response pass. An
optional refinement tier corrects the space against state-averaged CASSCF
evidence.

Because the targets live in a basis that does not change with the calculation,
the recommendation is basis independent by construction, and is measured to be
so. On a thirty-molecule benchmark spanning planar organics, non-planar
heteroatoms, diradicals, bond dissociation, conjugated systems up to fourteen
$\pi$ orbitals, and charged species, the recommended space reproduces the
literature space exactly for 25 of 30 molecules for a ground-state request and
27 of 30 when excited states are specified. A ground-state recommendation
costs 0.23 s at the median. Downstream, strongly contracted NEVPT2 in the
recommended spaces gives a mean absolute error of 0.30 eV against theoretical
best estimates over 18 states.

---

## 1. Introduction

A CASSCF calculation requires the user to choose, in advance, which orbitals
and electrons are treated exactly. The choice is not a convenience: an active
space that omits an orbital a state is built from does not describe that state
at all, and the calculation returns a converged, plausible, wrong answer with
no diagnostic to say so. Conversely a space that is too large is not merely
expensive but frequently unconvergeable, since the cost of the configuration
interaction problem grows combinatorially with the number of active orbitals.

The conventional remedy is expert judgement, which does not scale and does not
reproduce. Several automatic schemes exist. AVAS [1] projects the mean field
onto atomic valence orbitals selected by symbol and shell. The ranked-orbital
approach of King and Gagliardi [2, 3] scores orbitals by an approximate
pair-coefficient entropy computed in closed form. AutoCAS [5, 6] takes orbital
entropies from a cheap DMRG pilot calculation. Threshold schemes select on
natural-orbital occupation numbers [7, 20]. The Active Space Finder family has
recently been assessed on excitation energies [11].

Three problems recur across these approaches and motivate the present work.

**Basis dependence.** A scheme that selects orbitals by index, or that ranks
over the full molecular-orbital space, gives different answers in different
basis sets, because the virtual manifold it ranks over grows with the basis.
Measured here, ranking raw APC over all molecular orbitals returns
CAS(18e,12o) for pyrrole in def2-SVP and CAS(22e,13o) in def2-TZVP.

**State blindness.** A ground-state criterion identifies orbitals carrying
static correlation. That is not the same question as which orbitals a
*particular* excited state is made of. A dark $n \rightarrow \pi^*$ state
requires the heteroatom lone pair in the space; no measure of ground-state
correlation will reliably put it there.

**Size is not span.** The most consequential finding of this work is that a
recommended space can match the published size exactly and still be unable to
describe the state it was sized for. Sizes are what automatic schemes are
usually scored on, and they do not measure reachability.

We address these by projecting onto geometric targets in a fixed minimal
basis, by asking the requested states which orbitals they use before
selecting, and by measuring span directly rather than inferring it from
counts.

---

## 2. Methods

The pipeline is: perceive targets from the geometry $\rightarrow$ project the
mean field onto them $\rightarrow$ rank the pool by entropy $\rightarrow$ emit
size tiers $\rightarrow$ (if states are requested) analyse them and narrow
$\rightarrow$ (optionally) refine against CASSCF.

### 2.1 Perception: targets from geometry alone

Bonds are perceived from covalent radii [8]: atoms $i$ and $j$ are bonded when
$|\mathbf{r}_i - \mathbf{r}_j| < \tau (R_i + R_j)$ with $\tau = 1.30$. Three
kinds of oriented direction are then emitted.

**$\pi$ normals.** At an atom with exactly two neighbours, the normal to the
plane they define, $\hat{\mathbf{n}} \propto \mathbf{v}_1 \times \mathbf{v}_2$.
At an atom with three or more, the best-fit plane normal, obtained as the
right-singular vector of least variance of the centred neighbour
displacements. A fitted normal is accepted only if the centre is genuinely
planar,

$$
\max_i \left| \hat{\mathbf{v}}_i \cdot \hat{\mathbf{n}} \right| < 0.25 ,
$$

which evaluates to $0$ for a planar centre, $\approx 0.37$ for pyramidal
ammonia and $\approx 0.577$ for a tetrahedral one. Without this test the
singular value decomposition returns a confident direction of least variance
for an $sp^3$ carbon and every saturated centre acquires a spurious $\pi$
orbital.

**Lone pairs.** From the coordination geometry: for two neighbours, the
direction opposing their bisector and the normal to their plane; for three,
the direction opposing their sum, *provided the centre is pyramidal*. The
pyramidal condition uses the same planarity test, and is not a refinement: at
a planar three-coordinate centre the three bond unit vectors are coplanar and
nearly cancel, so $-\widehat{\sum_i \hat{\mathbf{v}}_i}$ is a small residual
whose direction is fixed by the deviation from trigonal symmetry rather than
by chemistry. The non-bonding density at such a centre is the $p$ orbital
perpendicular to the plane, which is already emitted as the $\pi$ target; an
in-plane lone pair would be a second claim on the same electrons.

For a *terminal* heteroatom all three non-bonding directions are emitted --
the two perpendicular to the bond and the one along it -- because which is the
true lone pair depends on bond order, which geometry does not supply. A
carbonyl oxygen's lone pairs are perpendicular to C=O; a nitrile or
dinitrogen nitrogen's lies along the axis. The projection discards whichever
holds no density, which is cheaper and more robust than perceiving bond
orders.

**$\sigma$ axes.** For every bond, the bond direction, emitted on both atoms.

### 2.2 Targets are oriented hybrids

A reference built from $p$ functions alone has the wrong shape for either a
lone pair or a $\sigma$ bond. Each target is an oriented $sp$ hybrid

$$
| t \rangle = c_s\, |\,n s\, \rangle + \sqrt{1 - c_s^{2}}\;
              \big( \hat{\mathbf{d}} \cdot | \,n\mathbf{p}\, \rangle \big),
$$

with $\hat{\mathbf{d}}$ the perceived direction. The hybrid must be *oriented*:
a bare valence $s$ has no direction and cannot distinguish one lone pair from
another on the same atom.

For $\sigma$ targets $c_s = 1/\sqrt{3}$, the $sp^2$ value. For lone pairs
$c_s = 0.20$. The lone-pair value is the single most consequential constant in
the method and is discussed in §4.2: a carbonyl's $n$ orbital is predominantly
an oxygen $2p$ in the molecular plane, perpendicular to the C=O axis, and it is
that $p$-like lone pair which performs $n \rightarrow \pi^*$, not the $s$-rich
hybrid pointing away along the bond.

### 2.3 Projection

All targets are expressed in a fixed minimal reference basis (`minao`), which
is what makes the selection basis independent: a target expressed in a basis
that does not change means the same thing in STO-3G and in aug-cc-pVQZ. The
idea of a minimal-basis reference as a bridge to chemical concepts is
Knizia's [28].

Let $\mathbf{T}$ collect the target vectors in the reference basis,
$\mathbf{S}_{pp}$ the reference-basis overlap, $\mathbf{S}_{pc}$ the
cross-overlap between reference and calculation bases, and $\mathbf{C}$ the
molecular-orbital coefficients of the $N_{\text{MO}} - n_{\text{frozen}}$
orbitals left after any frozen core the caller supplied. Define

$$
\mathbf{S}_{2} = \mathbf{T}^{\mathsf{T}} \mathbf{S}_{pp} \mathbf{T},
\qquad
\mathbf{S}_{21} = \mathbf{T}^{\mathsf{T}} \mathbf{S}_{pc} \mathbf{C}.
$$

The target set is over-complete by construction: $\sigma$ targets on bonded
neighbours overlap heavily and a lone-pair direction can be near-parallel to a
$\sigma$ one, so $\mathbf{S}_2$ is singular in general. The projector onto the
target span is therefore formed with the pseudo-inverse,

$$
\mathbf{A} = \mathbf{S}_{21}^{\mathsf{T}}\, \mathbf{S}_{2}^{+}\, \mathbf{S}_{21},
$$

symmetrised against round-off. Because $\mathbf{S}_2^{+}$ is the pseudo-inverse,
the result depends only on the *span* of the targets and never on the
particular redundant, non-orthogonal vectors chosen to describe it. This is
what makes the degenerate $\pi$ pair of a linear centre safe to emit.

$\mathbf{A}$ is diagonalised separately in the occupied and virtual blocks,

$$
\mathbf{A}_{\text{occ}} \mathbf{u} = w\, \mathbf{u},
\qquad
\mathbf{A}_{\text{vir}} \mathbf{u} = w\, \mathbf{u},
$$

and orbitals with eigenvalue $w \ge 0.2$ enter the active pool. Occupied
orbitals that do not make the cut remain doubly occupied and join the core, so
the active electron count is

$$
N_{\text{act}} = N - 2 n_{\text{frozen}} - 2 n_{\text{occ,dropped}} ,
$$

where the two subtracted terms are distinct rather than a double count:
$n_{\text{frozen}}$ is the frozen core the caller supplied, which the
projection never sees, and $n_{\text{occ,dropped}}$ is the number of occupied
orbitals the projection itself sent back to the core by leaving them below
threshold.

Open shells are handled rather than refused: a singly occupied orbital is
treated on the $\alpha$ side, following AVAS's `openshell_option=2` [1].

### 2.4 Ranking by approximate pair-coefficient entropy

The pool is ordered by APC entropy [2, 3]. For occupied $i$ and virtual $a$,
the coefficient of the doubly excited configuration
$|\Phi_{i\bar{i}}^{a\bar{a}}\rangle$ is estimated in closed form from
quantities a converged SCF already holds,

$$
c_{ia} = \frac{-K_{aa}/2}
              {\Delta_{ia} + \sqrt{(K_{aa}/2)^2 + \Delta_{ia}^2}},
\qquad
\Delta_{ia} = F_{aa} - F_{ii} .
$$

This is the lowest-root coefficient ratio of the two-state problem

$$
H = \begin{pmatrix} 0 & K_{aa}/2 \\ K_{aa}/2 & 2\Delta_{ia} \end{pmatrix},
$$

and the factor of two on the diagonal is not a normalisation choice: the
configuration being estimated is a *double* excitation, so its diagonal energy
relative to the reference is twice the one-electron gap. Two conventions here
are worth stating because they are easy to misread. $F$ and $K$ are the Fock
and exchange matrices transformed into the orbital basis being ranked, so
$K_{aa}$ is a diagonal element of the exchange matrix at virtual $a$, a sum
over occupied orbitals, and not the pair integral $K_{ia}$; and $\Delta_{ia}$
is the one-electron gap, with the doubling carried by the matrix above rather
than folded into $\Delta$. Normalising the coefficients belonging to one
orbital and reading the result as a two-state population gives a von Neumann
entropy

$$
s_p = -\sigma_p \ln \sigma_p - (1 - \sigma_p) \ln (1 - \sigma_p),
\qquad
\sigma_p = \frac{\sum_q c_{pq}^{2}}{1 + \sum_q c_{pq}^{2}} .
$$

The APC-$N$ variant ($N = 2$) repeats the estimate, promoting the
highest-entropy virtual to singly occupied each round, so that a single
low-lying virtual cannot dominate the ordering. A singly occupied orbital is
open shell by definition and is given top rank rather than a computed value.

The cost is the point: this requires only the Fock and exchange matrices, with
no CASCI, MP2, DMRG or iteration, and takes about 0.1 s.

**Ranking is performed inside the pool, never over the whole MO space.** This
is what keeps the method basis independent; ranking over all molecular
orbitals reproduces the basis dependence quoted in §1.

### 2.5 Size tiers

Three tiers are emitted. The **recommended** tier is the projected pool. The
**minimal** tier is the entropy-ranked head of that pool, cut at the largest
relative gap in the sorted entropy profile, provided that gap exceeds $0.15$;
if the profile is flat there is no defensible cut and the minimal tier is the
whole pool. The **maximal** tier is the pool projected from the extended target
set, which adds the $\sigma$ framework. When the recommended tier was already
built from that extended set -- an alkane with no $\pi$ system and no lone
pairs, or a molecule whose valence pool is full and therefore not a space at
all -- the maximal tier is identical to the recommended one rather than a
larger alternative.

Cost is reported and never enforced. The number of configuration state
functions for $n$ orbitals, $N$ electrons and total spin $S$ follows the
Weyl-Paldus dimension formula [23],

$$
N_{\text{CSF}} = \frac{2S + 1}{n + 1}
                 \binom{n + 1}{\tfrac{N}{2} - S}
                 \binom{n + 1}{\tfrac{N}{2} + S + 1},
$$

and is reported per tier alongside the number of roots a state average would
solve, since a state average over $R$ roots solves $R$ CI problems per
macro-iteration and cost tracks the product $R \cdot N_{\text{CSF}}$.

### 2.6 The excited-state branch

When $n_{\text{states}} > 1$ the analysis basis moves to one carrying diffuse
functions, and a linear-response pass runs: TDA [27] on a range-separated
hybrid (CAM-B3LYP [9]), for at least twice the requested number of roots. A
range-separated functional matters because TDA on a Hartree-Fock reference is
CIS, which overestimates valence excitations by of order an electronvolt and
misorders them, and state *ordering* is what this branch depends on.

Each root's transition density matrix $\mathbf{T}$ is decomposed into natural
transition orbitals [10] by singular value decomposition,

$$
\mathbf{T} = \mathbf{U}\, \boldsymbol{\sigma}\, \mathbf{V}^{\dagger},
$$

whose leading pair names the hole and the particle. Characters
($\pi \rightarrow \pi^*$, $n \rightarrow \pi^*$, Rydberg) follow from
projecting hole and particle onto the perceived targets.

Whether a Rydberg state can be described at all is decided per calculation
rather than from the basis set's name. The test asks whether the mean field
offers a virtual orbital with more than half its density outside $1.5$ van der
Waals radii of every atom. An exponent-based rule fails in both directions:
def2-SVPD's smallest carbon exponent is $0.067$ against a $0.05$ cut, so a
basis routinely used for Rydberg states is reported as having none, while
aug-cc-pVDZ is reported as carrying no diffuse functions on N$_2$ and F$_2$
because those elements' augmenting shells are less diffuse in absolute terms
than carbon's ordinary valence ones.

### 2.7 State narrowing

Given the requested states, the space is narrowed to the $\pi$ system plus the
lone pairs those states are built on. Heteroatom centres are identified from
the hole natural transition orbital by Mulliken population [26]: a centre
qualifies when it carries at least $10\%$ of the hole. Two lone pairs are kept
per $n \rightarrow \pi^*$ state, taken round-robin over centres by rank so the
first pass takes one from each.

Two alternative rules were measured and rejected. *Coverage of the hole* fails
because an $n \rightarrow \pi^*$ hole expressed in the projector's eigenbasis
smears across most of the lone-pair block; uracil's needs four of its six
orbitals to reach 90% even though the chemistry is two carbonyl lone pairs.
*Growing while the budget allows* fails instructively: adding an occupied
orbital to a nearly-full space *reduces* the CSF count -- CAS(24e,15o) is
63,700 CSFs where CAS(22e,15o) is 496,860 -- so a greedy fill exploits the
combinatorics rather than choosing chemistry.

The rule assumes the requested states have valence character to aim at. Where
they do not -- a state list that is entirely Rydberg -- the hole has no
significant population on any valence centre, the narrowing has nothing to
select, and its output is not stable between runs. This is a known limitation
rather than a guarded case; see §4.3.

### 2.8 The refinement tier

An optional second job corrects the space against state-averaged CASSCF
[22, 24] evidence, in cycles of at most four:

1. Solve SA-CASSCF over $n_{\text{states}} + 3$ roots. The margin exists
   because a linear-response pass and a CASSCF need not order states
   identically.
2. **Character audit.** Confirm the selected $\pi$ and lone-pair character
   survived orbital optimisation; a space correct at the starting guess need
   not remain so under optimisation [21].
3. **State audit.** Confirm each requested state is present. A missing state
   triggers a re-seed, then augmentation from the natural transition orbitals.
   A predicted Rydberg state is reported as deliberately not looked for rather
   than chased, since a valence space cannot hold one.
4. **Prune.** Drop orbitals whose state-averaged natural occupation [25] lies
   outside $[0.02, 1.98]$, then re-solve and confirm nothing was lost and no
   requested excitation moved by more than $0.20$ eV. The prune is undone if
   either check fails.

The state average is spin-adapted through a CSF-based solver [29]; failure to
spin-adapt is reported rather than swallowed, because a triplet's transition
density from a singlet reference vanishes by spin and every character built
from a contaminated average is noise.

Solver tolerances are `conv_tol` $10^{-8}$, `conv_tol_grad` $10^{-5}$, and 100
macro-iterations. These were set by measurement, not by preference: see §3.5.

### 2.9 Hole capture: measuring span rather than size

The results of §3.4 rest on a measurement that is not part of the selection
pipeline but is the instrument used to validate it, so it is defined here.

Let $|h\rangle$ be the hole natural transition orbital of a requested state,
obtained from the decomposition of §2.6, and let $\mathbf{Q}$ be an
orthonormal basis for the selected active columns. The **capture** of that
state's hole by the space is

$$
\kappa = \frac{\langle h | \mathbf{Q}\mathbf{Q}^{\dagger} | h \rangle}
              {\langle h | h \rangle} \in [0, 1],
$$

the fraction of the hole lying inside the active space. $\kappa \approx 1$
means the configurations that build the state are available to the CI;
$\kappa$ substantially below 1 means they are not, no matter how many roots are
solved for, because the amplitude simply is not in the space.

This is a direct measure of *reachability*, where electron and orbital counts
measure only *size*. The two are independent, which is the point: §3.4 records
a space matching its literature size exactly at $\kappa = 0.376$.

### 2.10 Portable handoff

The recommendation is written to disk as the *question* rather than the answer:
the oriented targets in the minimal reference basis, the thresholds, the tier
sizes, and the geometry. Given any later mean field, re-asking that question
reproduces the space. Molecular-orbital indices are not a viable handoff, as
§3.6 shows. The geometry is recorded and checked, so a specification cannot be
silently applied to a different structure.

---

## 3. Results

All benchmark data are committed under `docs/casbench/` and regenerated by
`scripts/casbench/run_bench.py`. The set is thirty molecules with a reference
active space, spanning five classes.

### 3.1 Recommended space against the literature

For a ground-state request, the recommended tier reproduces the literature
space **exactly for 25 of 30 molecules**.

| class | exact | what it tests |
|---|---|---|
| core | 8/13 | planar closed-shell organics |
| non-planar | 3/3 | pyramidal N, second-row S |
| diradical | 5/5 | degenerate $\pi$ systems, a stretched bond |
| conjugated | 4/4 | 10 to 14 $\pi$ orbitals |
| charged | 5/5 | cations and anions |

**The per-class figures must be read with the protocol attached.** All five
remaining misses are core molecules, and this set requests no excited states,
so nothing in it exercises the narrowing of §2.7. Three of the five (uracil,
furan, p-benzoquinone) have references that are excited-state spaces and reach
them once states are requested. The conjugated and charged references are
plain $\pi$ spaces needing no narrowing, which is much of why those rows are
full.

**With excited states requested, the figure is 27 of 30**, measured through the
production runner at its own choice of analysis basis.

The added classes should be held at arm's length in both directions. Several
are close to guaranteed by construction: on a $\pi$-only molecule the projector
emits $\pi$ targets, the pool is the $\pi$ system, and there is no lone pair to
over-count. What the newer entries carry individually is more interesting than
the count:

- **The allyl pair is the only genuine test of charge**, and it is a relation
  rather than a verdict. Cation and anion share a geometry and three $\pi$
  orbitals and differ by two electrons; a scheme that drops the charge returns
  the same electron count for both and scores one right by accident. The
  engine returns $(2e,3o)$ and $(4e,3o)$.
- **Pyridinium** tests a charge that changes the *perception* rather than the
  count: protonation gives the nitrogen a third neighbour and removes its
  in-plane lone pair, taking the space from pyridine's $(8e,7o)$ to $(6e,6o)$.
- **Anthracene** probes the large-planar axis at fourteen $\pi$ orbitals, and
  matches.

### 3.2 Downstream accuracy

Strongly contracted NEVPT2 [18] in the recommended spaces, in cc-pVDZ, against
theoretical best estimates from QUEST [12, 13] and Thiel's benchmark set [14]:

| quantity | value |
|---|---|
| SC-NEVPT2 MAE | **0.30 eV** over 18 states |
| SA-CASSCF MAE | 1.00 eV over the same 18 |
| $n \rightarrow \pi^*$ | MAE 0.23 eV, $n = 7$, mean signed error $-0.05$ eV |
| $\pi \rightarrow \pi^*$ | MAE 0.35 eV, $n = 11$, mean signed error $+0.15$ eV |
| molecules converged | 11 of 12 |

Non-converged rows are excluded from the mean rather than averaged in, and
excluded molecules are named with the number of states dropped, so a shrinking
denominator cannot pass for an improving mean.

### 3.3 Cost and time complexity

Each row below gives the dominant term for that stage, not the cheapest one.

| stage | dominant cost | measured |
|---|---|---|
| SCF reference | $O(N_{\text{bas}}^4)$ formally, density-fitted in practice | ~0.2 s, 10 heavy atoms |
| Perception | $O(N_{\text{atom}}^2)$ neighbour search | milliseconds |
| Projection | $O(N_{\text{bas}}^2 N_{\text{MO}})$ overlap contraction, then $O(n_{\text{occ}}^3 + n_{\text{vir}}^3)$ for the two eigendecompositions | milliseconds |
| APC ranking | $O(N_{\text{occ}} N_{\text{vir}})$ pair loop, riding on the $O(N_{\text{bas}}^4)$ integrals already formed for $K$ | ~0.1 s |
| **Ground-state recommendation** | dominated by the SCF it consumes | **0.23 s median, 6.2 s max (anthracene)** |
| Excited-state branch | one TDA linear response, $O(N_{\text{bas}}^4)$ per Davidson iteration; NTOs add one $O(n_{\text{occ}} n_{\text{vir}} \min(n_{\text{occ}}, n_{\text{vir}}))$ SVD per root | seconds |
| Refinement | $R \cdot N_{\text{CSF}}$ CI cost per macro-iteration, with $N_{\text{CSF}}$ growing as the Weyl-Paldus binomial product of §2.5 | **8.5 s median, 70.9 s mean** |

The asymmetry between the recommendation and the refinement is the design. Every
stage of the recommendation is polynomial in the one-electron dimensions and
none of them touches the CI space, so the recommendation is bounded by the SCF
it consumes and needs no orbital-count cap to stay interactive. The refinement,
by contrast, inherits the factorial-like growth of $N_{\text{CSF}}$ in the
active-space size, which is exactly why it is a separate opt-in tier rather
than part of the default path. It is minutes rather than sub-second precisely
because it solves where the recommendation predicts: of 36 molecules, 34 refine
inside a 600 s cap while anthracene exhausts memory building its CI diagonal
and p-benzoquinone reaches the cap. Of those 34, 33 converge and 7 change the
space.

### 3.4 Span, not size

The headline finding of the validation work. A space can match the published
size exactly and be unable to describe the state it was sized for.

Projecting the hole natural transition orbital of the state a space was
narrowed for onto the selected columns measures reachability directly. Before
the lone-pair amplitude was corrected, uracil's $n \rightarrow \pi^*$ hole
captured **0.376** of itself in its own $(14e,10o)$ -- the literature space, by
count -- while the $\pi \rightarrow \pi^*$ of the same molecule in the same
space gave **0.999**. Every $n \rightarrow \pi^*$ state in the benchmark was
unreachable in the space recommended for it, nine of nine, while every
$\pi \rightarrow \pi^*$ was spanned.

The cause was the hybridisation of the lone-pair target, aiming at a carbonyl's
$s$-rich lone pair where the excitation uses the $p$-like one. Setting
$c_s = 0.20$ moves uracil's capture to **0.759** and formamide's from 0.651 to
0.833, with every $\pi \rightarrow \pi^*$ unchanged at 0.998 or above. Solving
uracil's $A''$ block explicitly puts its lowest $n \rightarrow \pi^*$ singlet at
**15.675 eV** at the old amplitude and **8.272 eV** at the corrected one,
against a lowest $\pi \rightarrow \pi^*$ of 8.10 eV; cc-pVDZ agrees at 15.854
and 8.150.

Planar symmetry is an amplifier rather than a second defect. A Davidson solver
reaches only what its initial guess spans, and in exact planar symmetry the
$a'/a''$ coupling is identically zero, so once the $n \rightarrow \pi^*$
configurations sit above the window no root count recovers them. Where the
space is small enough for the guess to span it the state is found regardless:
formaldehyde's is found at root 1 with a depletion of 0.96 in a
16-determinant $(6e,4o)$.

### 3.5 Reproducibility

At the tolerances now shipped, acrolein reproduces exactly over five repeats:
E0 spread $0.001$ meV, every root $0.000$ eV, 5 of 5 converged. Those
tolerances were chosen *because* of this measurement rather than validated by
it. At the looser settings tried first (`conv_tol` $10^{-6}$, no gradient
tolerance) the same molecule moves 36 meV on E0 and **0.459 eV on root 5**,
with two roots changing character between identical runs -- while PySCF
reports `converged=True` on all five. Convergence at $10^{-6}$ is therefore not
evidence of reproducibility and cannot be used as one.

**The refinement loop is reproducible in its answer but not yet in its
convergence flag.** Three repeats of an identical uracil refinement return the
same $(14e,10o)$ space with an identical rotation trail, identical orbital
labels and identical root characters, with excitation energies agreeing to
0.6 meV. Convergence nonetheless flips on 1 of those 3, and cost varies from
282 to 974 s. That is reported rather than repaired, and it is why §3.7 treats
a non-converged row as unscorable instead of comparing it.

The mechanism is threading: the identical loose protocol pinned to one BLAS
thread reproduces exactly, so the run-to-run difference is reduction order in
the linear algebra and a loose tolerance is what lets it survive into the
answer. Tightness is not monotone -- at `conv_tol` $10^{-10}$ acrolein
converged 0 times in 5 and the full scatter returned, because a criterion the
optimiser cannot reach leaves it stopping arbitrarily. The shipped setting is
chosen for being *reachable*, not for being tight.

### 3.6 Basis independence

**Recommendation.** Pyrrole's $(8e,6o)$, recommended in def2-SVP, handed to
another basis:

| handoff into | by MO index (principal cosine) | by specification |
|---|---|---|
| cc-pVDZ | 0.999 | $(8,6)$ |
| def2-TZVP | 0.989 | $(8,6)$ |
| aug-cc-pVDZ | **0.000** | $(8,6)$ |

An index handoff fails completely into aug-cc-pVDZ, because diffuse functions
reshuffle the virtual manifold and the same indices name an orthogonal set.
Since a diffuse basis is exactly what a user moves to when Rydberg states
matter, this is not an edge case.

**Refinement.** This is a separate and weaker claim, because every reading the
refinement edits on comes from a correlated wavefunction computed *in* a basis.
Measured on three molecules in three bases, the refined space is nonetheless
identical: formaldehyde $(6,4)$, pyrrole $(6,5)$, uracil $(12,9)$ in def2-SVP,
def2-SVPD and cc-pVDZ, with natural occupations agreeing to about 0.005.

### 3.7 Root-count sensitivity

The refined space is unchanged at root margins of 0, 3 and 6 for five of six
molecules tested; the sixth (uracil) differs only in a run that failed to
converge, which is not scored. More roots ran *faster* and converged where
fewer did not: formamide 103.6 s non-converged at margin 0 against 3.2 s
converged at margin 3; acetone 86.0, 21.0, 14.5 s. The margin buys convergence
rather than costing time.

No molecule at any root count recovered a state that fewer roots had missed.

### 3.8 Threshold sensitivity

The projection threshold is flat from 0.05 to 0.40, a factor of eight, and it
determines pool size for everything downstream. The planarity cut is flat from
0.10 to 0.50 and the bond tolerance from 1.15 to 1.50. The lone-pair amplitude
is flat on the literature-match metric from 0.35 to 0.85 -- which is precisely
why that metric could not detect the span failure of §3.4, and why capture had
to be measured directly.

The refinement's own constants are flat for four of six molecules across a grid
of drift tolerance $\{0.10, 0.20, 0.30, 0.50\}$ eV and occupation window
$\{1.95, 1.98, 1.99\}$. Uracil is not flat and is **non-monotone**, returning
$(14e,10o)$ at both 1.95 and 1.99 and $(12e,9o)$ only at the shipped 1.98,
which places the pruned orbital's occupation between 1.98 and 1.99. A constant
whose verdict flips on both sides of its shipped value is not evidence for a
different value; it is evidence that the molecule sits on a knife edge.

Because a six-molecule grid is a poor basis for setting a global constant, the
drift tolerance was re-measured over the whole refinement set. Halving it from
the shipped $0.20$ eV to $0.10$ eV changes the outcome for **exactly one of the
34 molecules that refine**: uracil moves from $(12e,9o)$ to the literature
$(14e,10o)$. Every other space, rotation trail and convergence flag is
identical. This is a sharper result than it first appears. It confirms that
$0.10$ would not damage anything else, but it also shows the constant is
unconstrained by 33 of 34 molecules, so the entire case for changing it rests
on the single molecule already established as non-monotone in this parameter.
The tolerance is therefore left at $0.20$ eV and the sensitivity reported here
rather than tuned away. Fitting a global constant to one knife-edge molecule
would buy one literature match and forfeit the ability to claim the constant
was set on evidence.

---

## 4. Discussion

### 4.1 Comparison with other automatic schemes

**AVAS [1]** projects onto atomic valence orbitals identified by element and
shell -- "the 2p orbitals of carbon and oxygen". The present method projects
onto *oriented directions derived from the geometry*, which is a strictly finer
specification: AVAS cannot distinguish the in-plane lone pair of a carbonyl
oxygen from its out-of-plane $\pi$ contribution, because both are oxygen 2p.
That distinction is exactly what decides whether an $n \rightarrow \pi^*$ state
is describable. The projection machinery here follows AVAS closely, including
its open-shell handling, and the difference is entirely in what is projected
onto.

**Ranked-orbital / APC [2, 3]** supplies the entropy measure used in §2.4, and
the debt is direct. The difference is scope: APC applied over the whole
molecular-orbital space is basis dependent, as quantified in §1. Here APC
orders a pool that a basis-independent projection has already chosen, so the
ranking never sees the growing virtual manifold that causes the drift.

**AutoCAS [5, 6]** obtains orbital entropies from a DMRG pilot. That is a more
faithful entropy than a closed-form estimate, and it costs correspondingly
more. The present method's ranking is about 0.1 s where a DMRG pilot is
minutes, which is what permits an interactive recommendation with no orbital
cap. Where AutoCAS is likely to be better is strongly correlated systems in
which the two-level estimate of §2.4 is a poor model of the true pair structure.

**Occupation-threshold schemes [7, 20]** select on natural-orbital occupations.
The results here argue that occupation alone is not a safe selection criterion,
and §3.8 gives the sharpest form of the argument: an occupation cut applied to
uracil's two lone pairs takes one of them at four roots and neither at six. A
criterion whose verdict moves with a solver setting cannot be the thing that
decides membership. Occupations are used here only to *prune* a space that has
already been selected, and every prune is verified by re-solving.

**AEGISS [4]** is the closest published relative of this work: it also combines
an atomic-orbital-based construction with an entropy criterion, rather than
choosing one or the other. The differences are in what supplies each half. Its
atomic-orbital step is specified by element and shell in the AVAS manner, where
the perception of §2.1 orients each target along a geometric axis, and its
entropy is used as a selection threshold where §2.4 uses it only to order a
pool whose membership a projection has already decided. The comparison is
necessarily loose: AEGISS is a preprint that was not peer reviewed at the time
of writing, and no attempt has been made here to reproduce its benchmark.

**Active Space Finder [11]** reports a best mean absolute error of 0.49 eV for
l-ASF(QRO) over 32 molecules in def2-TZVPD, with 25-30% unsatisfactory results
for every scheme in fully automatic mode. The 0.30 eV over 18 states reported
in §3.2 is not like-for-like -- a different molecule set, a smaller basis and a
different downstream method -- and should be read as a soft comparison rather
than a ranking.

### 4.2 What the span finding implies for the field

Automatic active-space schemes are conventionally scored on whether they
reproduce a published space. §3.4 shows that metric can be satisfied while the
requested state remains unreachable, and that the failure is invisible to every
count-based measure. Uracil matched its literature space on both electrons and
orbitals throughout, and produced no $n \rightarrow \pi^*$ root at three, six
or ten roots, nor in a singlet-constrained CASCI in the seeded space.

We suggest that hole-capture -- projecting the hole natural transition orbital
of the target state onto the selected columns -- is a cheap and direct
reachability measure that any state-specific selection scheme could report, and
that reporting it alongside a size match would catch a class of silent failure
that sizes cannot.

### 4.3 Limitations

**Transition metals are untested.** The benchmark is organic. The perception
step emits no $d$-shell targets, and nothing here should be taken as evidence
about metal complexes.

**Dissociation has a cliff.** The engine returns a correct $(10e,8o)$ for
N$_2$ at every separation out to 1.80 Å and fails at 1.85 Å, where the pair
falls outside the covalent-radius criterion of §2.1, no bond emits a $\sigma$
axis, and a two-atom molecule has no atom with two neighbours to emit a $\pi$
normal. The honest repair is to fall back to atomic valence shells when no bond
survives, rather than to loosen the tolerance for every other molecule.

**One diradical is irreproducible.** Twisted ethylene returns $(2e,2o)$ three
times in four and $(4e,3o)$ once, with the SCF converged every time. It is a
singlet diradical, RHF is a qualitatively wrong reference for one, and the APC
ranking is taken from RHF Fock and exchange matrices, so the near-degeneracy
propagates into the ranking. Every count in §3.1 therefore carries $\pm 1$
molecule.

**The state audit is unreliable on large planar spaces.** For the symmetry
reason given in §3.4: a root list tests reliably on small spaces, where the
Davidson guess spans everything, and can fail quietly on large ones. This is
the wrong way round.

**Narrowing does not exclude Rydberg states.** Where every requested state is
Rydberg, the narrowing has nothing valence to aim at and its result is not
stable between runs.

---

## 5. Conclusion

Selecting an active space by projecting onto oriented, geometry-derived targets
expressed in a fixed minimal basis gives a recommendation that is basis
independent by construction, costs 0.23 s at the median, requires no
orbital-count cap, and reproduces the literature space for 25 of 30 benchmark
molecules for a ground-state request and 27 of 30 when states are specified.
Ordering the resulting pool by a closed-form entropy keeps the cost
interactive; asking the requested states which orbitals they use, through
natural transition orbitals from a linear-response pass, makes the selection
state specific without a CASSCF.

The most transferable result is negative. A recommended space can match its
published size exactly on both electrons and orbitals and still fail to span
the state it was chosen for, and no count-based metric detects this. Measuring
hole capture directly found it, attributed it to a single hybridisation
constant, and the correction recovered every affected state. Schemes that
select active spaces for particular electronic states should measure
reachability rather than infer it from size.

---

## References

[1] E. R. Sayfutyarova, Q. Sun, G. K.-L. Chan and G. Knizia, "Automated
Construction of Molecular Active Spaces from Atomic Valence Orbitals",
*J. Chem. Theory Comput.* **2017**, *13*, 4063-4078.
DOI: 10.1021/acs.jctc.7b00128.

[2] D. S. King and L. Gagliardi, "A Ranked-Orbital Approach to Select Active
Spaces for High-Throughput Multireference Computation",
*J. Chem. Theory Comput.* **2021**, *17*, 2817-2831.
DOI: 10.1021/acs.jctc.1c00037.

[3] D. S. King, M. R. Hermes, D. G. Truhlar and L. Gagliardi, "Large-Scale
Benchmarking of Multireference Vertical-Excitation Calculations via Automated
Active-Space Selection", *J. Chem. Theory Comput.* **2022**, *18*, 6065-6076.
DOI: 10.1021/acs.jctc.2c00630.

[4] "AEGISS: Atomic orbital and Entropy-based Guided Inference for Selecting
active Spaces", arXiv:2508.10671 (2025). *Preprint, not peer reviewed at the
time of writing.*

[5] C. J. Stein and M. Reiher, "Automated Selection of Active Orbital Spaces",
*J. Chem. Theory Comput.* **2016**, *12*, 1760-1771.
DOI: 10.1021/acs.jctc.6b00156.

[6] C. J. Stein and M. Reiher, "autoCAS: A Program for Fully Automated
Multiconfigurational Calculations", *J. Comput. Chem.* **2019**, *40*,
2216-2226. DOI: 10.1002/jcc.25869.

[7] E. Keller, K. Boguslawski, T. Janowski, M. Reiher and P. Pulay, "Selecting
Active Space for Multiconfigurational Quantum Chemistry",
*J. Chem. Phys.* **2015**, *142*, 244104. See also J. J. Bao and
D. G. Truhlar, "Automatic Active Space Selection Based on Natural Orbital
Occupation Numbers", *J. Chem. Theory Comput.* **2019**, *15*, 5308-5318.

[8] B. Cordero, V. Gómez, A. E. Platero-Prats, M. Revés, J. Echeverría,
E. Cremades, F. Barragán and S. Alvarez, "Covalent radii revisited",
*Dalton Trans.* **2008**, 2832-2838. DOI: 10.1039/B801115J.

[9] T. Yanai, D. P. Tew and N. C. Handy, "A new hybrid exchange-correlation
functional using the Coulomb-attenuating method (CAM-B3LYP)",
*Chem. Phys. Lett.* **2004**, *393*, 51-57.

[10] R. L. Martin, "Natural transition orbitals",
*J. Chem. Phys.* **2003**, *118*, 4775-4777. DOI: 10.1063/1.1558471.

[11] "Performance of Automatic Active Space Selection for Electronic Excitation
Energies", arXiv:2511.05732 (2025). Assesses the Active Space Finder (ASF)
family. *Preprint, not peer reviewed at the time of writing.*

[12] P.-F. Loos, A. Scemama, A. Blondel, Y. Garniron, M. Caffarel and
D. Jacquemin, "A Mountaineering Strategy to Excited States: Highly Accurate
Reference Energies and Benchmarks", *J. Chem. Theory Comput.* **2018**, *14*,
4360-4379. DOI: 10.1021/acs.jctc.8b00406.

[13] M. Véril, A. Scemama, M. Caffarel, F. Lipparini, M. Boggio-Pasqua,
D. Jacquemin and P.-F. Loos, "QUESTDB: A database of highly accurate excitation
energies for the electronic structure community",
*WIREs Comput. Mol. Sci.* **2021**, *11*, e1517. DOI: 10.1002/wcms.1517.

[14] M. Schreiber, M. R. Silva-Junior, S. P. A. Sauer and W. Thiel, "Benchmarks
for electronically excited states: CASPT2, CC2, CCSD, and CC3",
*J. Chem. Phys.* **2008**, *128*, 134110. DOI: 10.1063/1.2889385.

[15] B. O. Roos, K. Andersson, M. P. Fülscher, P.-Å. Malmqvist,
L. Serrano-Andrés, K. Pierloot and M. Merchán, "Multiconfigurational
Perturbation Theory: Applications in Electronic Spectroscopy",
*Adv. Chem. Phys.* **1996**, *93*, 219-331.

[16] C. Angeli, "On the nature of the $\pi \rightarrow \pi^*$ ionic excited
states: the V state of ethene as a prototype",
*J. Comput. Chem.* **2009**, *30*, 1319-1333.

[17] Q. Sun, X. Zhang, S. Banerjee *et al.*, "Recent developments in the PySCF
program package", *J. Chem. Phys.* **2020**, *153*, 024109.
DOI: 10.1063/5.0006074.

[18] C. Angeli, R. Cimiraglia, S. Evangelisti, T. Leininger and J.-P. Malrieu,
"Introduction of n-electron valence states for multireference perturbation
theory", *J. Chem. Phys.* **2001**, *114*, 10252-10264. DOI: 10.1063/1.1361246.

[19] K. Ruedenberg, M. W. Schmidt, M. M. Gilbert and S. T. Elbert, "Are atoms
intrinsic to molecular electronic wavefunctions? I. The FORS model",
*Chem. Phys.* **1982**, *71*, 41-49.

[20] P. Pulay and T. P. Hamilton, "UHF natural orbitals for defining and
starting MCSCF calculations", *J. Chem. Phys.* **1988**, *88*, 4926-4933.

[21] J. Olsen, "The CASSCF method: A perspective and commentary",
*Int. J. Quantum Chem.* **2011**, *111*, 3267-3272.

[22] B. O. Roos, P. R. Taylor and P. E. M. Siegbahn, "A complete active space
SCF method (CASSCF) using a density matrix formulated super-CI approach",
*Chem. Phys.* **1980**, *48*, 157-173. DOI: 10.1016/0301-0104(80)80045-0.

[23] J. Paldus, "Group theoretical approach to the configuration interaction and
perturbation theory calculations for atomic and molecular systems",
*J. Chem. Phys.* **1974**, *61*, 5321-5330. The unitary-group formulation from
which the Weyl-Paldus dimension formula of §2.5 follows.

[24] K. K. Docken and J. Hinze, "LiH Potential Curves and Wavefunctions for
X$^1\Sigma^+$, A$^1\Sigma^+$, B$^1\Pi$, $^3\Sigma^+$, and $^3\Pi$",
*J. Chem. Phys.* **1972**, *57*, 4928-4936. The origin of the state-averaged
MCSCF procedure of §2.8.

[25] P.-O. Löwdin, "Quantum Theory of Many-Particle Systems. I. Physical
Interpretations by Means of Density Matrices, Natural Spin-Orbitals, and
Convergence Problems in the Method of Configurational Interaction",
*Phys. Rev.* **1955**, *97*, 1474-1489. DOI: 10.1103/PhysRev.97.1474.

[26] R. S. Mulliken, "Electronic Population Analysis on LCAO-MO Molecular Wave
Functions. I", *J. Chem. Phys.* **1955**, *23*, 1833-1840.
DOI: 10.1063/1.1740588.

[27] S. Hirata and M. Head-Gordon, "Time-dependent density functional theory
within the Tamm-Dancoff approximation", *Chem. Phys. Lett.* **1999**, *314*,
291-299. DOI: 10.1016/S0009-2614(99)01149-5.

[28] G. Knizia, "Intrinsic Atomic Orbitals: An Unbiased Bridge between Quantum
Theory and Chemical Concepts", *J. Chem. Theory Comput.* **2013**, *9*,
4834-4843. DOI: 10.1021/ct400687b.

[29] M. R. Hermes, "csf_fci: a spin-adapted configuration-state-function CI
solver", distributed with the `mrh` package (github.com/MatthewRHermes/mrh) and
usable from PySCF [17].
