# Geometry-Oriented Projection with Entropy Ranking for Automated Active-Space Selection

**Method of record for NexusQC's CAS recommendation engine.**

---

## Abstract

Choosing a complete active space (CAS) is the step at which a multireference
calculation is usually won or lost, and it is normally done by hand. We describe
a fully automatic selection scheme built on four ideas: the mean field it reads
is stabilised rather than merely converged; candidate orbitals are identified by
projecting that mean field onto *oriented target directions* derived from the
molecular geometry and expressed in a fixed minimal reference basis; the
resulting pool is ordered by approximate pair-coefficient (APC) entropy; and,
when particular electronic states are requested, the space is narrowed to the
orbitals those states are actually built from, using natural transition orbitals
from a linear-response pass. An optional refinement tier corrects the space
against state-averaged CASSCF evidence.

Because the targets live in a basis that does not change with the calculation,
the recommendation is basis independent by construction, and is measured to be
so: no molecule in a thirty-molecule benchmark returns a different space in any
of five basis sets. It is orientation independent on the same measurement, no
molecule returning a different space under any of five random rotations of its
geometry. The recommended space reproduces the literature space
exactly for 25 of 30 molecules for a ground-state request and 27 of 30 when
excited states are specified, and every molecule returns the same space on every
run. A ground-state recommendation costs 0.27 s at the median. Downstream,
strongly contracted NEVPT2 in the recommended spaces gives a mean absolute error
of 0.32 eV against theoretical best estimates over 18 states.

The scheme also reports two things automatic selectors usually do not: whether
the requested state is *reachable* in the space chosen for it, measured directly
rather than inferred from orbital counts, and whether the answer is the only one
its own reference supports.

---

## 1. Introduction

A CASSCF calculation requires the user to choose, in advance, which orbitals and
electrons are treated exactly. The choice is not a convenience: an active space
that omits an orbital a state is built from does not describe that state at all,
and the calculation returns a converged, plausible, wrong answer with no
diagnostic to say so. Conversely a space that is too large is not merely
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

Four problems recur across these approaches and motivate the present work.

**Basis dependence.** A scheme that selects orbitals by index, or that ranks
over the full molecular-orbital space, gives different answers in different
basis sets, because the virtual manifold it ranks over grows with the basis.
Measured here, ranking raw APC over all molecular orbitals returns CAS(18e,12o)
for pyrrole in def2-SVP and CAS(22e,13o) in def2-TZVP.

**State blindness.** A ground-state criterion identifies orbitals carrying
static correlation. That is not the same question as which orbitals a
*particular* excited state is made of. A dark $n \rightarrow \pi^*$ state
requires the heteroatom lone pair in the space; no measure of ground-state
correlation will reliably put it there.

**Size is not span.** A recommended space can match the published size exactly
and still be unable to describe the state it was sized for. Sizes are what
automatic schemes are usually scored on, and they do not measure reachability.

**The reference is assumed rather than checked.** Every scheme above reads a
converged mean field, and convergence does not mean the mean field is a minimum.
Where it is not, the ambiguity propagates. Section 3.4 records one benchmark
molecule whose recommendation alternated between two spaces across identical
runs for this reason, and three more built on a stationary point that was not a
minimum, which no repeat measurement could have revealed.

We address these by stabilising the reference before reading it, projecting onto
geometric targets in a fixed minimal basis, asking the requested states which
orbitals they use before selecting, and measuring span directly rather than
inferring it from counts.

---

## 2. Methods

The pipeline is: converge and stabilise a mean field $\rightarrow$ perceive
targets from the geometry $\rightarrow$ project the mean field onto them
$\rightarrow$ rank the pool by entropy $\rightarrow$ emit size tiers
$\rightarrow$ (if states are requested) analyse them and narrow $\rightarrow$
(optionally) refine against CASSCF.

### 2.1 The reference: converged is not enough

Every later stage reads a converged self-consistent field. The projector takes
its orbitals, the ranking takes its Fock and exchange matrices, and the
refinement rebuilds a recorded specification against it. An SCF with more than
one solution therefore hands the whole method more than one answer.

Convergence does not exclude that. It means the iterations stopped moving, and
an unstable solution is a stationary point that is not a minimum, so it
satisfies the test exactly. The reference is therefore checked for stability and
re-converged from the improved orbitals until it is stable, at most five times.

The consequence is not subtle. Plain restricted Hartree-Fock on twisted ethylene
converges to $-77.801586$ Ha on 17 runs in 20 and to $-77.770110$ Ha on the
other three, 31.5 mHa apart, reporting success every time. One of the
projector's occupied eigenvalues for that molecule sits within about $0.02$ of
the admission threshold of §2.4, measured at $0.177762$ under one solution and
$0.212131$ under the other, so which solution was found decides which side of
the cut it falls on, and admitting one occupied orbital is exactly the
difference between $(2e,2o)$ and $(4e,3o)$.

**Internal instabilities are followed; external ones are reported.** An external
instability means the closed-shell reference is unstable toward an open-shell
one, which is the correct description of a singlet diradical and is true of
every diradical in the benchmark. Acting on it means a broken-symmetry
reference, and the projection of §2.4 takes the $\alpha$ set alone when handed
one, so following it would change what the projection means without saying so.
It is surfaced to the user instead.

### 2.2 Perception: targets from geometry alone

Bonds are perceived from covalent radii [8]: atoms $i$ and $j$ are bonded when
$|\mathbf{r}_i - \mathbf{r}_j| < \tau (R_i + R_j)$ with $\tau = 1.30$. Four
kinds of target are then emitted.

**$\pi$ normals.** At an atom with exactly two neighbours, the normal to the
plane they define, $\hat{\mathbf{n}} \propto \mathbf{v}_1 \times \mathbf{v}_2$.
At an atom with three or more, the best-fit plane normal, obtained as the
right-singular vector of least variance of the centred neighbour displacements.
A fitted normal is accepted only if the centre is genuinely planar,

$$
\max_i \left| \hat{\mathbf{v}}_i \cdot \hat{\mathbf{n}} \right| < 0.25 ,
$$

which evaluates to $0$ for a planar centre, $\approx 0.37$ for pyramidal
ammonia and $\approx 0.577$ for a tetrahedral one. Without this test the
singular value decomposition returns a confident direction of least variance for
an $sp^3$ carbon and every saturated centre acquires a spurious $\pi$ orbital.

**Lone pairs.** From the coordination geometry: for two neighbours, the
direction opposing their bisector and the normal to their plane; for three, the
direction opposing their sum, *provided the centre is pyramidal*. The pyramidal
condition uses the same planarity test, and is not a refinement: at a planar
three-coordinate centre the three bond unit vectors are coplanar and nearly
cancel, so $-\widehat{\sum_i \hat{\mathbf{v}}_i}$ is a small residual whose
direction is fixed by the deviation from trigonal symmetry rather than by
chemistry. The non-bonding density at such a centre is the $p$ orbital
perpendicular to the plane, which is already emitted as the $\pi$ target; an
in-plane lone pair would be a second claim on the same electrons.

For a *terminal* heteroatom all three non-bonding directions are emitted -- the
two perpendicular to the bond and the one along it -- because which is the true
lone pair depends on bond order, which geometry does not supply. A carbonyl
oxygen's lone pairs are perpendicular to C=O; a nitrile or dinitrogen nitrogen's
lies along the axis. The projection discards whichever holds no density, which
is cheaper and more robust than perceiving bond orders. The two perpendicular
directions are covariant only in their span, which §4.4 records as the source of
a real limitation.

**$\sigma$ axes.** For every bond, the bond direction, emitted on both atoms.

**Metal $d$ shells.** A transition metal contributes its whole valence $d$
shell, unoriented, and nothing else. The engine is not validated for metals and
says so when it meets one; §3.7 gives the measurement.

### 2.3 Targets are oriented hybrids

A reference built from $p$ functions alone has the wrong shape for either a lone
pair or a $\sigma$ bond. Each oriented target is an $sp$ hybrid

$$
| t \rangle = c_s\, |\,n s\, \rangle + \sqrt{1 - c_s^{2}}\;
              \big( \hat{\mathbf{d}} \cdot | \,n\mathbf{p}\, \rangle \big),
$$

with $\hat{\mathbf{d}}$ the perceived direction. The hybrid must be *oriented*:
a bare valence $s$ has no direction and cannot distinguish one lone pair from
another on the same atom.

For $\sigma$ targets $c_s = 1/\sqrt{3}$, the $sp^2$ value. For lone pairs
$c_s = 0.20$. The lone-pair value is the single most consequential constant in
the method and §3.5 is the parameter study that fixes it: a carbonyl's $n$
orbital is predominantly an oxygen $2p$ in the molecular plane, perpendicular to
the C=O axis, and it is that $p$-like lone pair which performs
$n \rightarrow \pi^*$, not the $s$-rich hybrid pointing away along the bond.

### 2.4 Projection

All targets are expressed in a fixed minimal reference basis (`minao`), which is
what makes the selection basis independent: a target expressed in a basis that
does not change means the same thing in STO-3G and in aug-cc-pVQZ. The idea of a
minimal-basis reference as a bridge to chemical concepts is Knizia's [28].

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
the result depends only on the *span* of the targets and never on the particular
redundant, non-orthogonal vectors chosen to describe it. This is what makes the
degenerate $\pi$ pair of a linear centre safe to emit.

$\mathbf{A}$ is diagonalised separately in the occupied and virtual blocks, and
orbitals with eigenvalue $w \ge 0.2$ enter the active pool. Occupied orbitals
that do not make the cut remain doubly occupied and join the core, so the active
electron count is

$$
N_{\text{act}} = N - 2 n_{\text{frozen}} - 2 n_{\text{occ,dropped}} ,
$$

where the two subtracted terms are distinct rather than a double count:
$n_{\text{frozen}}$ is the frozen core the caller supplied, which the projection
never sees, and $n_{\text{occ,dropped}}$ is the number of occupied orbitals the
projection itself sent back to the core by leaving them below threshold.

Open shells are handled rather than refused: a singly occupied orbital is
treated on the $\alpha$ side, following AVAS's `openshell_option=2` [1].

### 2.5 Ranking by approximate pair-coefficient entropy

The pool is ordered by APC entropy [2, 3]. For occupied $i$ and virtual $a$, the
coefficient of the doubly excited configuration
$|\Phi_{i\bar{i}}^{a\bar{a}}\rangle$ is estimated in closed form from quantities
a converged SCF already holds,

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
are worth stating because they are easy to misread. $F$ and $K$ are the Fock and
exchange matrices transformed into the orbital basis being ranked, so $K_{aa}$
is a diagonal element of the exchange matrix at virtual $a$, a sum over occupied
orbitals, and not the pair integral $K_{ia}$; and $\Delta_{ia}$ is the
one-electron gap, with the doubling carried by the matrix above rather than
folded into $\Delta$. Normalising the coefficients belonging to one orbital and
reading the result as a two-state population gives a von Neumann entropy

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

**Ranking is performed inside the pool, never over the whole MO space.** This is
what keeps the method basis independent; ranking over all molecular orbitals
reproduces the basis dependence quoted in §1.

### 2.6 Size tiers

Three tiers are emitted. The **recommended** tier is the projected pool. The
**minimal** tier is the entropy-ranked head of that pool, cut at the largest
relative gap in the sorted entropy profile, provided that gap exceeds $0.15$; if
the profile is flat there is no defensible cut and the minimal tier is the whole
pool. The **maximal** tier is the pool projected from the extended target set,
which adds the $\sigma$ framework. When the recommended tier was already built
from that extended set -- an alkane with no $\pi$ system and no lone pairs, or a
molecule whose valence pool is full and therefore not a space at all -- the
maximal tier is identical to the recommended one rather than a larger
alternative.

Every tier must be a space in its own right: it must hold electrons, must not be
completely full, and must keep at least one orbital on each side of the Fermi
level. Without that guard the gap search returns things like N$_2$ $(4e,5o)$ or
an O$_2$ triplet $(2e,3o)$, which are arithmetically fine and chemically
useless, and the state-narrowed tier of §2.8 returns water's $(4e,2o)$, two
doubly occupied orbitals holding exactly one configuration.

Cost is reported and never enforced. The number of configuration state functions
for $n$ orbitals, $N$ electrons and total spin $S$ follows the Weyl-Paldus
dimension formula [23],

$$
N_{\text{CSF}} = \frac{2S + 1}{n + 1}
                 \binom{n + 1}{\tfrac{N}{2} - S}
                 \binom{n + 1}{\tfrac{N}{2} + S + 1},
$$

and is reported per tier alongside the number of roots a state average would
solve, since a state average over $R$ roots solves $R$ CI problems per
macro-iteration and cost tracks the product $R \cdot N_{\text{CSF}}$.

### 2.7 The excited-state branch

When $n_{\text{states}} > 1$ the analysis basis moves to one carrying diffuse
functions, and a linear-response pass runs: TDA [27] on a range-separated hybrid
(CAM-B3LYP [9]), for at least twice the requested number of roots. A
range-separated functional matters because TDA on a Hartree-Fock reference is
CIS, which overestimates valence excitations by of order an electronvolt and
misorders them, and state *ordering* is what this branch depends on.

Each root's transition density matrix $\mathbf{T}$ is decomposed into natural
transition orbitals [10] by singular value decomposition,

$$
\mathbf{T} = \mathbf{U}\, \boldsymbol{\sigma}\, \mathbf{V}^{\dagger},
$$

whose leading pair names the hole and the particle. Characters
($\pi \rightarrow \pi^*$, $n \rightarrow \pi^*$, Rydberg) follow from projecting
hole and particle onto the perceived targets.

**Diffuseness is measured, not inferred from the basis set's name, and it is
measured absolutely.** The fraction of an orbital's density lying further than
1.5 van der Waals radii from every atom separates a diffuse orbital from a
valence one on an absolute scale: occupied orbitals come in below 0.010, cc-pVDZ
virtuals below 0.29, and aug-cc-pVDZ virtuals reach 0.98. An exponent-based rule
fails in both directions, and so does a *relative* measure comparing an
orbital's extent against the largest extent among the orbitals already in the
space -- that denominator contains the orbital being tested whenever the diffuse
orbital is inside the active space, so the ratio collapses toward one and no
root in such a space can ever be called Rydberg.

The analysis basis is aug-cc-pVDZ, chosen on the measurement in §3.6. Where an
element has no aug-cc-pVDZ definition the analysis falls back to def2-SVPD and
says so, because that basis resolves diffuse orbitals less reliably.

### 2.8 State narrowing

Given the requested states, the space is narrowed to the $\pi$ system plus the
lone pairs those states are built on. Heteroatom centres are identified from the
hole natural transition orbital by Mulliken population [26]: a centre qualifies
when it carries at least $10\%$ of the hole. Two lone pairs are kept per
$n \rightarrow \pi^*$ state, taken round-robin over centres by rank so the first
pass takes one from each.

An orbital is classified as $\pi$ or lone-pair only if it carries at least
$0.30$ of one of those characters, and that test comes *before* the two weights
are compared with each other. The other order asks which of two numerical zeros
is larger: water's second pool orbital carries $\pi$ weight of order $10^{-26}$
against lone-pair weight of order $10^{-28}$, and the comparison decides its
membership.

The narrowed tier is subject to the same completion guard as every other tier
(§2.6), and is not published when it fails it.

Two alternative rules were measured and rejected. *Coverage of the hole* fails
because an $n \rightarrow \pi^*$ hole expressed in the projector's eigenbasis
smears across most of the lone-pair block; uracil's needs four of its six
orbitals to reach 90% even though the chemistry is two carbonyl lone pairs.
*Growing while the budget allows* fails instructively: adding an occupied
orbital to a nearly-full space *reduces* the CSF count -- CAS(24e,15o) is 63,700
CSFs where CAS(22e,15o) is 496,860 -- so a greedy fill exploits the
combinatorics rather than choosing chemistry.

### 2.9 The refinement tier

An optional second job corrects the space against state-averaged CASSCF [22, 24]
evidence, in cycles of at most four:

1. Solve SA-CASSCF over $n_{\text{states}} + 3$ roots. The margin exists because
   a linear-response pass and a CASSCF need not order states identically.
2. **Character audit.** Confirm the selected $\pi$ and lone-pair character
   survived orbital optimisation; a space correct at the starting guess need not
   remain so under optimisation [21].
3. **State audit.** Confirm each requested state is present. A missing state
   triggers a narrowing, then a re-seed, then augmentation from the natural
   transition orbitals. A predicted Rydberg state is reported as deliberately
   not looked for rather than chased, for the reason §4.3 measures.
4. **Prune.** Drop orbitals whose state-averaged natural occupation [25] lies
   outside $[0.02, 1.98]$, then re-solve and confirm nothing was lost and no
   requested excitation moved by more than $0.20$ eV. The prune is undone if
   either check fails.

The loop begins from the largest tier whose cost $R \cdot N_{\text{CSF}}$ fits a
budget of $10^{6}$, or from the narrowed tier the recommendation published. When
no tier fits and there are requested states to narrow against, it narrows; when
no tier fits and there are none, it declines and says what the space costs,
because narrowing without states to aim at is not a smaller version of the same
answer but a different rule with no input.

The state average is spin-adapted through a CSF-based solver [29]; failure to
spin-adapt is reported rather than swallowed, because a triplet's transition
density from a singlet reference vanishes by spin and every character built from
a contaminated average is noise.

Solver tolerances are `conv_tol` $10^{-8}$, `conv_tol_grad` $10^{-5}$, and 100
macro-iterations, chosen for being reachable rather than tight: at $10^{-10}$
acrolein converged 0 times in 5, because a criterion the optimiser cannot reach
leaves it stopping arbitrarily.

Because a state average can converge to more than one solution (§3.4), the
result reports the state-averaged ground-state energy its excitation energies
are differences against, and says that a converged flag is not an
identification.

### 2.10 Hole capture: measuring span rather than size

The results of §3.5 rest on a measurement that is not part of the selection
pipeline but is the instrument used to validate it, so it is defined here.

Let $|h\rangle$ be the hole natural transition orbital of a requested state,
obtained from the decomposition of §2.7, and let $\mathbf{Q}$ be an orthonormal
basis for the selected active columns. The **capture** of that state's hole by
the space is

$$
\kappa = \frac{\langle h | \mathbf{Q}\mathbf{Q}^{\dagger} | h \rangle}
              {\langle h | h \rangle} \in [0, 1],
$$

the fraction of the hole lying inside the active space. $\kappa \approx 1$ means
the configurations that build the state are available to the CI; $\kappa$
substantially below 1 means they are not, no matter how many roots are solved
for, because the amplitude simply is not in the space.

This is a direct measure of *reachability*, where electron and orbital counts
measure only *size*. The two are independent, which is the point.

### 2.11 Portable handoff

The recommendation is written to disk as the *question* rather than the answer:
the oriented targets in the minimal reference basis, the thresholds, the tier
sizes, and the geometry. Given any later mean field, re-asking that question
reproduces the space. Molecular-orbital indices are not a viable handoff, as
§3.6 shows. The geometry is recorded and checked, so a specification cannot be
silently applied to a different structure.

---

## 3. Results

All benchmark data are committed under `docs/casbench/` and regenerated by
`scripts/casbench/run_bench.py`. Each ledger records the commit that produced
it, the wall time, and the thread counts in force, because some of the
quantities below depend on the last of those.

The set is 36 molecules, 30 of them with a reference active space, spanning five
classes: planar closed-shell organics, non-planar heteroatom systems,
diradicals, conjugated chains and rings up to fourteen $\pi$ orbitals, and
charged species. Transition metals were measured and are out of scope; §3.7 says
why.

Six benchmark sets produce every number below. They ask different questions, and
a figure quoted without saying which set produced it cannot be checked, so each
result names its set and each set names its ledger.

| set | the question it answers | over | ledger | cost |
|---|---|---|---|---|
| `spaces` | with no states requested, is the recommended space the literature one? | 30 molecules with a reference space | `spaces.md` | 205 s |
| `narrowed` | and when the states a user cares about are requested? | the same 30, each at its own state-averaging protocol | `narrowed.md` | 1997 s |
| `stability` | does the space change with the basis set, or with the molecule's orientation? | the same 30, in 5 bases and under 5 random rotations each | `stability.md` | 3616 s |
| `excited` | does the linear-response pass that chooses the space find the right states? | 12 molecules carrying reference excitation energies, 24 states | `excited.md` | 1699 s |
| `nevpt2` | how accurate is a real calculation in the space the engine chose? | the same 12, SA-CASSCF then SC-NEVPT2 in cc-pVDZ | `nevpt2.md` | 6103 s |
| `refine` | what does the optional refinement tier change, and at what cost? | all 36 geometries, one-hour cap each | `refine.md` | 6181 s |

Each ledger is a table of per-molecule rows, so any aggregate here can be taken
apart. Costs are wall time on one shared 255-core host at `omp=8, mkl=12`, and
are the cost of the whole set rather than of one molecule.

Two of the six, `excited` and `nevpt2`, were produced one commit earlier than
the other four. Nothing between the two commits touches what they measure:
transition metals were removed from the benchmark and they contain none, and
neither set reaches the code that changed. The stamps in the ledgers make that
checkable rather than something to take on trust.

### 3.1 Recommended space against the literature

For a ground-state request, the recommended tier reproduces the literature space
**exactly for 25 of 30 molecules**.

| class | exact | what it tests |
|---|---|---|
| core | 8/13 | planar closed-shell organics |
| non-planar | 3/3 | pyramidal N, second-row S |
| diradical | 5/5 | degenerate $\pi$ systems, a stretched bond |
| conjugated | 4/4 | 10 to 14 $\pi$ orbitals |
| charged | 5/5 | cations and anions |

**A count is only useful if the misses are named**, and all five are core
molecules. This set requests no excited states, so nothing in it exercises the
narrowing of §2.8, and that is what most of the difference is:

| molecule | reference | recommended | why they differ |
|---|---|---|---|
| furan | $(6e,5o)$ | $(8e,6o)$ | reference is an excited-state space; recovered exactly once states are requested (§3.2) |
| uracil | $(14e,10o)$ | $(18e,12o)$ | the same, and the largest narrowing in the benchmark |
| acrolein | $(8e,7o)$ | $(8e,6o)$ | the reference disagrees with itself: its description names four $\pi$ orbitals plus the oxygen lone pair, which is five, against a recorded count of seven. The engine matches the electron count exactly and is one virtual short, which acrolein's four-orbital $\pi$ system has no third $\pi^*$ to supply |
| formamide | $(8e,7o)$ | $(8e,5o)$ | the same disagreement, recorded in the benchmark's own reference entry: the description names five orbitals and the count is seven |
| p-benzoquinone | $(12e,10o)$ | $(16e,12o)$ | the projected pool is genuinely larger, and unlike furan and uracil the requested states do not narrow it |

So of the five, two are recovered by requesting states, two are comparisons that
cannot be made cleanly because the published space does not agree with its own
description, and one is a real difference. That is a more useful statement than
25 of 30, and it is why the per-molecule ledgers are committed.

The conjugated and charged references are plain $\pi$ spaces needing no
narrowing, which is much of why those rows are full.

Several classes are close to guaranteed by construction: on a $\pi$-only
molecule the projector emits $\pi$ targets, the pool is the $\pi$ system, and
there is no lone pair to over-count. What the entries carry individually is more
interesting than the count:

- **The allyl pair is the only genuine test of charge**, and it is a relation
  rather than a verdict. Cation and anion share a geometry and three $\pi$
  orbitals and differ by two electrons; a scheme that drops the charge returns
  the same electron count for both and scores one right by accident. The engine
  returns $(2e,3o)$ and $(4e,3o)$.
- **Pyridinium** tests a charge that changes the *perception* rather than the
  count: protonation gives the nitrogen a third neighbour and removes its
  in-plane lone pair, taking the space from pyridine's $(8e,7o)$ to $(6e,6o)$.
- **Anthracene** probes the large-planar axis at fourteen $\pi$ orbitals, and
  matches.

### 3.2 With the requested states taken into account

Measured through the production runner at its own choice of analysis basis, at
each molecule's own state-averaging protocol: **27 of 30 exact**. Two molecules
are narrowed by the requested states, and both of those are misses in §3.1 that
the narrowing recovers: furan's pool $(8e,6o)$ becomes its literature $(6e,5o)$,
and uracil's $(18e,12o)$ becomes its literature $(14e,10o)$.

The three that still differ are exactly the three §3.1 did not attribute to
narrowing: acrolein and formamide, whose published spaces disagree with their own
descriptions, and p-benzoquinone, where the pool is larger and the requested
states do not reduce it. No molecule is made worse by requesting states.

This is the figure that describes what a user asking about particular states
receives, and it is the protocol under which the reference spaces for those
molecules were determined.

### 3.3 Downstream accuracy

Strongly contracted NEVPT2 [18] in the recommended spaces, in cc-pVDZ, against
theoretical best estimates from QUEST [12, 13] and Thiel's benchmark set [14].
The states are requested, so the spaces measured are the ones a user asking
about those states receives:

| quantity | value |
|---|---|
| SC-NEVPT2 MAE | **0.32 eV** over 18 states |
| SA-CASSCF MAE | 1.08 eV over the same 18 |
| $n \rightarrow \pi^*$ | MAE 0.27 eV, $n = 6$, mean signed error $+0.06$ eV |
| $\pi \rightarrow \pi^*$ | MAE 0.35 eV, $n = 12$, mean signed error $+0.16$ eV |
| molecules scored | 11 of 12 |

Non-converged rows are excluded from the mean rather than averaged in, and
excluded molecules are named with the number of states dropped, so a shrinking
denominator cannot pass for an improving mean. One molecule is excluded here:
p-benzoquinone, two states.

The split between the two characters is the informative part. A valence space
does $n \rightarrow \pi^*$ well and *ionic* $\pi \rightarrow \pi^*$ badly, which
is a limitation of the space's size and the basis rather than of how the space
was chosen: formaldehyde's $\pi \rightarrow \pi^*$ is $+3.79$ eV at SA-CASSCF
and $+0.38$ eV after NEVPT2.

The linear-response pass that chooses the space is separately accurate, and it
is worth reporting on its own because a space chosen from misordered states is
wrong for a reason no downstream number would explain. Over the 12 molecules
carrying reference excitation energies, 24 states in total from QUEST [12, 13]
and Thiel [14], TDA on CAM-B3LYP in aug-cc-pVDZ gives a mean absolute error of
0.27 eV with a worst case of 1.06 eV, and **locates all 24**. Located means a
root was found whose character matches the reference's, matched by character
rather than by index, so a state that moved position still counts as found and a
state of the wrong character does not.

### 3.4 Reproducibility

**Every molecule returns the same space on every run.** Thirty of thirty, four
identical runs each, compared on the selected orbital indices rather than on the
size, because two runs can select the same number of orbitals without selecting
the same ones.

That is a property of the stabilised reference rather than a standing one.
Twisted ethylene used to return $(2e,2o)$ on 51 runs in 60 and $(4e,3o)$ on the
other nine, for the reason §2.1 gives. Three further molecules had references
that were unstable without being ambiguous, converging to the same non-minimum
every time: square cyclobutadiene by 11.4 mHa, stretched N$_2$ by 19.1 mHa and
O$_2$ by 0.25 mHa. None of them changes its recommended space when stabilised,
which is what identifies this as a repair rather than a perturbation, and their
failure mode is the one a repeat measurement cannot see.

**A state-averaged CASSCF is a different matter, and two molecules in seven have
more than one converged solution.** The census solves each molecule's recommended
space eight times over, identically, in cc-pVDZ, at the root count the refinement
uses, and counts how many distinct converged ground-state energies come back. Two
runs count as the same solution when they agree to better than 1 meV, which sits
far above the within-solution scatter of 0.0007 meV and far below the smaller of
the two gaps found. The denominator is seven rather than the twelve molecules
carrying reference energies because the run was stopped once it had answered the
question it was started for, which was whether acrolein is alone:

| molecule | solutions | spread | converged | characters differ |
|---|---|---|---|---|
| acrolein | 2 | 36.4 meV | 8/8 | yes |
| butadiene | 2 | 872.8 meV | 8/8 | yes |
| acetone, benzene, ethylene, formaldehyde, formamide | 1 | $\le 0.001$ meV | 8/8 | no |

Both converge on every run and both disagree about root characters between their
solutions, so the difference is not confined to a total energy nobody quotes. No
tolerance addresses it: within a solution the reproducibility is exact, to
0.0007 meV over sixteen runs of acrolein. Pinning to a single BLAS thread makes
the choice deterministic, which is what identifies reduction order as the
mechanism and also why it cannot be repaired from the solver side.

The root count is part of the protocol rather than a detail. The same census run
at a flat four roots reports every molecule single-solution, acrolein included;
its two solutions appear at six, which is its two reference states plus the
refinement's root margin, and six is what a user actually runs. A reproducibility
measurement taken at a root count nobody uses can report a stability the shipped
protocol does not have.

A user of the refinement tier meets this directly, which is why §2.9 reports the
state-averaged ground-state energy alongside every set of excitation energies:
two runs have to be compared on that number before their states are compared.

### 3.5 Span, not size

The most transferable result here, and the reason $c_s = 0.20$ in §2.3.

Projecting the hole natural transition orbital of the state a space was narrowed
for onto the selected columns measures reachability directly, and swept against
the lone-pair amplitude it is monotone and steep where the literature-match
metric is flat. At the $sp^2$ value $c_s = 1/\sqrt{3}$, uracil's
$n \rightarrow \pi^*$ hole captures **0.363** of itself in its own $(14e,10o)$ --
the literature space, by count -- while the $\pi \rightarrow \pi^*$ of the same
molecule in the same space gives **0.999**. Every $n \rightarrow \pi^*$ state in
the benchmark is unreachable at that amplitude, nine of nine, spanning 0.363 to
0.651, while every $\pi \rightarrow \pi^*$ is spanned.

| state | $c_s = 0.577$ | $c_s = 0.20$ |
|---|---|---|
| uracil $n \rightarrow \pi^*$, 5.03 eV | 0.363 | **0.759** |
| uracil $n \rightarrow \pi^*$, 6.19 eV | 0.381 | **0.819** |
| formamide $n \rightarrow \pi^*$, 5.45 eV | 0.651 | **0.806** |
| nine $n \rightarrow \pi^*$, range | 0.363 -- 0.651 | **0.570 -- 0.819** |

The cause is chemical rather than numerical. A carbonyl oxygen carries two lone
pairs: an $s$-rich hybrid pointing away along the C=O axis, and a much more
$p$-like one perpendicular to it in the molecular plane. The
$n \rightarrow \pi^*$ excitation comes out of the $p$-like one, and an $sp^2$
target selects the other. Solving uracil's $A''$ block explicitly puts its
lowest $n \rightarrow \pi^*$ singlet at **15.675 eV** at the $sp^2$ amplitude
and **8.272 eV** at the corrected one, against a lowest $\pi \rightarrow \pi^*$
of 8.10 eV; cc-pVDZ agrees at 15.854 and 8.150. Configurations built on a 38%
hole land near 16 eV rather than near 5.

The amplitude is not zero, because a bare valence $s$ has no direction and
pulls the deep $\sigma$ framework into the pool. It is flat on the
literature-match metric from 0.35 to 0.85, which is precisely why that metric
could not detect this and why capture had to be measured directly.

Planar symmetry is an amplifier rather than a second defect. A Davidson solver
reaches only what its initial guess spans, and in exact planar symmetry the
$a'/a''$ coupling is identically zero, so once the $n \rightarrow \pi^*$
configurations sit above the window no root count recovers them. Where the space
is small enough for the guess to span it the state is found regardless:
formaldehyde's is found at root 1 in a 16-determinant $(6e,4o)$.

### 3.6 Basis and orientation independence, and what a diffuse basis is for

**What is measured here, and how.** Both claims below come from
`run_bench.py --set stability`, whose per-molecule rows are in
`docs/casbench/stability.md`. It runs over the 30 molecules that carry a
literature reference space, which is the same set as §3.1 and six fewer than the
36 geometries in the benchmark, because a molecule with no reference is still
useful for measuring cost and convergence but not for this. For each molecule it
asks for a ground-state recommendation once per condition and collects the
resulting spaces into a set. Two runs count as agreeing when the recommended
space has the same electron count and the same orbital count, written
$(ne,no)$; the orbital *indices* are deliberately not compared, because a
different basis numbers its orbitals differently and the claim being made is
about the space, not about bookkeeping. A molecule is reported as changing when
that set has more than one member. The rotation half can be re-run on its own,
which is much faster than the full set, with
`scripts/casbench/rotation_invariance.py`.

**No molecule changes its space with the basis.** Each molecule is recommended
five times, once in each of STO-3G, cc-pVDZ, def2-SVP, def2-TZVP and
aug-cc-pVDZ, at the same geometry. 0 of 30 return more than one space. The
legacy AVAS pilot, run alongside on the same geometries, returns more than one
space for 3 of 30. This is the property the method is built to have, and it is
the one place the engine's design is fully vindicated by measurement.

**No molecule changes its space with its orientation either.** Each molecule's
coordinates are multiplied by five random rotation matrices, drawn from
`numpy.random.default_rng(20260902)` so the same five orientations are used for
every molecule and every re-run, and recommended in def2-SVP at each. 0 of 30
return more than one space. Stronger than that, and the check that matters when
a repair is being validated rather than a property claimed: each of the 30
returns the same space its *unrotated* geometry returns, so the answer is not
merely self-consistent across orientations but is the answer already recorded in
`spaces.md`.

That did not hold when the set was first measured. Six molecules returned two
distinct spaces across the five orientations: acetone, acrolein, formaldehyde,
formamide, p-benzoquinone and uracil. All six carry a carbonyl, and the
mechanism is worth recording because it is a trap for any scheme that builds
targets from geometry. `docs/casbench/rotation-invariance.md` carries the
per-molecule before and after, the perceived directions themselves, and the
enumeration behind the last paragraph of this section.

A terminal heteroatom's two non-bonding directions perpendicular to its bond
come from a pair spanning the perpendicular plane, and that pair was seeded from
a fixed vector in the laboratory frame. It was therefore an arbitrary basis of
the plane, and a different one for every orientation. The construction is
covariant only in its *span*, which is enough for a pure $p$ target because a
projection onto a subspace does not care which basis of it was handed over. Two
things then went wrong at once.

The first is what the span argument itself predicts. An $sp$ hybrid is not a
pure $p$ function, and adding the same $s$ component to two arbitrary in-plane
directions gives a pair whose span *does* depend on which two were chosen. So
the lone-pair amplitude that §3.5 shows is necessary is also what removes the
guarantee.

The second is sharper, and it is what actually moved the spaces. An $sp^2$
heteroatom's out-of-plane lone pair **is** its $\pi$ orbital, so §2.3 discards a
lone-pair direction parallel to the atom's $\pi$ normal rather than putting the
same direction in the pool twice. An arbitrary basis is parallel to nothing, so
that test fired only when the random orientation happened to align one member
with the normal. On the orientations where it missed, the $\pi$ direction
entered the pool a second time as a lone pair and the space gained an orbital
and two electrons. Formaldehyde returned $(8e,5o)$ against its reference
$(6e,4o)$ on two of five orientations, which is wrong rather than merely
unstable.

The repair is to seed the pair from a molecular direction. A terminal atom has
no plane of its own, but its neighbour has one and §2.3 already inherits it for
the atom's $\pi$ target; the same normal now seeds the lone pairs. The pair
comes out as one direction lying in that plane and one exactly perpendicular to
it, and the perpendicular one is discarded as the duplicate it
is rather than by luck. On each of the four carbonyls in the benchmark the
oxygen now emits two lone-pair targets rather than three, and the largest
absolute cosine between either of them and the $\pi$ normal is $0.0000$ to four
decimals, which is the assertion
`tests/backend/cas_20_rotation_invariance.py` makes and the reason the
duplicate can no longer be emitted on any orientation. Nothing else moved: all
30 molecules return the space the ledger recorded for the unrotated geometry
before the repair, and the class-by-class figures of §3.1 are unchanged at
25 of 30.

**The direction was not the whole of it, and the sign is the part that is easy
to miss.** Seeding from the plane makes the *line* covariant and takes the
count to 0 of 30, which looks like the end of the matter. It leaves the sign
arbitrary. The in-plane direction is built as the cross product of the bond axis
with the inherited normal, and `local_pi_normal` fixes no sign: it returns a
cross product at a two-neighbour centre and a singular vector at a larger one,
and neither has a preferred orientation. So the direction still reversed from
one orientation of the input to another.

For these targets a reversal is not a phase convention. A $\pi$ target is a
pure $p$ function and negating it gives the same orbital with the opposite sign,
describing the same space. A lone-pair target is the hybrid of §2.3, and
negating $\hat d$ leaves the $s$ lobe where it is while flipping the $p$ lobe,
so $+\hat d$ and $-\hat d$ are two different hybrids pointing opposite ways
and they project onto different orbitals.

Neither the benchmark nor the test caught this, and the reasons are worth
stating because they generalise. The recommended space did not move, so a
measurement that compares spaces cannot see it. The regression test compared
directions up to sign, which is correct for a $\pi$ target and is comparing the
wrong object for a lone pair. What exposed it was a number that failed to
reproduce: formamide's $n \rightarrow \pi^*$ hole capture read 0.802 against
the 0.806 recorded in the earlier study. Restoring the old seed and changing
nothing else returns 0.806, and the new seed returns 0.802 on four consecutive
runs, so the difference was real rather than scatter.

The sign is now fixed by the molecule as well: the in-plane direction is
oriented away from the centroid of the substituents on the neighbouring atom,
which for a carbonyl oxygen is the two groups hanging off the carbonyl carbon.
The rule is geometric, so it rotates with the molecule and does not depend on
the order atoms appear in the input file.

Where those substituents are symmetric about the bond axis the projection is
exactly zero, no sign is preferred, and none is imposed. That is a property
rather than a gap, because the two signs are then related by the molecule's own
mirror plane and give identical projection weights. Both halves of that were
measured by running the capture at each sign in turn:

| carbonyl | outward projection | $n \rightarrow \pi^*$ capture, outward | flipped |
|---|---|---|---|
| formaldehyde | 0.0 | 0.660 | 0.660 |
| acetone | 0.0 | 0.681 | 0.681 |
| p-benzoquinone, 2.75 eV | 0.0 | 0.617 | 0.617 |
| p-benzoquinone, 2.84 eV | 0.0 | 0.708 | 0.708 |
| acrolein, 3.60 eV | 0.068 Å | **0.668** | 0.667 |
| acrolein, 7.12 eV | 0.068 Å | **0.572** | 0.570 |
| formamide, 5.45 eV | 0.105 Å | **0.806** | 0.802 |
| uracil, 5.03 eV | 0.0046 Å | **0.760** | 0.756 |
| uracil, 6.19 eV | 0.061 Å | **0.818** | 0.817 |

The four molecules whose projection is zero give the same capture to three
decimals either way, which is what the mirror-plane argument requires and is
the evidence that the sign left free there is genuinely free. The five states
where a sign is defined all capture more with the outward choice than with its
exact reversal, by between 0.001 and 0.004. So the convention is not a toss-up
between equivalent options.

The claim is deliberately the narrow one. A molecule with two carbonyls has four
sign combinations rather than two, and enumerating uracil's shows the outward
rule is better than reversing it on both states while not being the maximum over
all four for both: a mixed combination takes the 6.19 eV state by 0.001 and
loses the 5.03 eV state by more. The supplement carries that enumeration. A
selection scheme cannot search for a per-state maximum before it knows the
answer, so what is wanted is a rule fixed by the molecule that beats its
alternative, which is what this is.

The cut separating the two populations is taken from the data rather than
assumed. Over the twelve terminal heteroatoms in the benchmark that have any
substituent behind them, four project exactly 0.0 and the remaining eight run
from 0.0046 Å on uracil's O4 to 1.14 Å on ozone, so any threshold between
floating-point noise and about $4 \times 10^{-3}$ Å separates them identically.

The seed stays arbitrary where the molecule supplies nothing to replace it,
which is a terminal heteroatom whose neighbour has no plane either. Enumerating
that condition over all 36 geometries, which
`scripts/casbench/rotation_invariance.py --fallback` does by asking
`local_pi_normal` for the atom and for its neighbour and reporting the atoms
where both answer nothing, returns three molecules: N$_2$, stretched N$_2$ and
O$_2$, both atoms in each. The condition is structural rather than incidental,
since a neighbour supplies no plane only when it is itself terminal or its own
neighbours are collinear, which is the diatomic and linear-centre class. §4.4
states what is and is not guaranteed there.

**Handoff.** Pyrrole's $(8e,6o)$, recommended in def2-SVP, handed to another
basis:

| handoff into | by MO index (principal cosine) | by specification |
|---|---|---|
| cc-pVDZ | 0.999 | $(8,6)$ |
| def2-TZVP | 0.989 | $(8,6)$ |
| aug-cc-pVDZ | **0.000** | $(8,6)$ |

An index handoff fails completely into aug-cc-pVDZ, because diffuse functions
reshuffle the virtual manifold and the same indices name an orthogonal set.
Since a diffuse basis is exactly what a user moves to when Rydberg states
matter, this is not an edge case.

**Which diffuse basis matters.** def2-SVPD carries diffuse functions by name and
still cannot resolve a diffuse particle orbital on four of seven molecules
tested: methylamine and ammonia fail the diffuseness gate outright, and pyrrole
and furan pass it and then label a plainly Rydberg particle "mixed".
aug-cc-pVDZ resolves all seven. The cost of being right is between nothing and a
factor of two on the linear-response pass: 0.99x on formaldehyde, 1.38x on
methylamine, 1.44x on pyrrole, 1.97x on uracil, 1.38x on p-benzoquinone.

**Refinement.** A separate and weaker claim, because every reading the
refinement edits on comes from a correlated wavefunction computed *in* a basis.
Measured on three molecules in three bases, the refined space is nonetheless
identical: formaldehyde $(6,4)$, pyrrole $(6,5)$, uracil $(12,9)$ in def2-SVP,
def2-SVPD and cc-pVDZ, with natural occupations agreeing to about 0.005.

### 3.7 Transition metals, and why they are out of scope

Three metal systems were added to the benchmark, measured, and removed:
Cr$_2$, TiO and octahedral [Fe(H$_2$O)$_6$]$^{2+}$. Nothing failed. The
perception emits a $d$-shell target for all twenty-nine transition metals, the
projection admits it, and all three produce a space at ordinary cost, 0.2 s for
the diatomics and 5.0 s for the nineteen-atom ion.

The reason they are out of scope is §3.6's property failing. Of the five bases
swept, two are not defined for Cr or Fe at all. Across the three that are:

| molecule | STO-3G | def2-SVP | def2-TZVP |
|---|---|---|---|
| benzene | $(6e,6o)$ | $(6e,6o)$ | $(6e,6o)$ |
| uracil | $(18e,12o)$ | $(18e,12o)$ | $(18e,12o)$ |
| Cr$_2$ | $(8e,10o)$ | $(10e,10o)$ | $(10e,10o)$ |
| [Fe(H$_2$O)$_6$]$^{2+}$ | $(18e,12o)$ | $(18e,11o)$ | $(16e,11o)$ |

The iron complex returns a different space in every basis that can represent it.
Whatever those answers are, they are not the basis-independent quantity this
method computes.

The cause is structural. A metal emits its $d$ shell and nothing else, so on
Cr$_2$, where both atoms are metals, the entire target set is two $d$ shells and
the $4s$ orbitals the conventional $(12e,12o)$ contains have nothing to select
them; the engine returns $(10e,10o)$. The hexaaqua ion returns the $d$ shell
plus six ligand orbitals rather than the ligand-field $(6e,5o)$. Neither
conventional space is reproduced. And three of the five pipeline stages are
blind to $d$ character by construction: the narrowing sorts a pool into $\pi$
and lone-pair, and the refinement's character audit, re-seed and root labelling
are built from the same two kinds.

A recommendation for a molecule containing a transition metal therefore carries
a note saying the engine is validated for organic molecules only, what a metal
does and does not contribute, and that the space is basis dependent in a way the
organic benchmark is not. Reported rather than refused, on the same principle
that governs cost; reported rather than left silent, because a confidently wrong
space is the worst of the three available outcomes.

### 3.8 Threshold sensitivity

Each constant is set to one value and the whole `spaces` scoring is re-run, so
every cell below is the same measurement as §3.1 taken at a different setting:
how many molecules the recommended space reproduces the literature space for,
exactly. Higher is better, and the shipped value is in bold.

**Projection cut** ($w_{\min}$ in §2.4), the eigenvalue at which an orbital
joins the pool:

| 0.05 | 0.10 | 0.15 | **0.20** | 0.30 | 0.40 |
|---|---|---|---|---|---|
| 21/32 | 23/32 | 24/32 | **25/32** | 25/32 | 25/32 |

**Planarity cut** (§2.2), which decides whether a centre gets a $\pi$ target:

| 0.10 | 0.20 | **0.25** | 0.35 | 0.50 |
|---|---|---|---|---|
| 25/32 | 25/32 | **25/32** | 25/32 | 25/32 |

**Bond tolerance** (§2.2), the covalent-radius multiplier the whole
connectivity is built from:

| 1.15 | 1.25 | **1.30** | 1.40 | 1.50 |
|---|---|---|---|---|
| 25/32 | 25/32 | **25/32** | 25/32 | 25/32 |

**Entropy gap** (§2.6), which separates the minimal tier from the recommended
one:

| 0.05 | 0.10 | **0.15** | 0.25 | 0.40 |
|---|---|---|---|---|
| 25/32 | 24/32 | **25/32** | 25/32 | 24/32 |

The denominator is 32 rather than the 30 of §3.1 because this sweep was run
while the two transition-metal systems were still in the benchmark. They score
the same in every row and so shift each column by a constant, which changes the
absolute numbers and none of the shapes.

The projection threshold rises monotonically to the shipped 0.20 and is flat
above it, so the shipped value is the lowest one that reaches the best score.
The planarity cut and the bond tolerance are flat across the ranges tested. The
entropy gap is non-monotone, 25, 24, 25, 25, 24, which is the signature of
knife-edge molecules rather than of a better value, and it is left where it is.

The refinement's own constants are flat for four of six molecules across a grid
of drift tolerance $\{0.10, 0.20, 0.30, 0.50\}$ eV and occupation window
$\{1.95, 1.98, 1.99\}$. Uracil is not flat and is non-monotone, returning
$(14e,10o)$ at both 1.95 and 1.99 and $(12e,9o)$ only at the shipped 1.98. Over
the whole refinement set, halving the drift tolerance changes the outcome for
exactly one molecule of 34, which is uracil, so the entire case for changing it
rests on the molecule already established as non-monotone in that parameter.

### 3.9 Cost and time complexity

Each row gives the dominant term for that stage, not the cheapest one.

| stage | dominant cost | measured |
|---|---|---|
| SCF reference | $O(N_{\text{bas}}^4)$ formally, density-fitted in practice | ~0.2 s, 10 heavy atoms |
| Stability analysis | an iterative eigenproblem over the same integrals | 0.3x to 13x the SCF |
| Perception | $O(N_{\text{atom}}^2)$ neighbour search | milliseconds |
| Projection | $O(N_{\text{bas}}^2 N_{\text{MO}})$ contraction, then two eigendecompositions | milliseconds |
| APC ranking | $O(N_{\text{occ}} N_{\text{vir}})$ pair loop, riding on integrals already formed | ~0.1 s |
| **Ground-state recommendation** | dominated by the SCF and its stability analysis | **0.27 s median** |
| Excited-state branch | one TDA linear response, $O(N_{\text{bas}}^4)$ per Davidson iteration | seconds to minutes |
| Refinement | $R \cdot N_{\text{CSF}}$ CI cost per macro-iteration | **8.8 s median** |

The asymmetry between the recommendation and the refinement is the design. Every
stage of the recommendation is polynomial in the one-electron dimensions and
none of them touches the CI space, so the recommendation is bounded by the SCF
it consumes and needs no orbital-count cap to stay interactive. The refinement
inherits the factorial-like growth of $N_{\text{CSF}}$ in the active-space size,
which is exactly why it is a separate opt-in tier.

The stability analysis is the one stage whose cost varies by more than an order
of magnitude with molecule size: 0.29x the SCF on water, 1.16x on twisted
ethylene, 7.1x on square cyclobutadiene, 13x on anthracene, where it takes 45 s.
It is paid unconditionally rather than on a heuristic, because a conditional
check fires on a minority of molecules and is therefore rarely exercised, and
because a recommendation precedes a refinement measured in minutes.

### 3.10 What the refinement does

Over all 36 benchmark geometries in def2-SVPD, with a one-hour cap per molecule.
The denominator is 36 rather than the 30 of §3.1 because the refinement needs no
reference space to be measured against: it is judged on what it changes and
whether it converges, so the six molecules carrying no published space are
included.

- **34 return a refined space.** The two that do not are anthracene, whose only
  tier is 2,760,615 CSFs, and dimethyl sulfide, whose only tier is 367,479,684.
  Both decline explicitly, naming the number, rather than substituting a space
  nothing measured.
- **33 of those 34 converge.** The one that does not is p-benzoquinone, which
  runs the full hour.
- **6 change the space**: ammonia, furan, hydrogen sulfide, o-nitrophenol,
  uracil and water. The other 28 come back unchanged, which is the common and
  desirable outcome: it means the recommendation was already right.
- Median 8.8 s against a median recommendation of 0.27 s.

The changes are of two kinds. A narrowing, where the requested states do not use
the whole pool -- uracil goes from $(18e,12o)$ to $(12e,9o)$ and o-nitrophenol
from $(22e,15o)$ to $(16e,12o)$. And a prune, where an orbital carries no
correlation for these states, which is what takes water and hydrogen sulfide
from $(8e,6o)$ to $(4e,4o)$. Every change is recorded with the orbital it moved
and the reason, so a user can replay it by hand.

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

**Ranked-orbital / APC [2, 3]** supplies the entropy measure used in §2.5, and
the debt is direct. The difference is scope: APC applied over the whole
molecular-orbital space is basis dependent, as quantified in §1. Here APC orders
a pool that a basis-independent projection has already chosen, so the ranking
never sees the growing virtual manifold that causes the drift.

**AutoCAS [5, 6]** obtains orbital entropies from a DMRG pilot. That is a more
faithful entropy than a closed-form estimate, and it costs correspondingly more.
The present method's ranking is about 0.1 s where a DMRG pilot is minutes, which
is what permits an interactive recommendation with no orbital cap. Where AutoCAS
is likely to be better is strongly correlated systems in which the two-level
estimate of §2.5 is a poor model of the true pair structure.

**Occupation-threshold schemes [7, 20]** select on natural-orbital occupations.
The results here argue that occupation alone is not a safe selection criterion:
an occupation cut applied to uracil's two lone pairs takes one of them at four
roots and neither at six. A criterion whose verdict moves with a solver setting
cannot be the thing that decides membership. Occupations are used here only to
*prune* a space that has already been selected, and every prune is verified by
re-solving.

**AEGISS [4]** is the closest published relative: it also combines an
atomic-orbital-based construction with an entropy criterion rather than choosing
one or the other. Its atomic-orbital step is specified by element and shell in
the AVAS manner, where the perception of §2.2 orients each target along a
geometric axis, and its entropy is a selection threshold where §2.5 uses it only
to order a pool whose membership a projection has already decided. The
comparison is necessarily loose: AEGISS is a preprint that was not peer reviewed
at the time of writing, and no attempt has been made here to reproduce its
benchmark.

**Active Space Finder [11]** reports a best mean absolute error of 0.49 eV for
l-ASF(QRO) over 32 molecules in def2-TZVPD, with 25-30% unsatisfactory results
for every scheme in fully automatic mode. The 0.32 eV of §3.3 is not
like-for-like -- a different molecule set, a smaller basis and a different
downstream method -- and should be read as a soft comparison rather than a
ranking.

### 4.2 What the span finding implies for the field

Automatic active-space schemes are conventionally scored on whether they
reproduce a published space. §3.5 shows that metric can be satisfied while the
requested state remains unreachable, and that the failure is invisible to every
count-based measure. A space can match its literature reference on both
electrons and orbitals and produce no root of the requested character at three,
six or ten roots, nor in a singlet-constrained CASCI in the seeded space.

We suggest that hole capture -- projecting the hole natural transition orbital
of the target state onto the selected columns -- is a cheap and direct
reachability measure that any state-specific selection scheme could report, and
that reporting it alongside a size match would catch a class of silent failure
that sizes cannot.

### 4.3 What a diffuse orbital does inside a valence space

The second transferable negative result, and it is sharper than the usual advice
that Rydberg states are difficult.

The obvious way to make a valence active space describe a requested Rydberg
state is to put the orbital in: take the particle natural transition orbital
from the linear-response pass, orthogonalise it against the space, and append
it. That works mechanically and it converges. What it does not do is survive.
Measured on formaldehyde, the appended orbital enters with 0.648 of its density
outside 1.5 van der Waals radii and leaves the state-averaged CASSCF with 0.471,
below the threshold that distinguishes a diffuse orbital from a valence one at
all. The orbital optimisation contracts it, and what the space then describes is
neither the Rydberg state nor a valence one.

The energies follow. Formaldehyde's Rydberg state has a reference value of 7.30
eV and comes back at 5.93 eV in the served space, which is what a collapse onto
a more compact orbital looks like; ammonia's roots move away from their
reference rather than toward it, and differ between identical runs.

Two things follow for a scheme that means to serve such a state. Adding the
orbital is not sufficient, because orbital optimisation will undo it; and the
diagnostic that would notice must be absolute rather than relative to the active
space, since a ratio against the space's own extent cannot see a diffuse orbital
once that orbital is inside the space. The engine therefore identifies the
state, declines to build a space around it, and says so.

### 4.4 Limitations

**Two directions are still chosen arbitrarily on an axially symmetric centre.**
Where a terminal heteroatom's neighbour supplies no plane, which is a diatomic
or a linear centre, the perpendicular pair is seeded from the laboratory frame
because the molecule offers nothing to seed from. The pair is then covariant
only in its span, and the $s$ amplitude of §2.3 means even the span is not
strictly invariant. This cannot be repaired rather than merely has not been: an
axially symmetric centre has no perpendicular direction to prefer, so no choice
of pair is covariant. It is also where it matters least, because the
perpendicular plane is degenerate by symmetry. Three of the 36 geometries reach
it, N$_2$, stretched N$_2$ and O$_2$, and none of the three changes its space
under rotation. Elsewhere orientation independence is a property of the
construction; here it is a property of the measurement.

**Transition metals are out of scope**, for the measured reasons in §3.7.

**Dissociation has a cliff.** The engine returns a correct $(10e,8o)$ for N$_2$
at every separation out to 1.80 Å and fails at 1.85 Å, where the pair falls
outside the covalent-radius criterion of §2.2, no bond emits a $\sigma$ axis,
and a two-atom molecule has no atom with two neighbours to emit a $\pi$ normal.
The honest repair is to fall back to atomic valence shells when no bond
survives, rather than to loosen the tolerance for every other molecule.

**Rydberg states are declined rather than served**, for the reason §4.3
measures. The engine identifies such a state and says a valence active space
cannot describe it. What it cannot do is produce one.

**A state audit on a large space reports "not found" rather than "not there".**
A Davidson solver reaches only what its initial guess spans, and pyscf builds
that guess from the 400 lowest-diagonal determinants. Below that the guess spans
the space and an absent state really is undescribable; above it, absence from
the roots is not absence from the space, and in a planar molecule the
identically zero $a'/a''$ coupling guarantees that no number of roots repairs
it. The verdict says which regime it is in, which is the most that can be
claimed without orbital optimisation.

**A converged refinement does not say which solution it converged to.** §3.4
shows two molecules in seven with more than one converged state-averaged
solution. A user of the refinement tier meets this directly: the tier reports
convergence, and convergence is not identification. The reference energy is
reported so two runs can be compared on it.

**A space too large to refine is refused rather than approximated**, and the
recommendation stands in both cases.

**One constant is set on a knife edge for one molecule**, the prune's drift
tolerance, reported in §3.8 rather than tuned.

**Adding roots is not a repair for a missing state.** Across six molecules at
three root counts, no molecule at any root count recovered a state that fewer
roots had missed. The root margin buys convergence and speed rather than
coverage: formamide takes 103.6 s and does not converge at margin 0 against
3.2 s converged at margin 3.

---

## 5. Conclusion

Selecting an active space by projecting onto oriented, geometry-derived targets
expressed in a fixed minimal basis gives a recommendation that is
independent of both the calculation basis and the orientation of the input --
measured, not merely by construction, with no molecule of thirty changing its
space across five basis sets or five random rotations -- costs 0.27 s at the
median,
requires no orbital-count cap, and is reproducible across identical runs. It
reproduces the literature space for 25 of 30 benchmark molecules for a
ground-state request and 27 of 30 when states are specified. Ordering the pool
by a closed-form entropy keeps the cost interactive; asking the requested states
which orbitals they use, through natural transition orbitals from a
linear-response pass, makes the selection state specific without a CASSCF.

Four results transfer beyond this implementation, and all four are negative.

A recommended space can match its published size exactly on both electrons and
orbitals and still fail to span the state it was chosen for, and no count-based
metric detects this. Measuring hole capture directly found it and attributed it
to a single hybridisation constant. Schemes that select active spaces for
particular electronic states should measure reachability rather than infer it
from size.

A converged mean field is not necessarily a stable one, and where it is not, the
ambiguity reaches the active space. One benchmark molecule returned two
different recommendations across identical runs for this reason, and three more
were reproducibly built on a stationary point that was not a minimum, which no
amount of repetition would have revealed. A selection scheme that reads a
Hartree-Fock reference should ask whether that reference is stable before
reading it.

A construction that is invariant only in its span stops being invariant once
its members are hybridised, and the failure need not look like noise. Here it
surfaced as a duplicate: the test that removed a redundant direction compared
against one specific vector, and an arbitrary basis of a plane matches a
specific vector only by chance. Six of thirty molecules returned two different
spaces depending on how the input geometry happened to be oriented, and on the
molecule where the answer could be checked against the literature, two of five
orientations were wrong rather than merely inconsistent. A scheme that derives
targets from geometry should assert covariance of the directions it emits, and
not only of the space they span.

The same finding has a second half that took longer to see, and it is the more
transferable one. Repairing the direction left the **sign** arbitrary, because
the normal it now inherits comes from a cross product or a singular vector and
neither fixes one. For an oriented $sp$ hybrid a reversal is not a phase
convention: the $s$ lobe stays put while the $p$ lobe flips, so the two are
different functions. Nothing caught it. The recommended space did not move, so
the benchmark could not see it, and the regression test compared directions up
to sign, which is right for a pure $p$ target and is comparing the wrong object
for a hybrid. It surfaced only because a single downstream number, one hole
capture in one molecule, failed to reproduce a value recorded earlier, and the
discrepancy was chased instead of rounded away. A test that canonicalises away
a degree of freedom cannot detect that the degree of freedom is unconstrained,
and an aggregate that is stable is not evidence that the quantities behind it
are.

And a diffuse orbital added to a valence active space does not survive the
orbital optimisation it is handed to. It contracts, the state it was added for
collapses onto something more compact, and the diagnostic that would notice
cannot see it, because a diffuseness measured relative to the active space is
blind to a diffuse orbital inside that space. Serving a Rydberg state needs more
than putting its orbital in.

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
which the Weyl-Paldus dimension formula of §2.6 follows.

[24] K. K. Docken and J. Hinze, "LiH Potential Curves and Wavefunctions for
X$^1\Sigma^+$, A$^1\Sigma^+$, B$^1\Pi$, $^3\Sigma^+$, and $^3\Pi$",
*J. Chem. Phys.* **1972**, *57*, 4928-4936. The origin of the state-averaged
MCSCF procedure of §2.9.

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
