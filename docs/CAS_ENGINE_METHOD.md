# A geometry-oriented projection method for automatic active-space selection

**Status:** implemented 2026-09, `app/chemistry/cas/`. This document is the
method of record. It supersedes [`CAS_RECO_REDESIGN.md`](CAS_RECO_REDESIGN.md),
which describes the previous entropy-pilot design.

---

## 1. The problem

A CASSCF, CASPT2 or NEVPT2 calculation requires a choice of active space: a set
of $n$ orbitals holding $N$ electrons, within which the wavefunction is expanded
to full CI. The choice is not a convenience. Too small and the qualitative
physics is missing; too large and the calculation is intractable, since the
determinant count grows as $\binom{n}{N_\alpha}\binom{n}{N_\beta}$. Choosing it
well has traditionally required an expert, and automating that choice is an
active research problem with no settled solution: a recent assessment of the
leading fully automatic schemes reports 25-30% unsatisfactory results across
every variant tested [11].

The design target was a selector that

1. is **cheap** enough to run interactively, so a user can ask for a
   recommendation and get one in seconds;
2. imposes **no ceiling** on the number of active orbitals;
3. gives the **same answer regardless of the basis set**, and regardless of how
   the input geometry happens to be oriented;
4. is **robust to the character of the requested states**, whether pi->pi\*,
   n->pi\* or Rydberg, bright or dark.

Points 3 and 4 are where the previous implementation failed, and they turn out
to be related: both are consequences of asking the wavefunction the wrong
question.

---

## 2. How this compares to existing methods

Automatic active-space selection is a crowded field, and the methods in it
differ less in their machinery than in **what question they ask**. That is the
useful axis for comparison, because it predicts where each one fails.

### 2.1 Four questions, four families

**"Which orbitals have atomic character I care about?"** AVAS [1] projects the
molecular orbitals onto reference atomic orbitals drawn from a minimal basis
(here PySCF's `minao`, in the spirit of [28] rather than using intrinsic atomic
orbitals themselves) and diagonalises the projector separately in the occupied
and virtual blocks. It is
fast, deterministic, and needs only a converged SCF.

*Strength:* the answer is chemically stated. Ask for oxygen 2p and you get the
orbitals carrying oxygen 2p. *Weakness:* the request is made in the
**laboratory frame**. A chemist targeting the pi system of a planar molecule
writes `C 2pz` because the molecule happens to lie in the *xy* plane; rotate the
input and the same label selects different physics. AVAS also requires the user
to know which labels to ask for, which is the expert judgement the automation
was meant to remove.

**"Which orbitals are strongly correlated?"** Entropy methods. AutoCAS [5,6]
takes single-orbital entropies from a partially converged DMRG calculation over
a large preliminary space and keeps those above a threshold. The approximate
pair coefficient (APC) of King and Gagliardi [2,3] answers the same question in
closed form from the Fock and exchange matrices, at essentially no cost.

*Strength:* correlation importance is the property that actually matters for a
CASSCF, measured rather than assumed. *Weakness:* a ranking is only as good as
the set it ranks. Over the full virtual manifold it is **not basis
independent**, because the manifold grows with the basis. Measured here, raw APC
over all molecular orbitals gives pyrrole $(18e,12o)$ in def2-SVP and
$(22e,13o)$ in def2-TZVP, promoting orbitals that are artefacts of the larger
manifold.

**"Which orbitals have fractional occupation?"** Natural-orbital methods
[7,19,20] take a cheap correlated density and keep orbitals whose occupation
departs from 0 or 2.

*Strength:* directness. Fractional occupation is the definition of
multireference character. *Weakness:* occupation is a **ground-state** measure.
An orbital inert in $S_0$ can be the hole an excited state is built from, and an
occupation cut removes it while appearing to have proved it was never needed.
Section 9.3 measures that failure directly.

**Hybrids.** AEGISS [4] combines the first two: an atomic-orbital projection to
choose candidates, then DMRG entropies to order them. The Active Space Finder
family [11] uses MP2 natural orbitals followed by a DMRG-CASCI cumulant
analysis. These are the closest relatives of the present method in shape.

### 2.2 Where this method sits

A hybrid of the first two families, with three changes.

| | AVAS | APC alone | AutoCAS / AEGISS | ASF | **this work** |
|---|---|---|---|---|---|
| input beyond SCF | AO labels from user | none | DMRG on a large pool | MP2 + DMRG-CASCI | none |
| cost | seconds | ~0.1 s | minutes to hours | minutes | **~0.2 s** |
| basis independent | no | no | not by construction | no | **yes, measured** |
| rotation independent | **no** | yes | yes | yes | **yes, by construction** |
| state-specific | no | no | no | partly | **yes** |
| predicts or measures | predicts | predicts | measures | measures | **predicts, then optionally measures** |
| orbital ceiling | none | none | practical | practical | **none** |

**Change 1: the reference directions come from the geometry, not the user.**
Instead of `C 2pz`, the reference at atom $A$ is a unit-vector combination of
that atom's minimal-basis $p$ functions along a direction derived from the
structure (section 4). Under rotation the direction and the $p$ functions
transform together, so the selected space is carried into itself. This removes
both the lab-frame dependence and the requirement that a user name the right
labels.

**Change 2: the entropy ranks a pool the geometry already fixed.** APC is
applied strictly inside the projector's output rather than over the whole
virtual manifold, so the ordering inherits the pool's basis independence. The
cost is that the entropy does a smaller job than it does in AutoCAS or AEGISS.
Section 5.1 measures how much smaller, and it is a limitation rather than a
feature.

**Change 3: the states are asked what they are made of.** A request for $k$
excited states triggers a linear-response pass whose natural transition orbitals
say whether each state is n->pi\*, pi->pi\* or Rydberg, which orbitals it is
built from, and whether the proposed space contains them (section 6). Selecting
on ground-state correlation alone is how a dark n->pi\* state loses its
heteroatom lone pair and disappears without comment.

### 2.3 What this method gives up

Three things, stated plainly, because they are the price of the above.

**It is a prediction, not a measurement.** AutoCAS and ASF pay minutes to hours
for entropies or cumulants from a correlated wavefunction; this pays 0.2 s for a
projection and a closed-form estimate, and a projection cannot know what orbital
optimisation will do [21]. Section 9 exists because of that gap: an optional
refinement tier that runs the CASSCF and corrects the estimate against it.

**It assumes the chemistry is describable by directions.** The reference set is
built from pi normals, lone-pair directions, sigma axes and transition-metal $d$
shells. A system whose active space is not naturally expressed that way, a
strongly delocalised metallic cluster for instance, has no natural target set
here, where an entropy method needs no such assumption.

**It inherits AVAS's threshold.** The eigenvalue cut $\tau = 0.2$ is AVAS's own
default, retained so the two remain comparable. It is not fitted, but it is not
without consequence: it decides pool size, and section 4.3 shows pool size and
detection sensitivity are coupled through it.

Methods this is *not*: it is not AutoCAS; it is not the Active Space Finder
family; it is not a natural-orbital-occupation method; and it does not use
machine learning.

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
                                                           │
                          (opt-in) ──────────────▶ CASSCF refinement
```

Everything except the optional TDA pass costs a fraction of a second on top of
one SCF. The engine never builds a `Mole` and never imports the application's
job registry, so the same code runs inside the job worker, inside the benchmark
harness, and in a bare script.

---

## 4. The oriented projector

### 4.1 Construction of the reference set

Let $\hat{\mathbf{a}}_A$ be a unit vector at atom $A$ derived from the geometry.
The reference orbital is the corresponding combination of that atom's
minimal-basis $p$ functions,

$$
|t_A\rangle \;=\; a_x\,|p_x^A\rangle + a_y\,|p_y^A\rangle + a_z\,|p_z^A\rangle .
$$

Under a rotation $\mathbf{R}$ of the molecule, $\hat{\mathbf{a}}_A \to
\mathbf{R}\hat{\mathbf{a}}_A$ and the $p$ functions transform the same way, so
$|t_A\rangle$ is carried into itself. The selected space is invariant.

### 4.2 Where the directions come from

Three kinds of direction, all from the geometry alone, with bonds from covalent
radii [8]:

**Pi normals.** At an atom with exactly two neighbours, the normal to the plane
they define, $\hat{\mathbf{n}} \propto \mathbf{v}_1 \times \mathbf{v}_2$. At an
atom with three or more, the best-fit plane normal, the right-singular vector of
least variance of the centred neighbour displacements. A fitted normal is
accepted only if the centre is genuinely planar,

$$
\max_i \left| \hat{\mathbf{v}}_i \cdot \hat{\mathbf{n}} \right| < 0.25 ,
$$

which is 0 for a planar centre, $\approx 0.37$ for pyramidal ammonia and
$\approx 0.577$ for a tetrahedral one. Without this test an SVD returns a
confident direction of least variance for an sp3 carbon, and every saturated
carbon acquires a spurious pi orbital.

**Lone pairs.** From the coordination geometry: for two neighbours, the
direction opposing their bisector and the normal to their plane; for three, the
direction opposing their sum. For a *terminal* heteroatom all three non-bonding
directions are emitted, because which is the true lone pair depends on the bond
order, and bond orders are not available from geometry alone. A carbonyl
oxygen's lone pairs are perpendicular to C=O; a nitrile or dinitrogen nitrogen's
lies along the axis. The projection discards whichever holds no density, which
is cheaper and more robust than perceiving bond orders.

**Sigma axes.** For every bond, the bond direction, emitted on *both* atoms.

### 4.3 A lone pair is an sp hybrid, and so is a sigma bond

A reference built from $p$ functions alone is the wrong shape for either. A
heavy-atom sigma bond is an sp hybrid rather than a pure $p$ lobe, and so is a
lone pair on a heteroatom: a carbonyl oxygen's in-plane lone pair carries real
$s$ character and delocalises into the adjacent sigma framework. So a target
carrying an $s$ amplitude becomes an **oriented sp hybrid**, $s$ and $p$ of the
same atom in a single column:

$$
|t_A\rangle \;=\; c_s\,|s^A\rangle \;+\; \sqrt{1 - c_s^2}\;
\big(a_x |p_x^A\rangle + a_y |p_y^A\rangle + a_z |p_z^A\rangle\big),
\qquad c_s = 1/\sqrt{3}
$$

for the sp2 case used here.

The cost of omitting it is large and silent. Measured on uracil, **an orbital
scoring 0.715 lone-pair character against an sp reference scores 0.019 against a
pure $p$ one**, a factor of 39. With pure-$p$ references the engine could not
see uracil's carbonyl lone pairs at all: absent from the pool, absent from the
re-seed that should have restored them, and unrecognisable to the character
classifier, so the n->pi\* state built on them was reported missing.

**The orientation is what makes it work**, and this was measured rather than
assumed. Three variants, over the fifteen benchmark molecules carrying a
literature space:

| lone-pair reference | literature spaces | that uracil orbital scores |
|---|---|---|
| pure oriented $p$ | 10 / 15 | 0.019 |
| bare valence $s$ | 9 / 15 | 0.715 |
| two oriented references ($p$ and sp) | 9 / 15 | 0.715 |
| **one oriented sp hybrid** | **10 / 15** | 0.327 |

A bare valence $s$ has no direction, so it overlaps an atom's sigma-bonding
hybrids exactly as well as its lone pair. Adding one pulled the deep sigma
framework into the pool, took formaldehyde from an exact $(6e,4o)$ to $(8e,5o)$
and uracil's *minimal* tier from $(14e,10o)$ to $(30e,18o)$. The two-reference
variant is the informative failure: it detects identically to the bare $s$ and
inflates identically, which isolates the mechanism. **The pool grows with the
number of targets clearing the threshold $\tau$, not with their orientation.**
Detection and pool size are coupled through $\tau$, so no variant is
simultaneously more sensitive and equally selective, and the single oriented
hybrid is the one that improves detection seventeen-fold while leaving every
benchmark space where it was.

### 4.4 Why sigma targets are mandatory

A sigma bond needs a target on **both** atoms: the bonding and antibonding
combinations are what the projection separates into an occupied and a virtual
orbital, and emitting only one end gives a pool with no virtual partner.

For a molecule with no pi system, water or ammonia or methane, selecting on pi
and lone-pair character alone returns orbitals that are all doubly occupied: one
configuration, no correlation described at all. With every bond contributing its
sigma and sigma\*, water comes back as $(8e,6o)$ with virtuals in it, and the
hydride special-casing the previous engine needed disappears.

Heavy-atom sigma targets carry the valence $s$ as well as the oriented $p$, for
the reason in 4.3. On N2 that is the difference between the $(10e,7o)$ a
$p$-only set finds and the $(10e,8o)$ full valence space the literature uses;
the same orbital is missing from O2.

### 4.5 The projection

With $\mathbf{T}$ ($n_{\text{minao}} \times n_{\text{target}}$) holding the
oriented targets, $\mathbf{S}^{pp}$ the minimal-basis overlap, $\mathbf{S}^{pc}$
the cross overlap with the calculation basis and $\mathbf{C}$ the MO
coefficients:

$$
\mathbf{S}^{2} = \mathbf{T}^{\dagger}\mathbf{S}^{pp}\mathbf{T},
\qquad
\mathbf{S}^{21} = \mathbf{T}^{\dagger}\mathbf{S}^{pc}\mathbf{C},
\qquad
\mathbf{A} = \left(\mathbf{S}^{21}\right)^{\dagger}
             \left(\mathbf{S}^{2}\right)^{+}\mathbf{S}^{21}
$$

$\mathbf{A}$ is the projector onto the target space in the MO basis. Its
occupied and virtual blocks are diagonalised separately, which is what keeps the
electron count well defined, and eigenvalues above $\tau = 0.2$ define the
active space.

The Moore-Penrose pseudo-inverse in $\left(\mathbf{S}^{2}\right)^{+}$ is
essential rather than defensive. The target set is deliberately over-complete:
sigma targets on bonded neighbours overlap heavily, a lone-pair direction can be
near-parallel to a sigma one, and a linear centre emits a degenerate pair.
$\mathbf{S}^{2}$ is therefore singular in general. The pseudo-inverse makes
$\mathbf{A}$ the projector onto the *span* of the targets, so the result depends
only on that span and never on the particular redundant, non-orthogonal vectors
chosen to describe it. This is also what makes the non-covariance of the
degenerate perpendicular pair harmless: an axially symmetric centre such as N2
admits no covariant choice of two perpendicular directions, but both members are
always emitted together, and a projection onto a subspace does not care which
basis of it was supplied.

Open-shell references follow AVAS's `openshell_option=2` convention, with singly
occupied orbitals counted on the alpha side. ROHF is used rather than UHF, by
measurement rather than by argument: over four radicals and three basis sets
ROHF gives an identical space every time, while UHF moves for the methyl
radical, its alpha and beta sets relaxing differently.

---

## 5. Ranking

The projector answers *which orbitals are chemically relevant*. It does not
order them, and for a molecule of any size the sigma-inclusive pool is larger
than anyone wants to correlate: benzene's is 25 orbitals.

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

and each orbital is assigned the von Neumann entropy of the resulting normalised
two-state population,

$$
\sigma_p = \frac{\sum_q c_{pq}^2}{1 + \sum_q c_{pq}^2},
\qquad
s_p = -\sigma_p \ln \sigma_p - (1-\sigma_p)\ln(1-\sigma_p).
$$

The APC-*N* variant [3] repeats the estimate, promoting the highest-entropy
virtual to singly occupied each round, so one low-lying virtual cannot dominate.
$N = 2$ is used.

This requires only $\mathbf{F}$ and $\mathbf{K}$, both of which a converged SCF
has already built. No CASCI, no MP2, no DMRG, no iteration: measured at
$\approx 0.1$ s.

For an open-shell reference the matrices are taken from the ROHF solution of
4.5 in PySCF's own canonicalisation, and the occupation vector the entropy is
built on is set from the declared spin rather than from $N/2$: `spin_2s` singly
occupied orbitals above the doubly occupied ones. Getting that wrong is not
subtle in its effect -- filling $N/2$ orbitals doubly regardless of spin gave
O2 a minimal tier of $(2e,3o)$.

### 5.1 What the entropy is for here, and what it is not

Applying the ranking after the projection rather than before it changes its
role, measurably. Over water, formaldehyde, benzene, pyrrole and butadiene, the
relative APC entropies inside the projected pool span only **0.55 to 1.00**,
never an order of magnitude.

That is not a defect in the entropy. It is the projector having already made the
selection on chemical grounds, so every orbital reaching the ranking is
genuinely relevant. In AutoCAS [5,6] and AEGISS [4] the entropy ranks around a
hundred frontier orbitals of which most are inert, and an absolute cut at
$S_{\max}/10$ discards the bulk. Applied to a pool that is already tight, the
same rule discards nothing: the right answer for the wrong reason.

**This is the sharpest conceptual trade against the entropy-first methods.**
They use the entropy as the selector and pay for a wavefunction good enough to
trust it. Here the geometry is the selector and the entropy is a tie-breaker, so
it costs nothing and carries correspondingly little information. A *gap* search
is what still says something about a flat profile: it fires only where there is
a real shoulder. At a relative gap of 0.15 it declines to cut benzene below
$(6e,6o)$ or butadiene below $(4e,4o)$, where every pi orbital genuinely
matters, and recovers pyrrole's textbook $(6e,5o)$ pi space. Where the profile
has no shoulder it returns the recommended tier unchanged, which is the honest
answer: formaldehyde's four candidates score 0.159, 0.146, 0.181 and 0.182, a
spread of 0.036 against a 0.15 threshold, so its minimal tier coincides with its
recommended one.

The ranking's remaining jobs are ordering the maximal tier, which is large, and
supplying the repair rule that keeps a subset from being chemically
half-finished.

---

## 6. The excited-state branch

Choosing a space by ground-state correlation and then computing excited states
in it is the failure mode this branch exists to prevent. A dark n->pi\* state
needs the heteroatom lone pair; a ground-state criterion sees that lone pair as
inert and drops it; the state then does not appear, and nothing reports that
anything was lost.

### 6.1 Asking the states

For $k$ requested states the engine runs a Tamm-Dancoff linear-response pass on
a CAM-B3LYP reference [9], which costs seconds and is discarded afterwards. Its
purpose is not the energies but the **characters**.

Each root's dominant natural transition orbital pair [10] is obtained by
singular-value decomposition of the transition density matrix. The hole and the
particle are then projected onto the same perceived targets the pool was built
from, so "is this a lone pair" is answered by one definition rather than two.

### 6.2 Character assignment

An orbital is labelled by which target kind it overlaps most, subject to a floor
below which it is called `mixed` rather than guessed. The particle additionally
carries a spatial extent: the ratio of its second moment $\langle r^2 \rangle$
to the largest occupied value. A ratio above 3 marks a Rydberg particle, which
is reported and deliberately kept out of the valence space, since diffuse
orbitals do not mix with valence ones and are a reliable way to make a CASSCF
hard to converge for no gain.

**`mixed` is the classifier declining to decide, not a character**, and treating
it as a mismatch is a real error. A hole whose pi weight falls just under the
floor comes back `mixed->pi*`; excluding such a root from consideration once
threw a benchmark match onto a state three electronvolts away. Comparison is
therefore by *compatibility*, where `mixed` matches anything on the side it
appears, with exact matches preferred.

### 6.3 The state average must be confined to one multiplicity

This is a correctness requirement rather than a refinement, and getting it wrong
invalidates everything downstream.

PySCF's plain FCI solver returns the lowest roots of **any** multiplicity, so
asking for five states of a closed-shell molecule does not give five singlets.
Measured on o-nitrophenol's $(12e,9o)$ at five roots:

| root | eV | $\langle S^2 \rangle$ | $2S+1$ |
|---|---|---|---|
| 0 | 0.000 | 0.000 | 1 |
| 1 | 3.735 | 2.000 | **3** |
| 2 | 4.495 | 2.000 | **3** |
| 3 | 4.826 | 2.000 | **3** |
| 4 | 6.095 | 0.000 | 1 |

Three of five are triplets. **A triplet's one-particle transition density from
the singlet ground state is zero by spin**, so the natural transition orbitals
built from it are numerical noise and the character assigned to them means
nothing. That is how o-nitrophenol's two n->pi\* singlets came to be reported as
pi->pi\*, and why requested states kept coming back "missing": the singlet being
asked about had been pushed out of the root count by triplets nobody asked for.

The CI space is therefore restricted to the declared multiplicity with a CSF
solver [29], which builds the CI space from spin-adapted configuration state
functions so that every root is spin-pure by construction, with no penalty
parameter to choose. (`fix_spin_`, which instead adds a penalty
$\lambda(\langle S^2\rangle - s(s{+}1))$, is a workable alternative for a
plain state average; it is avoided here because its shift leaks into the stored
MCSCF energies and breaks the CMS-PDFT path downstream, so the application uses
one mechanism for both.) Constrained, o-nitrophenol's five roots are all singlets, S1 becomes
n->pi\* as the reference has it, and the excitation energies move by 0.5 to
2.3 eV. It also converges better: formamide, furan and pyrrole all failed to
converge before and now converge in roughly a fifth of the time, a state average
confined to one multiplicity being a better-conditioned problem than one mixing
two.

### 6.4 Augmentation

When a predicted state's hole or particle is not spanned by the proposed space,
the missing NTO is added. Rydberg particles are excluded by design. In practice
this fires rarely, because the projector's pool usually already contains what a
valence state needs. It has been exercised on valence states only; see 11.2 for
why, which is not the reason this section used to give.

### 6.5 The one real basis dependence

Rydberg states cannot be represented without diffuse functions. When the
calculation offers no orbital diffuse enough to hold one, the engine reports
that they were **not looked for** rather than reporting their absence as a
result. Measured on water, cc-pVDZ produces no orbital above a 0.22 diffuseness
fraction while aug-cc-pVDZ finds five between 0.63 and 0.94. This is the only
place the answer depends on the basis, and it is a statement about what the
basis can represent rather than about the selection method.

**The engine spent a release deciding this a different way from how this
section describes it**, and the section was right. The paragraph above measures
orbitals; `excited.basis_has_diffuse` instead compared the smallest primitive
exponent in the molecule against 0.05. That rule called `def2-svpd`
non-diffuse, and `def2-svpd` is the engine's own analysis basis whenever
excited states are requested, so in the shipped configuration the answer was
always "not looked for". Worse, the Rydberg label is gated on the same flag, so
in `def2-svpd` formaldehyde's n->Rydberg 3s was found at 7.50 eV against a
QUEST reference of 7.30, with a second-moment ratio of 3.24, and labelled a
valence transition; a state not labelled Rydberg is not excluded by 6.4 and can
be pulled into the valence space. The rule also called aug-cc-pVDZ non-diffuse
on N2 (smallest exponent 0.056) and F2 (0.085), whose augmenting shells are
less diffuse in absolute terms than carbon's ordinary valence ones.

No single exponent cut separates the bases, which `app/chemistry/jobs/molden.py`
had already concluded in as many words. The measure this section always
described, the fraction of an orbital's density outside 1.5 van der Waals radii
of every atom, is now what the engine uses, shared between the two so they
cannot diverge again. It is evaluated once per job on the SCF reference and
passed to the analysis, because a Kohn-Sham virtual manifold is systematically
more compact than a Hartree-Fock one: over four molecules and three basis sets
every KS fraction is 0.02 to 0.08 below its RHF counterpart, all twelve pairs
still agreeing on the answer but the closest sitting 0.024 above the threshold.

The question is now asked of the calculation rather than of the basis set,
which is the more honest form of it and changes two answers on purpose: N2 in
`def2-svpd` reaches only 0.347 and F2 in aug-cc-pVDZ only 0.429, so for those
molecules in those bases there really is nothing diffuse enough to hold a
Rydberg state, whatever the basis is called.

---

## 7. Sizing, and the absence of a cap

The previous engine refused anything above twelve orbitals, because it ended by
running a state-averaged CASSCF and had to fit inside what that could afford.
This one never runs that CASSCF, so the ceiling is gone.

What replaces it is an honest cost report. For each tier the engine computes the
determinant count and the Weyl-Paldus CSF dimension,

$$
N_{\text{CSF}}(n, N, S) = \frac{2S+1}{n+1}
\binom{n+1}{\tfrac{N}{2}-S}\binom{n+1}{\tfrac{N}{2}+S+1},
$$

and reports which engines can reach it. The CSF count is the one that matters:
CAS(6,6) as a singlet holds 175 CSFs and as a triplet 189, which a determinant
count cannot distinguish.

Three tiers are always offered: **minimal** (the entropy-gap space of 5.1),
**recommended** (the projector's pool), and **maximal** (every target, sigma
included). The user chooses; the engine never refuses.

---

## 8. Reporting what the orbitals are

A space reported as $(14e, 10o)$ is not reproducible. What makes it reproducible
is knowing which orbitals, and that is a reporting problem with two traps in it.

### 8.1 Labels are a report, never a criterion

A per-orbital label is **not invariant** to rotations within the active space,
so it cannot decide whether an orbital stays or goes. The audits of section 9
measure a subspace trace instead, which is invariant to exactly those rotations.
But the orbitals a *result* reports are one specific named set, the
state-averaged natural orbitals the run converged to, and for that set a label
is well defined and is what lets a user rebuild the space by hand.

### 8.2 The n/sigma band is real chemistry, not classifier noise

The pi, n and sigma reference sets are each over-complete and mutually
non-orthogonal, so their weights do not sum to one and **an orbital can score
highly on two at once**. Four of uracil's occupied orbitals score
n $\approx 0.92$ and sigma $\approx 0.98$ simultaneously, and a plain argmax
hands all four to sigma on a margin of about 0.06.

Two rules follow. The continuous weights are published beside every label, never
instead of it. And a lone pair beats sigma from a weight of 0.50 rather than
having to win outright, because uracil emits 44 sigma targets against 6
lone-pair ones and sigma spans more by set size before any chemistry is
considered. An orbital substantially both is labelled `n/sigma`, which is the
honest answer where no threshold separates them. Those two constants were set
against two molecules and are the thinnest empirical basis in the method.

### 8.3 The orbital table is a second, independent classifier

`app/chemistry/jobs/molden.py` labels the orbitals of every CASSCF job and
shares no code with the engine above. It had the same fault in a different form:
an orbital was called `n` only if **one** atom carried more than 0.6 of the
population. A nitro, carboxyl or carboxylate group holds its lone pairs as the
symmetric and antisymmetric combinations across two equivalent oxygens, so each
carries about 0.45 and neither clears the bar. The orbital then fell through to
the shape test, where an in-plane lone pair is symmetric about the molecular
plane exactly as a sigma bond is, and came back `sigma`.

The discriminator is that **a sigma bond sits on a bonded pair**. Two nitro
oxygens are each bonded to the nitrogen and not to each other, so a group of
mutually non-bonded heteroatoms holding an occupied orbital between them is a
lone-pair combination.

Verified against a user's SA-5 CASSCF$(14e,10o)$ on o-nitrophenol run before any
of this: exactly two labels change, both the intended ones, every pi and pi\*
left alone. The space then reads 5pi + 2n + 3pi\*, and the corresponding
$(12e,9o)$ reads 4pi + 2n + 3pi\*, which is the assignment its S1 and S2 n->pi\*
states require.

---

## 9. The refinement tier

Everything above is decided **a priori**. The refinement is the opposite trade:
it runs the CASSCF and corrects the estimate against what actually happened. It
is offered after the quick answer and runs only on approval.

### 9.1 What a converged CASSCF sees that an estimate cannot

Orbitals rotate during optimisation. A space correct at the starting guess need
not remain so [21], and a CASCI cannot detect this because it holds the orbitals
frozen by construction. Only a converged CASSCF can report that the pi/pi\* pair
placed in the space has been displaced by sigma.

It also measures, rather than estimates, which orbitals carry correlation: the
state-averaged natural occupations are the direct form of the criterion APC
approximates [19,20].

### 9.2 The loop, and why its order is what it is

1. **Solve.** SA-CASSCF over the roots the source job recorded, with the spin
   constraint of 6.3, solving for $k + 3$ roots rather than exactly $k$.
2. **Character audit.** The total pi and lone-pair target weight the active
   subspace holds, before and after optimisation, as a subspace trace.
3. **State audit.** Are the predicted states among the roots, by compatibility?
4. **Correct.** A missing state with character lost triggers a **re-seed**: keep
   the converged orbitals, drop those no longer carrying the character they were
   chosen for, rotate the projected ones back into their place. A missing state
   with character intact triggers **augmentation**.
5. **Prune.** Only once states are stable: drop orbitals whose state-averaged
   natural occupation lies outside $[0.02, 1.98]$, averaged over every requested
   root and never the ground state alone.
6. **Re-verify.** Re-solve, confirm the states survived with their character and
   that no requested excitation energy moved by more than 0.2 eV. Any failure
   restores the last good space.

**The ordering is the whole point.** Character leaving an active space has two
meanings requiring opposite responses: with a state missing the space lost
something it needed; with every state present the optimisation has handed back
orbitals those states do not use, which argues for pruning. The state audit
decides; the character measure is the diagnostic.

The margin of three extra roots exists because a linear-response pass and a
CASSCF do not order states the same way. Without it, a state appearing at root 3
of a three-root average is reported missing forever. The result records which
root each predicted state landed on.

### 9.3 The trap this is built around

Pruning by natural occupation without first asking whether the requested states
are present throws away orbitals that are not inert at all. On uracil at four
roots a carbonyl lone pair sits at 1.981, an occupation cut takes it, and the
n->pi\* state built on it goes with it, while the occupations appear to have
proved it was never used.

A caution on the numbers. An earlier draft of this document claimed both lone
pairs relax to about 2.00 and that adding roots does not rescue them. Both were
measured while the state average was running over triplets as well as singlets
(6.3). Confined to singlets they are visibly correlated and their occupations
*fall* as roots are added, [1.981, 1.954] at four roots and [1.976, 1.936] at
six, so at six neither is outside the inert window. More roots do protect them.
The ordering constraint survives at four roots, which is what the test pins.

### 9.4 Where to start, and what it costs

Measured on four molecules, all three tiers each: **maximal is the wrong
answer**, and decisively. For three of the four it is unreachable by six to
thirteen orders of magnitude, so asking for it merely falls back. On the one
where it can be run it took 197 s against 0.5 s, failed to converge, and pruned
nothing: in a large space the correlation spreads thinly and no orbital reaches
the inert threshold. **Minimal is not wrong so much as inert**, converging in
one cycle because there is nothing to do. The default is **recommended**, which
can shrink on evidence where minimal cannot grow without a missing state.

The budget is spent against $N_{\text{CSF}} \times n_{\text{roots}}$, not the
CSF count alone, because a state average over $R$ roots solves $R$ CI problems
per macro-iteration. o-Nitrophenol's narrowing gives 496,860 CSFs, which passes
a flat $10^6$ test comfortably, but 3.97M root-CSFs over eight roots, and one
cycle took two hours. Uracil at 41,405 CSFs over six roots is 248k and runs a
cycle in minutes.

A ground-state prune is guarded twice: an absolute 5 mHartree rise, and a
scale-free cap on the **fraction of correlation lost**. The absolute test does
not scale, so a cut costing 4 mHartree out of 20 mHartree of correlation would
pass it while destroying a fifth of what the space was for.

### 9.5 Narrowing: counting atoms, not orbitals

A recommendation admits every lone-pair-derived orbital in the molecule, six for
uracil and six for o-nitrophenol, because it cannot know which a state will use.
Once the states have been asked for that is knowable, and carrying four lone
pairs no state touches dilutes the state average the missing state has to be
found in.

The first rule tried was "the whole pi system, plus every pool orbital
projecting more than 0.30 onto a state's hole". On o-nitrophenol five of six
lone pairs clear that threshold and the space stays at $(22e,15o)$, against the
$(12e,9o)$ a chemist uses. Two replacements were measured and both failed, in
ways worth recording because neither is obvious.

**Coverage of the hole does not work.** An n->pi\* hole expressed in the
projector's eigenbasis smears across most of the lone-pair block: uracil's needs
*four* of its six orbitals to reach 90% coverage, though the chemistry is two
carbonyl lone pairs. The projector's eigenbasis is not the chemist's basis and
no coverage threshold reconciles them.

**Growing while the budget allows does not work either**, and fails backwards:
adding an occupied orbital to a nearly-full space *reduces* the CSF count,
$(24e,15o)$ being 63,700 CSFs where $(22e,15o)$ is 496,860, so a greedy fill
exploits the combinatorics rather than choosing chemistry and returns a space
larger than it started from.

What works is counting **atoms**. Project each predicted n->pi\* hole onto the
atoms, keep the heteroatoms carrying at least 10% of it, expand that set to
chemically equivalent partners, and admit two lone-pair orbitals per predicted
state spread across those centres. The pi system stays whole, because the
completion rule of 4.4 applies here too.

Two details are load-bearing. **Equivalence** is required by the data: TDA puts
76% of uracil's S1 hole on *one* carbonyl oxygen, so counting atoms alone gives
a single lone pair, and a single lone pair is known not to work for uracil. Two
heteroatoms count as equivalent when they are the same element with the same
multiset of neighbour elements, which pairs the two carbonyl oxygens of uracil
and the two oxygens of a nitro or carboxylate group.

**Allocating per state rather than per atom** is what makes formaldehyde and
uracil agree, and they pull in opposite directions:

| | one per centre | all of each centre | **two per state** |
|---|---|---|---|
| formaldehyde, literature (6,4) | (4,3) | **(6,4)** | **(6,4)** |
| uracil, literature (14,10) | **(14,10)** | (18,12) | **(14,10)** |

Formaldehyde's literature space is two lone pairs on one oxygen; uracil's is one
on each of two. Same count, different arrangement, so a per-state budget of two
reproduces both where either per-atom rule reproduces one and breaks the other.

Narrowing runs whenever states were requested and it strictly shrinks the space,
not only when nothing fits the budget. Uracil's tier *does* fit, so it never
reached the trim, and the trim is the difference between 248,430 root-CSFs and
29,700, and between exceeding a ten-minute cap and converging in 154 s.

### 9.6 What it returns

A refined $(N, n)$ is not reproducible on its own, so the result carries an
ordered **rotation trail**: every narrow, re-seed, augment and prune, with the
orbital and the occupation or character that justified it.

**Every orbital index in the trail and in the reported table is 1-based and
refers to the natural-orbital set**, not to the restart orbitals. Two moldens
with different orderings and no stated convention is precisely the trap the
next paragraph warns about, so the convention is stated here rather than
inferred. Plus the converged
orbitals as a molden, a second molden in the natural-orbital basis that the
reported occupations and characters actually describe, and a regenerated
`active_space_spec.json`. The two orbital sets span the same space and are not
the same orbitals, so reading the reported table against the wrong file gives
the wrong answer.

---

## 10. Results

Seventeen molecules, cc-pVDZ unless stated, against QUEST [12,13] and Thiel
[14] reference data. Two molecules carry no literature space: methane, and
o-nitrophenol, which has no QUEST entry and no settled space and is therefore
scored on state character and convergence only.

**Every CASSCF figure below was re-measured after the multiplicity fault of
6.3.** Numbers reported before that fix matched singlet reference states against
roots that were partly triplets and are withdrawn. The state-identification
figure in 10.3 was never affected, TDA being singlet-only by construction.

### 10.1 The recommended space against the literature

**9 of 15 molecules with a literature space are matched exactly by the
recommended tier, and 10 of 15 counting the two other tiers on offer** (pyrrole
matches as its minimal tier). The previous engine matches **1 of 15**, and
refuses every open-shell molecule outright.

**Those two counts are for a ground-state request, and they still stand for
one.** They come from `run_bench.py --set spaces`, which asks for no excited
states, so nothing in it can exercise a rule that reads the requested states.

**For a user who asks about excited states, which is what a `cas_reco` job
usually is, the count is now 12 of 15**, measured by `--set narrowed` over the
same fifteen molecules through the production runner at its own choice of
analysis basis. The three that changed are uracil, pyrrole and furan, and all
three changed for the same reason: the narrowing of 9.5 is a priori, it was
reachable only from the refinement loop, and calling it from the quick path
turns two tier-only matches into exact ones and takes uracil from $(22e,14o)$
to its literature $(14e,10o)$.

| | ground-state request | states requested |
|---|---|---|
| exact, recommended tier | 9 / 15 | **12 / 15** |
| counting every offered tier | 10 / 15 | **12 / 15** |

The inclusive count rises less than the exact one, and that is the point rather
than a disappointment: pyrrole and furan were already reachable if a user read
all three sizes and picked the right one. What changed is that they are now the
answer rather than an alternative the user had to know to look for.

Still not matched: acrolein, formamide and *p*-benzoquinone, which are the
three 11.3 already names and none of which is a lone-pair surplus.

**Acrolein is formamide's situation, not a defect.** Checked orbital by
orbital, the recommended $(8e,6o)$ is two oxygen lone pairs, two pi and two
pi\*, and the interesting part is that three numbers disagree rather than two.
The reference's own description, "the four pi orbitals plus the oxygen lone
pair and the carbonyl pi system", names **five** orbitals holding six
electrons. Its recorded count is $(8e,7o)$, which is four occupied and three
virtual. The engine returns four occupied and two virtual.

So the engine reproduces the recorded **electron** count exactly and is one
**virtual** short, and that virtual cannot be a pi\*: acrolein conjugates four
p orbitals across C=C-C=O, giving four pi molecular orbitals of which exactly
two are antibonding. A seventh orbital has to be a sigma\* the description does
not mention, which is word for word what 10.6 concluded about formamide's two
extra virtuals. Making either molecule "match" means adding orbitals its own
reference never names.

That leaves *p*-benzoquinone as the only one of the three whose gap is not
accounted for.

The two numbers are given separately because they answer different questions. A
user who accepts the default gets the first; a user who reads all three sizes
gets the second. Quoting only the larger one would be the misleading choice.

Matched: water $(8e,6o)$, ethylene $(2e,2o)$, butadiene $(4e,4o)$, benzene
$(6e,6o)$, formaldehyde $(6e,4o)$, acetone $(6e,4o)$, pyridine $(8e,7o)$,
pyrrole $(6e,5o)$ as a tier, N2 $(10e,8o)$, O2 $(12e,8o)$.

Not matched: acrolein, formamide, furan as a tier only, and *p*-benzoquinone.

**Uracil moved out of this list**, and the change is in what the quick tier is
allowed to do rather than in the selection. Its quick answer was $(22e,14o)$
against a literature $(14e,10o)$, because it retained all six
lone-pair-derived orbitals when the three requested states use two of them, and
only the refinement resolved it. The narrowing of 9.5 needs no CASSCF, only the
geometry, the projection and the linear-response analysis, all of which the
quick path already holds by the time it reports; it was written inside the
refinement loop and was therefore reachable only from there. Called from the
quick path it returns $(14e,10o)$ directly, at 4,950 CSFs against 41,405, and
pyrrole's $(6e,5o)$ likewise stops being a tier the user has to notice and
becomes the recommendation.

The narrowed space is offered as a fourth tier and the projector's own pool
keeps its name, so nothing is withdrawn: a user who wants the space chosen on
ground-state chemistry alone can still read it. Formaldehyde, whose space is
already right, does not move, and a ground-state-only request narrows nothing,
there being no states to narrow against.

### 10.2 Invariance

| | changes with the basis | changes under rotation |
|---|---|---|
| **This work** | **0 / 15** | **0 / 15** |
| Previous engine | 2 / 15 | 0 / 15 |

Five basis sets (STO-3G, def2-SVP, cc-pVDZ, def2-TZVP, aug-cc-pVDZ) and five
random rotations per molecule. This is the property 4.1 is constructed to give
and the one AVAS as published does not have.

### 10.3 State identification

**24 of 24 reference states located, mean absolute error 0.27 eV** against QUEST
best estimates, with every located state's character matching the reference
label. This is the TDA/CAM-B3LYP pass of 6.1, not a CASSCF result.

### 10.4 End to end: SA-CASSCF then SC-NEVPT2 [18] in the recommended space

**SC-NEVPT2 MAE 0.32 eV over the 16 states whose CASSCF converged**, 0.55 eV if
the two non-converged molecules (*p*-benzoquinone, uracil) are included.

| Character | n | SC-NEVPT2 MAE |
|---|---|---|
| n->pi\* | 5 | **0.24 eV** |
| pi->pi\* | 10 | 0.38 eV |
| **all converged** | **16** | **0.32 eV** |

**The largest deviation in the whole set is +0.48 eV** (ethylene's pi->pi\*),
then pyridine +0.47, pyrrole +0.43, acrolein -0.41, furan +0.40. That flat tail
is the result worth reading, not the mean.

This replaces an earlier figure of 0.29 eV that was not valid. That number
looked better and concealed outliers of ±3 eV which came and went depending on
which triplet root a mislabelled character happened to match. **A tighter
distribution with a worse headline is the better result**, and the headline
moved because the measurement was wrong, not because the method changed.

The V-state difficulty is not solved by any of this: an ionic pi->pi\* is hard
for a small valence pi space in a double-zeta basis [16]. What changed is that
these states are located at all, and that the number attached to them is
reproducible.

### 10.5 Against the published bar

The best fully automatic scheme in the ASF assessment [11] reports **0.49 eV**
over 32 molecules in def2-TZVPD. The 0.32 eV here is **not like for like**: a
different and smaller molecule set, a smaller basis, and a different downstream
method. It establishes that this is in the right range, not that it is better.
That assessment's more useful finding is that every scheme it tested returned
25-30% unsatisfactory results in fully automatic mode, which is the honest
baseline expectation for this class of method.

### 10.6 The refinement tier

Seventeen molecules with a ten-minute cap. **15 of 17 finish inside it, and 11
of the 14 that finished and have a literature space land on it exactly.** Median
refinement 2 s against a median recommendation of 0.14 s.

| Molecule | literature | quick | refined | |
|---|---|---|---|---|
| uracil | (14,10) | (22,14) | **(14,10)** | narrow |
| pyrrole | (6,5) | (8,6) | **(6,5)** | narrow |
| furan | (6,5) | (8,6) | **(6,5)** | narrow |
| acetone, formaldehyde | (6,4) | (6,4) | **(6,4)** | unchanged |
| benzene, butadiene, ethylene, pyridine, N2, O2 | | | **match** | unchanged |
| acrolein | (8,7) | (8,6) | (8,6) | one orbital short |
| formamide | (8,7) | (10,6) | (8,5) | see below |
| water | (8,6) | (8,6) | (4,4) | ground-state only |
| o-nitrophenol, *p*-benzoquinone | | | not reached | past the cap |

**Every predicted state is now found in every molecule that finished.** Before
the spin constraint of 6.3, pyridine found neither of its two predicted states
and several others found some but not all. A refinement that cannot see the
states it is protecting is not doing the job 9.2 describes, so this matters more
than any change in space size.

**Uracil is the case that changed most**, from exceeding the cap entirely to
$(14e,10o)$, exactly the literature space, converging in 154 s.

**Formamide's gap is in the reference, not in the space.** Its reference is
recorded as $(8e,7o)$ and described as "the amide pi system plus the oxygen lone
pairs", but that description names *five* orbitals: N-C=O gives three pi MOs of
which only one is virtual, plus two oxygen lone pairs, holding eight electrons.
The refinement returns $(8e,5o)$ and, checked orbital by orbital, keeps exactly
those: both retained lone pairs sit on the oxygen, with 0.69 and 0.96 of their
population there, and the nitrogen lone pair is dropped. The two extra orbitals
in the recorded space are virtuals the description does not name, and an amide pi
system has no second pi\* to offer. Making this molecule "match" would mean
adding sigma\* orbitals the reference never describes.

**Water is a legitimate reduction, and this can be said with a number.** Its
$(8e,6o) \to (4e,4o)$ drops two orbitals at natural occupations of 1.9994 and
1.9990, costs 1.887 mHartree, and retains **96.4% of the correlation energy the
full space captured**. The conventional $(8e,6o)$ is the full valence space by
convention, not a claim that those lone pairs carry ground-state correlation.

**The guard is doing work.** N2 is the case that shows it: an unguarded prune
took $(8e,7o)$ to $(4e,4o)$, dropping the sigma framework a triple bond needs,
and the ground-state check rejects that cut at a cost of 51 mHartree, 1.39 eV
and 38% of the correlation energy.

### 10.7 The handoff between bases

Pyrrole's $(8e,6o)$, recommended in def2-SVP, handed to a calculation in another
basis:

| Handoff into | by MO index (principal cosine) | by projection | by specification |
|---|---|---|---|
| cc-pVDZ | 0.999 | pi weight 4.972 preserved | **(8,6)** |
| def2-TZVP | 0.989 | not measured | **(8,6)** |
| aug-cc-pVDZ | **0.000** | pi weight 4.972 preserved | **(8,6)** |

A naive **index** handoff fails completely into aug-cc-pVDZ, because diffuse
functions reshuffle the virtual manifold and the same indices name an orthogonal
set of orbitals. Since a diffuse basis is exactly what a user moves to when
Rydberg states matter, this is not an edge case.

The application does not perform an index handoff. It projects the coefficients
themselves, and that path preserves the pi subspace weight at 4.972 into every
basis tested, so the operative handoff is sound. The portable specification
reproduces the space independently of any orbital file.

### 10.8 Cost

| Stage | Cost |
|---|---|
| SCF reference | ~0.2 s (def2-SVP, 10 heavy atoms) |
| Perception + projection | milliseconds |
| APC ranking | ~0.1 s |
| **Whole ground-state recommendation** | **0.14 s median, 0.82 s max** |
| TDA, 8 roots, pyrrole | 3 s (def2-SVP), 21 s (def2-TZVP) |
| Verification CASCI | seconds, skipped above 5x10^5 CSFs |
| **Refinement tier** | **2 s median, 154 s for uracil** |

---

## 11. Strengths, and where this falls short

### 11.1 What is established

- **Rotation invariance**, by construction and confirmed over five random
  rotations of fifteen molecules. This is the property AVAS as published lacks.
- **Basis independence** of the selected space, measured over five basis sets
  from STO-3G to aug-cc-pVDZ, with the single stated exception of Rydberg
  detection, which is a statement about the basis rather than the method.
- **No orbital ceiling.** Cost is reported rather than used to refuse.
- **Open-shell support**, where the previous engine declined outright.
- **State-specific selection**, with 24 of 24 reference states located and
  characters matching.
- **Speed**: 0.14 s median for a full ground-state recommendation, three to five
  orders of magnitude cheaper than a DMRG-based selector.
- **Reproducible handoff** between bases through a portable specification.

### 11.2 What is not established

- **A larger and more diverse benchmark.** Seventeen molecules, all organic,
  mostly small and mostly planar. No transition metals have been tested at all,
  though the target machinery emits a $d$-shell target for them. Bond-breaking
  and diradical cases are absent apart from O2.
- **The 0.32 eV figure against the 0.49 eV bar** is not like for like (10.5).
- **The Rydberg augmentation path** is structurally implemented but has been
  exercised on valence states only. The reason given here used to be that no
  benchmark molecule has a Rydberg reference below its valence pi->pi\*, and
  that is **false**: `scripts/casbench/reference_data.py` records pyrrole with a
  pi->Rydberg 3s at 5.24 eV against a valence pi->pi\* at 6.33, and furan at
  6.00 against 6.37. Both have qualified all along. What actually kept the path
  unexercised is that the refinement and NEVPT2 sets run in cc-pVDZ, which
  cannot represent a Rydberg state, so those references were invisible to the
  measurement rather than absent from it.
- **Two thresholds rest on two molecules**: the 0.50 lone-pair-over-sigma
  preference and the 0.25 ambiguity band of 8.2. They are stated rather than
  fitted, but the evidence under them is thin.
- **The n/sigma band is untested off planar carbonyls.** The 8.2 rule was set
  on uracil and o-nitrophenol, both planar with carbonyl or nitro oxygens. A
  thiol, or an amine with a pyramidal nitrogen, would exercise it differently
  and has not been tried.
- **BAGEL and ORCA receive counts only.** The orbital identity transfers to
  PySCF; the molden-to-ORCA route was never validated and is not claimed.

### 11.3 Where it falls short

- **Ground-state-only requests have the least evidence.** With no excited state
  to protect, occupations and the ground-state energy are all the refinement
  has. Water's reduction is defensible (10.6), but the mechanism that makes the
  excited-state case safe, the state audit, is simply unavailable here.
- **Two molecules exceed the ten-minute refinement cap**, o-nitrophenol and
  *p*-benzoquinone, and they are the kind most likely to be asked about. The
  causes are deliberate: a root-aware budget and a singlet-only average both
  cost time.
- **Acrolein lands one orbital short** of its $(8e,7o)$.
- **Ionic pi->pi\* states remain the worst-described**, which is a limitation of
  a small valence pi space in a double-zeta basis [16] rather than of the
  selection, but it bounds what the method can deliver end to end.
- **The entropy carries little information here** (5.1). Because the projector
  has already selected on chemical grounds, the APC profile inside the pool is
  flat, so the ranking mostly orders rather than selects. A method that spent
  more on the entropy would have more to work with.
- **Delocalised systems have no natural target set.** The reference directions
  assume chemistry describable as pi normals, lone pairs and bond axes.

### 11.4 The measurement floor

Repeat runs of the same molecule differ. Three identical repeats of acrolein's
SA-CASSCF, same code, geometry and basis:

| | trial 1 | trial 2 | trial 3 |
|---|---|---|---|
| $E_0$ (Hartree) | -190.82451658 | -190.82452598 | -190.82442026 |
| root 5 (eV) | 6.457 | 6.446 | 6.740 |
| converged | no | yes | yes |

The root nearest acrolein's 6.68 eV reference moves **0.29 eV** between
identical runs, enough to change which root a reference matches and therefore to
move an aggregate mean. This was found while investigating an apparent
regression that turned out to be apparatus noise.

**That floor has since been measured properly and removed. It was a property of
the convergence settings, not of CASSCF.** `scripts/casbench/repeat_scatter.py`
runs the same calculation five times and records the character of every root
alongside its energy, which is what the table above was missing and what makes
the number interpretable: the ground-state energy moves 0.003 eV there while
root 5 moves 0.29 eV, and a hundredfold difference between the two is not one
state's energy wobbling.

At the harness settings, `conv_tol` 1e-8 with a 1e-5 gradient over 100
macro-iterations, acrolein reproduces **exactly**: 0.001 meV on the ground
state, 0.000 eV on every root, identical characters, converged 5 times out of
5. At the settings the refinement tier actually shipped, 1e-6 with no gradient
tolerance at all, the same molecule moves 36 meV on the ground state and
0.459 eV on root 5, and **two roots change character between identical runs**.
PySCF reports `converged = True` on all five of those. So convergence at 1e-6
is not evidence of reproducibility, and since the refinement loop branches on
root characters, this changed which correction it applied.

The mechanism is reduction order in the threaded linear algebra: the identical
loose protocol pinned to one BLAS thread reproduces exactly, at three times the
wall clock. A loose tolerance is what lets that perturbation survive into the
answer. The refinement now uses the harness settings.

**What that costs depends on the size of the system, and the acrolein number
alone would misrepresent it.** On acrolein it is not measurable: 4.1 s mean at
the tight tolerances against 3.3 s median at the loose ones, on the same eight
threads. On uracil it is real. That refinement is recorded at 154 s in 10.6 and
now takes 282 s on the run that converges, and 926 s and 974 s on the two that
do not, since missing the criterion inside 100 macro-iterations also buys a
second attempt through the second-order solver. Both numbers belong in any
statement of the cost: no measurable price on a small system, roughly double on
a larger one that converges, and several times more on one that does not.

**Tightness is not monotone**, which is worth stating because the obvious next
move is wrong. At `conv_tol` 1e-10 acrolein converges 0 times out of 5 and the
entire scatter returns, 35.9 meV and 0.459 eV with the same two characters
moving. A criterion the optimiser cannot reach leaves it stopping at an
arbitrary point in a shallow region exactly as one it reaches too early does.
1e-8 is the setting because it is reachable.

**The refinement tier reproduces now, and this is the case that shows it.** The
previous tracker recorded uracil returning $(14e,9o)$, $(14e,10o)$ and
$(14e,9o)$ by a different route across three runs of identical setup, and
cautioned that whatever a single benchmark row says for that molecule is one
sample rather than a settled answer. Three identical repeats at the new
tolerances return $(14e,10o)$ every time, with the same rotation trail, the
same orbital labels, the same root characters, and excitation energies agreeing
to 0.6 meV. The caution can be retired: the sample was unstable because the
solver was, not because the molecule is ambiguous.

What remains, and is reported rather than fixed: uracil's convergence flag and
its cost do not settle, at 282 s converged against 926 s and 974 s unconverged
for identical runs, 1 of 3. The answer is reproducible; the path to it is not,
and that molecule sits at the edge of the 100 macro-iteration budget. Raising
the budget is the obvious move and is not free, so it wants measuring rather
than assuming.

The harness also names any molecule that did not converge and prints a
converged-rows-only mean beside the headline.

### 11.5 Verdict on the previous engine

| | this work | previous |
|---|---|---|
| Literature space matched, recommended tier | **9 / 15** | 1 / 15 |
| Literature space matched, any offered tier | **10 / 15** | 1 / 15 |
| Space changes with the basis | **0 / 15** | 2 / 15 |
| Open-shell molecules | **supported** | refused |
| Orbital ceiling | **none** | 12 |
| States identified by character | **24 / 24** | not attempted |
| Cost | **0.14 s median** | FCI or DMRG pilot, then a full SA-CASSCF |

There is no axis on which the previous engine is ahead. It is retained under
`scripts/casbench/` so the comparison stays runnable, and is not reachable from
the application.

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
family; reports a best mean absolute error of 0.49 eV for l-ASF(QRO) over 32
molecules in def2-TZVPD, and 25-30% unsatisfactory results for every scheme in
fully automatic mode. *Preprint, not peer reviewed at the time of writing.*

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

[16] C. Angeli, "On the nature of the pi->pi\* ionic excited states: the V state
of ethene as a prototype", *J. Comput. Chem.* **2009**, *30*, 1319-1333.

[17] Q. Sun, X. Zhang, S. Banerjee *et al.*, "Recent developments in the PySCF
program package", *J. Chem. Phys.* **2020**, *153*, 024109.
DOI: 10.1063/5.0006074.

[18] C. Angeli, R. Cimiraglia, S. Evangelisti, T. Leininger and J.-P. Malrieu,
"Introduction of n-electron valence states for multireference perturbation
theory", *J. Chem. Phys.* **2001**, *114*, 10252-10264. DOI: 10.1063/1.1361246.

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
*Int. J. Quantum Chem.* **2011**, *111*, 3267-3272. On why an active space
correct at the starting guess need not remain so under orbital optimisation,
which is the rotation problem section 9.1 measures.

[22] B. O. Roos, P. R. Taylor and P. E. M. Siegbahn, "A complete active space
SCF method (CASSCF) using a density matrix formulated super-CI approach",
*Chem. Phys.* **1980**, *48*, 157-173. DOI: 10.1016/0301-0104(80)80045-0.

[23] J. Paldus, "Group theoretical approach to the configuration interaction and
perturbation theory calculations for atomic and molecular systems",
*J. Chem. Phys.* **1974**, *61*, 5321-5330. The unitary-group formulation from
which the Weyl-Paldus dimension formula of section 7 follows.

[24] K. K. Docken and J. Hinze, "LiH Potential Curves and Wavefunctions for
X1Sigma+, A1Sigma+, B1Pi, 3Sigma+, and 3Pi", *J. Chem. Phys.* **1972**, *57*,
4928-4936. The origin of the state-averaged MCSCF procedure section 9.2 uses.

[25] P.-O. Löwdin, "Quantum Theory of Many-Particle Systems. I. Physical
Interpretations by Means of Density Matrices, Natural Spin-Orbitals, and
Convergence Problems in the Method of Configurational Interaction",
*Phys. Rev.* **1955**, *97*, 1474-1489. DOI: 10.1103/PhysRev.97.1474. Natural
orbitals and their occupations, the basis in which section 9 reports.

[26] R. S. Mulliken, "Electronic Population Analysis on LCAO-MO Molecular Wave
Functions. I", *J. Chem. Phys.* **1955**, *23*, 1833-1840.
DOI: 10.1063/1.1740588. The population analysis used to localise a hole on
atoms in section 9.5 and to label orbitals in section 8.3.

[27] S. Hirata and M. Head-Gordon, "Time-dependent density functional theory
within the Tamm-Dancoff approximation", *Chem. Phys. Lett.* **1999**, *314*,
291-299. DOI: 10.1016/S0009-2614(99)01149-5. The linear-response pass of
section 6.1.

[28] G. Knizia, "Intrinsic Atomic Orbitals: An Unbiased Bridge between Quantum
Theory and Chemical Concepts", *J. Chem. Theory Comput.* **2013**, *9*,
4834-4843. DOI: 10.1021/ct400687b. On minimal-basis references as a bridge to
chemical concepts, the same idea the `minao` reference set of section 4 rests
on.

[29] M. R. Hermes, "csf_fci: a spin-adapted configuration-state-function CI
solver", distributed with the `mrh` package (github.com/MatthewRHermes/mrh) and
usable from PySCF [17]. The spin-adaptation route used in section 6.3. See also
[23] for the unitary-group formulation CSF-based solvers rest on.
