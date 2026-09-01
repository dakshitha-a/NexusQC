<div align="center">

# NexusQC

### Agentic Quantum Chemistry Engine

**Describe a calculation in plain English. Get real numbers from a real quantum chemistry program.**

[![License: MIT](https://img.shields.io/badge/License-MIT-6e8cff.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)
[![Node 24](https://img.shields.io/badge/Node-24-339933.svg?logo=nodedotjs&logoColor=white)](https://nodejs.org)
[![Engines: PySCF · ORCA · BAGEL](https://img.shields.io/badge/Engines-PySCF%20%C2%B7%20ORCA%20%C2%B7%20BAGEL-34c7a0.svg)](#what-you-can-ask-for)
[![Runs locally](https://img.shields.io/badge/LLM-runs%20locally-e8a33d.svg)](#install)

<img src="docs/screenshot.png" alt="NexusQC: a chat conversation, a pending job approval card showing the generated input file, the 3D molecule viewer, and the job manager" width="900">

</div>

---

Name a molecule, say what you want to know, and NexusQC resolves the structure,
writes a proper input file for whichever program actually supports the method,
runs it in the background, and reports numbers parsed from that program's own
output. Not numbers a language model produced because they looked plausible.

Everything runs on your own hardware. The model is local, served through
[Ollama](https://ollama.com), and so are the engines:
[PySCF](https://pyscf.org), [ORCA](https://www.faccts.de/orca/) and
[BAGEL](https://nubakery.org).

Three things separate this from a chatbot with a calculator bolted on.

**Nothing runs without your approval.** Every job pauses on a real graph
interrupt and shows you the exact input file first. That's structural, not a
line in a prompt, so it holds even when the model never thinks to ask. The card
comes up as soon as the setup is complete, and whichever button you press is
answered straight away rather than after another round trip to the model. Ask
to see an input without running it and it stops short of the card.

**It asks instead of guessing.** Missing a basis set or an active space? You
get a specific question back rather than a silently chosen default that
quietly produces the wrong physics.

**Failures get diagnosed, but only when you ask.** A failed job says so and
changes nothing on its own. Press *Troubleshoot* and the agent reads the
engine's actual output, checks the manual, searches the web if it has to, and
explains what went wrong. Any corrected job it proposes still goes through the
approval gate, because guessing at a fix can burn hours of compute you never
agreed to.

---

## What you can ask for

Ask in whatever words you'd use with a colleague. The table is what those words
resolve to, read directly from the app's capability registry.

**Columns are in routing order.** If you don't name a program, the leftmost one
in that row that supports your request is what runs.

| What you ask for | PySCF | ORCA | BAGEL |
|---|---|---|---|
| **Energies and properties** | | | |
| Ground-state energy | every method | every method | every method |
| Excited-state energies | HF, DFT, EOM-CCSD, CASSCF, NEVPT2, MC-PDFT, L-PDFT, CMS-PDFT | HF, DFT, EOM-CCSD, CASSCF | CASSCF, CASPT2 |
| Energy gradient | HF, DFT, MP2, CCSD, CASSCF, MC-PDFT, L-PDFT, CMS-PDFT | HF, DFT, MP2, CASSCF | every method |
| Non-adiabatic coupling | CASSCF, MC-PDFT, L-PDFT, CMS-PDFT | HF, DFT | CASSCF, CASPT2 |
| **Structure** | | | |
| Geometry optimization | HF, DFT, MP2, CCSD, CASSCF, MC-PDFT, L-PDFT, CMS-PDFT | HF, DFT, MP2, CASSCF | every method |
| Constrained optimization | HF, DFT, MP2, CCSD, CASSCF, MC-PDFT, L-PDFT, CMS-PDFT | HF, DFT, MP2, CASSCF | - |
| Conical intersection | - | HF, DFT | CASSCF, CASPT2 |
| Transition state, by NEB | - | HF, DFT, MP2, CASSCF | - |
| **Vibrations** | | | |
| Frequencies | HF, DFT, CASSCF, MC-PDFT, L-PDFT, CMS-PDFT | HF, DFT, MP2, CASSCF | every method |
| Optimize, then frequencies | HF, DFT, CASSCF, MC-PDFT, L-PDFT, CMS-PDFT | HF, DFT, MP2, CASSCF | every method |
| **Scans, paths and ensembles** | | | |
| Scan a bond, angle or dihedral | every method | every method | - |
| Interpolate between two geometries | every method | every method | every method |
| Excited states at every point of a scan or path | HF, DFT, EOM-CCSD, CASSCF, NEVPT2, MC-PDFT, L-PDFT, CMS-PDFT | HF, DFT, EOM-CCSD, CASSCF | CASSCF, CASPT2 |
| Nuclear-ensemble UV/Vis spectrum | HF, DFT, CMS-PDFT | HF, DFT, EOM-CCSD, CASSCF | CASSCF, CASPT2 |
| Run the same job over a set of structures | every method | every method | every method |
| **Active space** | | | |
| Recommend one, autoCAS-style | CASSCF | - | - |
| Build one from valence character (AVAS) | CASSCF | - | - |
| Name the orbitals in it yourself | CASSCF, NEVPT2, MC-PDFT, L-PDFT, CMS-PDFT | - | CASSCF, CASPT2 |
| **Escape hatch** | | | |
| Run your own input file, verbatim | - | every method | every method |

*Every method* means every one that program offers here: for PySCF, HF, DFT,
MP2, CCSD, EOM-CCSD, CASSCF, NEVPT2, MC-PDFT, L-PDFT and CMS-PDFT; for ORCA,
the same list without the last four; for BAGEL, HF, CASSCF and CASPT2. The per-method
evidence behind every cell, down to which ones were executed here versus taken
from a manual, is in [QM_CAPABILITIES.md](docs/QM_CAPABILITIES.md).

A few things the table can't show. TDDFT, TDA-DFT, CIS and TD-HF are all the
excited-state row at HF or DFT with one flag toggled, not separate calculations
to choose between. Two requests override routing order regardless of what you
asked for. CASPT2 always goes to BAGEL, since it is the only one of the three
that has it here. A CASSCF job that needs oscillator strengths also goes to
BAGEL, which is the preferred engine for those on this deployment; ORCA
computes them too and is used if you name it, and PySCF cannot report an
intensity for a CASSCF state at all.

NEVPT2, MC-PDFT, L-PDFT and CMS-PDFT are PySCF only, and they all build on a
CASSCF wave function, so each needs an active space stated the way CASSCF does.
The three pair-density ones also need an on-top functional, which is a
different thing from a Kohn-Sham one: tPBE and ftPBE rather than B3LYP or PBE0.

Two things about them are worth knowing before you ask. NEVPT2 gives energies
and nothing else, because PySCF has no NEVPT2 gradient: there is no optimizing
or frequency-taking at that level, only energies at a geometry you already
have. And of the four, **only CMS-PDFT gives you transition intensities**, so
it is the one to pick if you want a UV/Vis spectrum from a multireference
calculation rather than only a list of excitation energies. L-PDFT is the
better multi-state method in every other respect and is the one to prefer when
you do not need intensities.

Excited states from **every** multireference method here mean states of the
same multiplicity as the ground state, the same convention TDDFT already
follows: a closed-shell molecule gets singlets. That is worth stating because
it was not always true. Until 2026-08-29 a state-averaged CASSCF on PySCF
returned the lowest states of any multiplicity, so what was labelled S1 could
be a triplet. ORCA and BAGEL never had the problem, and a single-state
calculation was never affected.

Orbital visualisation isn't in the table because it isn't a calculation. Every completed job already has
its orbitals in its own drawer.

Ask for something none of the three can do, a Gaussian or Psi4 calculation say,
and you'll get the input file written out in chat along with a plain statement
that it can't be run here.

### Building on work you've already done

Any job built on a CASSCF wave function, which is CASSCF, CASPT2, NEVPT2,
MC-PDFT, L-PDFT and CMS-PDFT, can start from a previous one's converged orbitals
instead of a fresh guess. Tag the source job and the new one restarts from it.
Same engine only, since orbital files don't convert between programs. On PySCF
this can cut macro-iterations noticeably when the two geometries are close; ORCA
and BAGEL use their own restart mechanisms, `MOREAD` and `load_ref`.

A new job can also run on a **previous job's geometry** rather than whatever is
in the molecule panel. "Run that again with a bigger basis" works, and so does
"same geometry as job X". The agent already has the job id from the
conversation, so it never asks you for one. It takes the optimized geometry if
the job produced one, otherwise the input geometry. A job with no single
geometry of its own, like a scan or a Wigner ensemble, is refused by name rather
than guessed at.

A **nuclear-ensemble spectrum** always builds on earlier work, because there is
nothing to sample without a molecule's vibrations: it draws its geometries from
a finished frequency calculation's normal modes. Tag that job and ask for the
spectrum. If you haven't run one, say so and the agent will set the frequency
calculation up first, then sample the ensemble from it once it lands.

For the CASSCF-based methods, every sample also starts from that same frequency job's
converged orbitals rather than from its own fresh guess. Besides saving the
work, it is what keeps the active space the same one from sample to sample, so
the pooled spectrum is a single space sampled many times instead of a mixture
of whatever each geometry happened to converge to. You will see it filled in on
the approval card and can point it at a different job or take it out. If the
frequency job cannot supply orbitals, because it ran at DFT or on another
program, the ensemble says so and falls back to a fresh guess per sample.

---

## What comes back

**Orbitals on every completed job**, with per-orbital energies and occupancies.
Click a row for a 3D isosurface with an isovalue slider. CASSCF shows genuine
fractional natural-orbital occupations rather than integer HF-style ones.
Enlarging the panel keeps the list beside the isosurface, so you can work down
the orbitals, or the vibrational modes, without shrinking the view again each
time.

**UV/Vis and IR spectra**, with the leading orbital-pair character named for
each excited state, read from the engine's own CI vectors rather than inferred.
Vibrational modes animate on all three engines. Nuclear-ensemble spectra pool
across every sampled geometry, with a per-state breakdown under the total curve.
Both the live preview and the finished figure plot energy in eV, the convention
these spectra are read in. The preview carries two controls: a broadening-width
slider, which re-renders as you drag it because the transitions are fetched once
and re-broadened in the browser with no server round trip, and a two-handled
energy window for zooming in on one band. The finished figure trims its own
x-axis to where the curve is still worth looking at, so a couple of eV of
Gaussian tail doesn't crowd out the band; the spectrum file that downloads
alongside it is untrimmed, since that one is the data rather than the view.

When a job genuinely has no oscillator strengths or IR intensities to plot, it
says so instead of drawing a flat line and pretending otherwise.

Two methods' spectra go on one axis by asking for it. Say you want the UV/Vis
spectra of the TDDFT and the EOM-CCSD run compared, and both curves are drawn
together, each normalised to its own peak so the shapes and band positions line
up rather than the taller one flattening the other. It works the same for a
nuclear-ensemble spectrum against a single-geometry one, and for several IR
spectra. Asking for wavelength instead of energy redraws the same comparison in
nanometres. Two spectra can also be subtracted rather than overlaid, which is
what you want once two methods agree closely enough that the curves sit on top
of each other. An IR spectrum and a UV/Vis spectrum are not put on one axis,
since wavenumbers and electronvolts are not the same scale, and the reply says
that rather than drawing something meaningless.

Four more charts come from numbers your calculations already produced. The
**molecular orbital levels** either side of the gap, with the HOMO and LUMO
picked out and the gap measured. **How a geometry optimization approached its
minimum**, drawn relative to the energy it finished at so the last few steps
are legible rather than a flat line. **Each excited state** at its own energy,
as tall as its oscillator strength and labelled with the orbitals that move,
which is the question a broadened band raises and cannot answer. And **how a
Wigner ensemble's samples are spread**, the standard check before you trust the
spectrum pooled from them. And a **thermochemistry breakdown** from a frequency
job, showing what the zero-point, thermal and entropy corrections each
contribute between a bare electronic energy and a free energy.

An orbital diagram is refused for a CASSCF calculation rather than drawn. Those
export natural orbitals, which carry occupancies but no orbital energies, so a
diagram would be a stack of levels at zero and a HOMO-LUMO gap measured from a
number nobody calculated.

Attaching a spectrum job to a prompt now hands over the curve itself, not just
the peak positions and heights behind it, so the agent can quote where a band
sits and how tall it is without redrawing anything.

Beyond the standard spectra, you can describe the chart you want and get it.
Ask for the excitation energies of seven methods with the method names along
the bottom and a stack of horizontal lines for each state, colour coded with a
legend, and that is what you get. The x axis is either a real number you name
or one column per calculation, the marks are lines, points, bars or energy
levels, and each series carries its own colour and legend entry. If one of the
methods never produced the quantity you asked for, its column stays on the
chart with that slot left empty, and the reply says which ones those were.

Plots are kept, not thrown away after one message. The **Plots** section of the
instrument panel lists every chart the app has drawn, yours and the spectra
jobs produce on their own, each with a thumbnail, a name you can change, and
buttons to attach, download or delete it. One filter box narrows the list, and
clicking a row opens the chart full size alongside the numbers behind it. Attaching one to a prompt lets you
ask about it, and asking for a change ("make the y axis log", "drop the CASSCF
column", "colour S2 red") edits the plot rather than starting a new one. Each
edit keeps the previous image, so an older message still shows the chart it was
actually talking about.

Any chart restyles by asking. Title, axis labels, font sizes, figure size,
grid, axis ranges, colours, line and marker settings, and where the legend
goes, including beside the chart rather than on top of it. Asking for bigger
text scales the title, the axis labels, the tick numbers and the legend
together, so one request does what you meant. A chart can be downloaded as SVG
or PDF as well as PNG, at whatever size and font you set, which is what a
figure headed for a paper needs.

A plot is kept for as long as any of the calculations behind it is still
around. Delete one of the seven jobs behind a seven-method comparison and the
chart stays; delete all seven and it goes with them, since by then there is
nothing left to redraw it from.

**Everything on screen downloads**, not just the job data. That includes a PNG
of a 3D viewer in its *current* state, the angle you rotated to, the isovalue
you picked, the frame you're on, and a vibrational mode as an animated PNG.
Every file a job hands you is named the same way: the job, then which of its
files this is, then a real extension. A downloads folder reads as
`20260817_water_Freq_HF_sto-3g_ORCA_78a32a61_mode3_3840cm-1.png` rather than a
column of hex ids, and renaming a job carries through to its downloads.
Punctuation a filesystem would object to is stripped from the job's name on the
way through, so a job called `H2O CASSCF(6,6)/cc-pVDZ` still lands as a file you
can open.

**Every text viewer has a find bar with typo tolerance.** Raw input and output,
knowledge-base manuals, uploaded geometries, all open into the same viewer.
Ctrl/Cmd+F focuses its search box without leaving the page, matches are counted
and highlighted, and a query that's close but not exact still finds the word.

**Finished work can be filed into a project.** The job list otherwise only
grows, and a study that took thirty calculations sits on top of the next one's
forever. Tick the jobs you're done with, choose "Add to project", and give the
project a name. Those jobs leave the job list and the project appears in the
left sidebar, next to your conversations and files, showing how many jobs it
holds and how much disk they take.

A project can be renamed, opened to see what's in it, and downloaded as a
single zip. The zip has a spreadsheet at the top listing every job in it by
name, method, program, status, date and result, which is what makes an archive
you come back to in a year worth having; underneath it, each job's own files
keep the names its program gave them, so an unpacked ORCA job still has an
`input.inp` you can rerun.

Nothing is hidden permanently. "Show archived" in the job manager brings
archived jobs back into view, each labelled with the project it belongs to, and
one click sends any of them back. You can also send several back at once from
inside the project. A job lives in one project at a time, so filing it into
another moves it rather than copying it.

Deleting a project asks which you mean, every time, and never assumes: you can
delete just the grouping, in which case the jobs return to the job list
untouched, or delete the results along with it, which asks you to type the
project's name first. Archived jobs still count towards your storage quota, but
they are the last thing it reaches for: everything you haven't filed away goes
first.

<div align="center">
<img src="docs/screenshot-results.png" alt="A completed job: the agent's summary of the total energy, HOMO-LUMO gap and dipole moment, beside the job detail drawer showing parsed results and the per-orbital energy, occupancy and character table" width="900">
<br>
<sub><i>A finished HF/STO-3G run on water. Every number is parsed from PySCF's own output, orbital characters and localisations included.</i></sub>
</div>

### Getting a molecule in

By name, SMILES, pasted XYZ, or a sketch. Resolved through PubChem and OPSIN,
then shown in 3D with numbered atoms. You don't have to run a calculation just
to look at something.

Or upload it. Drop an `.xyz` on the composer and one geometry becomes the active
molecule, two become a start/end pair for an interpolated path or NEB, and three
or more become a taggable set you can pull individual frames from later. ORCA
and BAGEL input files upload the same way; the content lands in the chat itself,
so "run this verbatim" fills a blind job's input from what you attached with
nothing to retype.

Whatever you paste is read before it runs, so the app can tell you what it is
and offer to build the equivalent job properly instead. It reads the level of
theory the input actually computes rather than the block it starts from, which
matters on BAGEL, where every CASSCF input opens with a Hartree-Fock section
because those orbitals are the starting guess. It also counts the states: on
CASSCF and CASPT2 nothing else in the file says whether you asked for one
energy or a set of excitation energies.

A verbatim run keeps every file it wrote. If your input asks the engine for an
orbital file, you get it, both in the job's download and in the orbital viewer,
even though nothing else about the calculation is parsed.

Basis sets and functionals are matched against the names each engine really
recognises, so a typo gets you a short menu instead of a guess. If nothing in
the menu is right, its last entry searches
[Basis Set Exchange](https://www.basissetexchange.org/) for the published set,
bundled offline, not a network call, and confirms it covers every element in
your molecule before offering it.

**Say a functional the way you say it out loud.** "ωB97X-D", "m062x", "r2scan".
Each engine spells these differently and sometimes not at all, and you should
not have to remember which. Ask for M06-2X and ORCA gets `M062X`, because ORCA
rejects the hyphen. Ask for SCAN and ORCA gets `SCANFUNC`, because plain `SCAN`
is its geometry-scan keyword. Ask for ωB97X-D on PySCF, which cannot run it at
all, and you get its supported near-equivalent with a note saying why. Every
rewrite is shown on the approval card before anything runs, and where the
request is genuinely ambiguous, a bare "-d3", where the two damping schemes
give different energies. You are asked rather than chosen for.

The names on offer are ones the engine will really run. That sounds obvious and
was not: half a functional is a valid name to a quantum chemistry library, and
asking for r2SCAN used to be able to get you its exchange half, which converges
happily and quietly gives the wrong energy.

### Choosing a CASSCF active space

Picking an active space by hand is one of the more error-prone judgement calls
in multireference chemistry. Too small and you miss the physics; too large and
it's intractable.

Ask for one and you get asked two questions first: how many state-averaged roots
you're after, and which basis set you're targeting. Both shape what follows, so
neither is guessed. NexusQC then searches the literature for **your** molecule --
your uploaded papers, then published work, then the open web -- narrowing by the
root count and basis where it can, and relaxing those, never the molecule. If
nothing has been published for it, you are told that, plainly. An active space
reported for a similar-looking compound is not a weaker answer to your question;
it is an answer to a different one.

**Or name the orbitals outright.** If you have looked at a previous job's
orbitals and know which ones you want, say so and those are the ones used,
rather than however many the engine would take around the HOMO. Give as many
orbital numbers as the space is wide and they go in as they are. BAGEL and
PySCF can both do this; ORCA has no way to express it, so asking for it on an
ORCA job offers you the two engines that can instead of quietly ignoring you.

This is only ever used when you name the orbitals. NexusQC will not put a list
together out of orbital numbers that happen to be in the conversation already,
because a guessed active space arrives on the approval card looking exactly like
a chosen one while computing something else.

Then you pick the method, because there are two and they answer different
questions.

**AVAS** ([Sayfutyarova et al.](https://doi.org/10.1021/acs.jctc.7b00347))
builds the space directly from atomic valence character and runs the CASSCF in
it. One step, no screening: you get what the orbital character says, unfiltered.
Because nothing filters it, the size is yours. The cap you set *is* the size of
the space, and lone pairs survive into it. Deterministic and cheap, and the one
to ask for when you already know the space you want.

**AutoCAS** ([Stein and Reiher](https://doi.org/10.1021/acs.jctc.6b00156)) uses
AVAS only to seed a candidate pool, then computes single-orbital entropies over
a deliberately cheap unconverged pilot and sweeps for the stable plateau that
marks a chemically meaningful cutoff. The space it recommends is the entangled
subset, usually smaller than what AVAS alone selects, and the plateau, not your
cap, decides how big it is. Ask for this when you want the calculation to tell
you which orbitals are strongly correlated rather than deciding yourself.

Its pilot screens on one of two backends. **Exact CASCI** is the default, exact
for the pool and capped at 12 orbitals. **DMRG** is approximate but
polynomial-cost, screening up to 30, and needs the optional
[block2](https://github.com/block-hczhai/block2-preview) package. A 379 MB
wheel with its own bundled MKL, so it is not installed by default. The installer
offers it, and `QC_AGENT_INSTALL_DMRG=1` adds it to a Docker build. Where it is
absent the option is declined with a reason rather than offered and failed on,
and the exact-FCI pilot covers every pool up to its own 12-orbital ceiling.
Either backend feeds the same final CASSCF: the screening changes, the
recommendation machinery does not.

Either way you get a fully converged state-averaged CASSCF on the chosen space,
every orbital classified by character (σ/π/n/σ*/π*) and dominant atoms, an
isosurface viewer, and -- for AutoCAS -- the entropy plateau diagram. The result
is reported against the literature search that preceded it, including when the
two disagree.

Each orbital also carries how much of its density lies outside the molecule,
which is what a diffuse or Rydberg-like orbital looks like from the outside. An
orbital past the halfway mark is flagged and stops being described by which
atoms carry it, because a population analysis of something centred nowhere
describes nothing. That is a measure of how far the orbital reaches, not a
Rydberg assignment. On PySCF and BAGEL; ORCA tables carry neither this nor the
character column, for the reason in the architecture notes.

Two knobs matter if you work on excited states, and both were added because
the defaults quietly answer a different question than you may be asking.

**The entropy pilot screens the ground state unless you tell it otherwise.**
Single-orbital entropy measures ground-state correlation, so an orbital that
only matters once you excite *out of* it is invisible to it. A doubly
occupied lone pair carries almost no ground-state entanglement however much
the n→π* states depend on it. On uracil/cc-pVDZ that is not hypothetical:
both pilots recommend the same seven π/π* orbitals and leave the carbonyl
lone pairs in the pool, while the published spaces for that molecule include
them. Ask the pilot to screen over several states and it averages the
density matrices across them, and the lone pairs enter the ranking. Costs
roughly in proportion to the number of states, and the DMRG pilot cannot do it
at all (block2 crashes on a multi-root wavefunction). You will be told, before
anything runs, rather than after.

**The occupied/virtual split of the space is yours to set.** By default half
the orbitals come from each side, which for a long time was the only shape
reachable: on uracil a nine-orbital cap could only ever give (8e,9o), and
(12e,9o), six occupied, three virtual, the usual choice when n→π* matters,
was impossible at every cap. Say how many occupied orbitals you want and you
get that shape, clamped and reported if the pool cannot supply it.

Between the two: AutoCAS decides the *size* of its own space from the entropy
plateau, so the state count is the lever that changes which orbitals it sees.
If you want a space of a size and shape you have already chosen, AVAS is the
one to ask. It builds what you specify rather than what the entropies prefer.

Three more things worth knowing before you read a recommendation:

- **The basis is not a setting on the final step.** It builds the molecule that
  AVAS, the pilot and the entropies are all computed in, so a different basis
  can recommend a different space.
- **For AutoCAS, so is the root count.** If the space the entropies picked can't
  host the number of states you asked for, it is widened along the entropy
  ranking until it can, and the result says which part came from that rather
  than from the plateau.
- **A valence pool with nothing unoccupied in it is refused, not guessed at.**
  For a hydride of a single heavy atom the heavy-atom shells alone come back
  completely full -- water seeds three oxygen 2p orbitals holding six electrons
  -- which can describe no correlation at all. The hydrogens are brought in
  automatically in that case; if the pool is still full, you get the reason and
  the knob to turn instead of a recommendation that cannot mean anything.

You can also just ask about a space you already have -- "is (8e,8o) sensible for
this?" -- which runs no calculation and answers from the same literature search.

> A minimal basis systematically under-represents diffuse and Rydberg character.
> Treat an STO-3G recommendation as a starting point, particularly for excited
> states with charge-transfer character.

If that matters to you, the orbital table is where to look: run the same
molecule in a basis that carries diffuse functions and the diffuseness column
fills in. On water, cc-pVDZ produces nothing above 0.22 while aug-cc-pVDZ finds
five orbitals between 0.63 and 0.94, the lowest of them just under 1 eV.

---

## How it works

```mermaid
flowchart TB
    U([You]) -->|"plain language"| A

    subgraph API["FastAPI backend"]
        A["LangGraph agent<br/><i>local LLM via Ollama</i>"]
        A <-->|"exact syntax"| KB[("Knowledge base<br/>manuals · papers")]
        A -->|"builds JobSpec"| G{{"interrupt()<br/><b>approval gate</b>"}}
    end

    G -->|"shows input file"| U
    U -->|"approve"| JM["JobManager"]

    JM -->|"detached subprocess"| W["Worker"]
    W --> E1["PySCF"] & E2["ORCA"] & E3["BAGEL"]
    E1 & E2 & E3 -->|"parsed output"| R[("Results<br/>energies · orbitals · spectra")]
    R -->|"streamed over SSE"| U

    classDef gate fill:#e8a33d22,stroke:#e8a33d,stroke-width:2px
    classDef engine fill:#34c7a022,stroke:#34c7a0
    class G gate
    class E1,E2,E3 engine
```

Three properties carry the weight. The approval gate is a real graph interrupt,
so the safety property holds structurally instead of depending on the model's
cooperation. Jobs are fully detached subprocesses, so a calculation outlives the
request, the session, and a backend restart. Orphans get reconciled at startup.
And engine output is parsed, never generated: every regex was written against
real runs, because exact formatting isn't guaranteed across versions.

A CASSCF job can run for hours. Close the tab and come back; it'll still be
there, and nothing about the UI blocks while it runs. On a shared machine it
tries to be a good neighbour: every job takes four cores by default, on any of
the three engines and enforced on the engine's own subprocess rather than left
to it, up to twenty run at once, and a new one is admitted only when the host
genuinely has headroom, so an idle machine gets used and a busy one gets left
alone. All of that is tunable.
See [CONFIGURATION.md](docs/CONFIGURATION.md#job-execution-and-resource-limits).

[**docs/ARCHITECTURE.md**](docs/ARCHITECTURE.md) covers the design decisions
and, more usefully, the alternatives that were tried and rejected.

---

## Install

One interactive script does the whole thing.

```bash
git clone https://github.com/dakshitha-a/NexusQC.git
cd NexusQC
scripts/install.sh
```

It generates your secrets, asks how the stack should be reachable (localhost,
LAN, Tailscale), generates a TLS certificate, finds ORCA and BAGEL on the host
or lets you skip either, checks Ollama and offers to pull the model, builds and
starts everything, and creates the first admin account. It ends with a URL you
can open. Re-running it is safe. It asks before touching an existing `.env` and
never touches a populated `data/`.

**Before you run it** you need Docker with Compose v2, and
[Ollama](https://ollama.com) reachable with a tool-calling model. Tool calling is
a hard requirement; a model without it cannot drive this app at all.

The default is `qwen3.8:27b`, about 16.5 GB to download and **16.3 GB resident
in VRAM** while serving. Allowing headroom for the context window and the
embedding model beside it, **24 GB of VRAM is the practical floor** -- which
puts this within reach of a single consumer card (RTX 3090, 4090, 5090) as
well as workstation and datacentre GPUs. It will run on CPU with enough system
RAM, considerably slower.

**Substituting a smaller model is not a free trade, and the failure is not
graceful.** Measured across 108 scored trials on the same task set:

| Model | End-to-end tasks | Elicitation | Grounding |
|---|---|---|---|
| `qwen3.8:27b` (16.3 GB) | 55/60 | 31/36 | 30/30 |
| 14B (8.6 GB) | 14/30 | 6/18 | 12/12 |
| 8B (4.9 GB) | 0/29 | 0/18 | 1/1 |

At 14B the agent still reports what the artifacts say, but loses tasks and
stops asking for parameters it should ask for. At 8B it cannot reliably emit a
tool call at all, which in this app means it cannot run anything. Grounding
holding while the rest degrades is not a coincidence: reported numbers come
from files on disk rather than from the model, so that property survives a
smaller model when little else does.

So: a smaller model is worth trying only if you are prepared to check whether
it can drive the tool loop, and `QC_AGENT_LLM_MODEL` is how you point at one.

**How responsive it is, measured.** On one RTX 5000 Ada (32 GB) serving
`qwen3.8:27b` through Ollama, with the model already warm: **first visible
output in about 1.9 s**, a short conversational turn complete in about 4 s.
Cold, the first request after an idle spell pays roughly 11 s to load the
model, which is what `QC_AGENT_MODEL_KEEPALIVE_INTERVAL` exists to avoid.

**Several people at once is the constraint, not raw speed.** Four
simultaneous conversations on the same single GPU took first-output times of
2.5, 7.8, 10.4 and 13.7 seconds -- a queue, not a slowdown. The reason is
VRAM rather than software: each concurrent slot needs its own key/value
cache, and at this model's shape a 64k-token context is roughly 17 GB of it,
so with 16 GB of weights a 32 GB card has room for one such slot. If you
expect concurrent users, the levers are a shorter context, more VRAM, or an
inference server that pages the KV cache instead of reserving it per slot.

`tests/backend/perf_02_ttft_and_concurrency.py` is the measurement, so you
can take it on your own hardware rather than ours.

PySCF is bundled and always available. ORCA and BAGEL are separately licensed,
never redistributed here, and bind-mounted from your own installation if you
have them.

One setting is worth checking before a long session. `QC_AGENT_LLM_NUM_CTX`
tells the app how large your model's context window is, so it knows when to
start trimming old messages. It cannot read this from the server, and it cannot
change it: the app can only be told. Run `ollama ps` after your first request
and set it to the number in the CONTEXT column. Leaving it too low only means
the agent forgets earlier turns sooner. Setting it higher than the server really
has is the one to avoid, because replies then get cut off in mid-sentence with
nothing reported anywhere, and a reply cut off before it submits a job means the
approval card never appears.

Then open the URL the installer printed and type `water`.

| Say this | To see |
|---|---|
| `water` | Structure resolution and the 3D viewer |
| `run a single point HF/STO-3G calculation on water` | A background job, with the approval card in the chat |
| `run a CASSCF calculation on formaldehyde` | It asking for the basis and active space instead of guessing |
| `what active space should I use for butadiene?` | A literature search, then an offer to compute one |

### Keeping it current

```bash
scripts/update.sh --dry-run      # report the impact, change nothing
scripts/update.sh                # fetch and update
scripts/update.sh --drain        # wait for in-flight jobs first
scripts/update.sh --rollback     # back to the last commit that came up healthy
```

`update.sh` is the only way a deployment should move forward. It refuses on a
dirty tree, reports in advance anything an update would break or destroy,
in-flight jobs, a schema change, newly required configuration, a bind mount
about to disappear, and takes a full backup before it touches anything.
`scripts/backup.sh` and `scripts/restore.sh` handle the same data on their own.

It works out what is deployed by asking the containers and the built frontend
bundle, both of which record the commit they were built from, rather than by
asking the git checkout. On a deployment where the checkout and the running
stack are the same directory, committing without rebuilding leaves those two
answers different, and the checkout's answer is the wrong one. A build it
cannot identify is treated as out of date rather than current, so the first
run against an existing deployment rebuilds once and reports accurately after
that.

### Running as a shared service

The installer already produces a multi-user deployment: real accounts, per-user
data isolation, storage quotas, an append-only audit log, and an admin console
behind the cogwheel in the sidebar. Invites, suspensions, deletions, storage
usage and bug-report triage all happen there rather than through raw API calls.
Deployment-wide purges require typing a confirmation phrase, since a second
click is too easy to do by reflex. Every user, admin or not, can download all of
their own data as a zip and purge it themselves.

**People can pass work to each other.** Find a colleague by name or username,
send them a copy of a finished calculation or a whole project archive, and it
turns up in a "Shared with me" section in their sidebar. Nothing is copied until
they accept, so nobody can fill your storage without your agreement, and you can
withdraw an offer until it is answered.

It is a real copy rather than a window onto yours, and that cuts both ways. It
goes on working after you delete your own, which is the point; it also does not
follow your later renames or re-runs. It occupies storage on both accounts, and
an offer too large for the recipient's allowance is refused with the actual
numbers rather than being made to fit by deleting something of theirs. A scan
travels with all of its images, a spectrum travels with its picture, and a
shared project arrives as their own project holding their own copies. Received
work is labelled with who sent it. Conversations are not shareable.

The storage view also reports **orphaned job directories**. Disk left behind
without a job record, by an interrupted delete or an artifact written after its
job was removed. Nothing lists those anywhere else and they count toward
nobody's quota, so nothing reclaims them on its own; an admin can, in one click,
without touching anyone's job history. A directory that changed in the last hour
is left alone and said so out loud, because a job being submitted looks the same
for a moment.

Two things worth knowing before you invite anyone. **HTTPS is mandatory**. The
session cookie is `Secure`, so login over plain HTTP silently does nothing at
all, which is the most common first-deployment failure. And there is no
password-reset flow, so an all-admin lockout is recoverable only by destroying
every account; the last active admin therefore can't be deleted or suspended.

[**Full deployment guide**](docs/DEPLOYMENT.md), certificates, quotas, admin
operations, backup and restore, lockout recovery, and an honest account of what
is and isn't verified. For running from source instead of Docker, see
[DEVELOPMENT.md](docs/DEVELOPMENT.md#running-from-source).

---

## Limitations

Worth knowing before you rely on it.

**CASPT2 is BAGEL-only**, and EOM-CCSD oscillator strengths are ORCA-only.
Neither has a workaround. CASSCF oscillator strengths are available on both
ORCA and BAGEL, and only PySCF has no route to them.

**ORCA refuses an excited-state gradient or NAC for B3LYP and BLYP**, and there
is no working substitute here. A documented LibXC rewrite was tried and came
back with a ground-state energy about 1.2 Hartree off from real B3LYP, so the
combination is refused outright rather than run with a functional that isn't the
one you asked for. That's a confirmed absence in ORCA itself, not syntax this
app got wrong. The check matches exact functional names, so another B88-derived
functional like CAM-B3LYP or BP86 slips past it and fails with ORCA's own error
at run time instead. Still safe, since no rewrite is ever applied, just less
informative than the pre-submission refusal. PBE0 works, or ask for the
ground-state gradient.

**Bare `wb97x-d` is invalid on both PySCF and ORCA**, for opposite reasons,
despite being the form most papers write. PySCF's libxc parser accepts the name
but its TDDFT gradient driver has nothing behind it; ORCA's functional list has
no entry without an explicit dispersion version and rejects it at input-check
time. Plain `wb97x` is confirmed working end to end on both. `wb97x-d3` works on
ORCA but not PySCF. `wb97x-d3bj`, `wb97x-d4` and the VV10 forms are real ORCA
keywords that crashed or aborted in testing here, so they aren't offered as
verified. See [PARSER_GAPS.md](docs/PARSER_GAPS.md).

**NEB transition-state search is ORCA-only**, and its excited-state path is less
verified than the ground-state one. **BAGEL's CASSCF geometry optimization and
frequencies are structurally confirmed but not convergence-verified** end to end.

**This app is reached over a LAN address and a tailnet address, and nothing
else.** There is no public-internet listener; a second nginx block for one was
removed on 2026-08-25, along with the admin toggle and host firewall script
that had been built to control it, because its port had never been published
and so none of it was guarding anything. Serving publicly means restoring that
listener deliberately, with a real certificate and a fresh decision about how
access gets withdrawn.

**There's no general pre-flight validator** for basis sets and keywords. An
invalid basis gets caught when the engine fails, and *Troubleshoot* is how you
turn that failure into a diagnosis.

**The model, embeddings, engines and knowledge base all stay local. Four
things do reach the public internet**, and it is worth knowing which, because
a compound name is exactly what someone choosing a local tool assumes stays on
their machine:

- **Web search** sends your query text to a third party.
- **Molecule resolution by name** sends the compound name to PubChem, and
  systematic names to the hosted OPSIN service at `opsin.ch.cam.ac.uk`.
- **Literature search** sends query text to Semantic Scholar.

None of them carries a structure you drew, a geometry you computed, or any
result. A name being looked up is the whole of what leaves.

Fuller list in [ARCHITECTURE.md](docs/ARCHITECTURE.md#known-limitations), with
what has and hasn't been exercised in [TESTING.md](docs/TESTING.md) and
[BACKLOG.md](docs/BACKLOG.md).

---

## Documentation

| Document | What it covers |
|---|---|
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Multi-user deployment, start to finish |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works and why, including rejected alternatives |
| [QM_CAPABILITIES.md](docs/QM_CAPABILITIES.md) | Per-method capability matrix, with the evidence behind each cell |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable and job-parameter default |
| [WORKFLOW.md](docs/WORKFLOW.md) | Commit discipline, releasing, and updating a deployment |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Contributing: running from source, the two-remote workflow, the public-safety scan |
| [TESTING.md](docs/TESTING.md) | What was tested, results, and what was **not** |
| [BACKLOG.md](docs/BACKLOG.md) | Known bugs, unimplemented features, and what remains unverified |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [NOTICE.md](NOTICE.md) | Third-party licences and attribution |

---

## Citation

If NexusQC contributes to published work, please cite it, and **also cite the
quantum chemistry program that performed the calculation**. NexusQC orchestrates
PySCF, ORCA and BAGEL; it does not implement the underlying methods.

Metadata is in [`CITATION.cff`](CITATION.cff), which GitHub turns into a
ready-made citation under *Cite this repository*.

## Authors

- **Dakshitha Abeygunewardane**, author, [dma@temple.edu](mailto:dma@temple.edu)
- **Spiridoula Matsika**. Principal investigator, [smatsika@temple.edu](mailto:smatsika@temple.edu)

Matsika Group, Temple University, which was the affiliation when this project
was created. Written with [Claude Code](https://claude.com/claude-code) on Opus.

## License

[MIT](LICENSE). NexusQC bundles or depends on third-party components under their
own licences, including Ketcher (Apache-2.0), 3Dmol.js (BSD-3-Clause), IBM Plex
(OFL-1.1), ASE (LGPL-2.1+) and psycopg (LGPL-3.0). **ORCA and BAGEL are never
redistributed**. ORCA's licence forbids it, and both are bind-mounted from your
own installation. See [NOTICE.md](NOTICE.md).

## Acknowledgements

Built on [PySCF](https://pyscf.org), [ORCA](https://www.faccts.de/orca/),
[BAGEL](https://nubakery.org), [RDKit](https://www.rdkit.org),
[LangGraph](https://langchain-ai.github.io/langgraph/),
[3Dmol.js](https://3dmol.csb.pitt.edu),
[Ketcher](https://lifescience.opensource.epam.com/ketcher/) and
[Ollama](https://ollama.com). Molecule data from
[PubChem](https://pubchem.ncbi.nlm.nih.gov); literature search via
[Semantic Scholar](https://www.semanticscholar.org).
