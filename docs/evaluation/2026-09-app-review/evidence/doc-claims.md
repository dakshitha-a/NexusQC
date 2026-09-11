# NexusQC documentation claims, as a checklist

Every user-visible, falsifiable claim I could extract from `README.md`,
`docs/CONFIGURATION.md`, `docs/QM_CAPABILITIES.md`, `docs/DEPLOYMENT.md`,
`frontend/src/app-shell/HelpFlyout.tsx` and
`frontend/src/chat/WelcomeMessage.tsx`, at commit `ca7e0ff`.

**How to use this.** Work down the `high` rows first: those are claims a user
acts on and is misled by if false. `medium` rows are worth doing and cheap.
`low` rows are prose or presentation and can be **sampled** rather than
exhausted; I have marked them as such rather than pretending the list is
complete there.

**Priority means:**
- `high` — a user would act on it and be misled: a capability that does not
  exist, a wrong command, a wrong path, a promised output that never appears,
  a number presented as measured.
- `medium` — checkable and worth doing; a wrong answer is annoying rather than
  damaging.
- `low` — prose, framing, or a claim whose falsification costs more than it is
  worth. Sample these.

**Already falsified from code alone** (each is also filed as a finding in
`deploy.md`, do not spend live-walkthrough time re-deriving them):

| Claim | Source | What the code says |
|---|---|---|
| `scripts/update.sh --rollback` goes "back to the last commit that came up healthy" | README:848, DEPLOYMENT.md:586, check_destructive.sh:645 | On a branch checkout (which `install.sh` always produces) the rollback runs `git merge --ff-only <ancestor>`, which is a no-op. The checkout never moves and the rebuilt image is mislabelled with the old commit. |
| `docker compose run --rm api python -m server.admin_cli bootstrap-admin --email ... --username admin` | DEPLOYMENT.md:345 | `server/admin_cli.py:149-150` also requires `--first-name` and `--last-name`. The documented command exits with an argparse error. |
| Backup "`data/kb` is reproducible from `data/scraped`" as the reason kb is excluded by default | DEPLOYMENT.md:551, backup.sh:31 | `data/scraped` is archived by neither the default nor `--full`. Also missing from `--full`: `data/plots` and `data/projects.json`. |
| Update "reports … engine mounts that would quietly disappear" | DEPLOYMENT.md:591, README:854 | `check_destructive.sh:634` tests only whether `docker-compose.override.yml` **exists**, not whether it still declares the mounts. |
| WelcomeMessage: BAGEL runs potential-energy scans (`yes*`) | WelcomeMessage.tsx:21 | `engines_supporting('casscf','pes_1d')` → `('pyscf','orca')`. BAGEL is not offered. README's own table correctly shows `-`. |
| WelcomeMessage: BAGEL geometry optimisation is "CASSCF/CASPT2 only", frequencies "numerical, HF only" | WelcomeMessage.tsx:14-15 | `engines_supporting('hf','opt','min')` and `('hf','freq')` both include `bagel`; `('casscf','freq')` includes `bagel`. README says "every method" and matches the registry. |
| WelcomeMessage: oscillator strengths listed against ORCA's CASSCF cell only | WelcomeMessage.tsx:16 | `CAPABILITIES[('bagel','casscf')].osc_strengths is True`, and README:144 says a CASSCF job wanting intensities routes to BAGEL by preference. |
| `docker-compose.dev.yml`'s `ports: !override` "for the pattern" | DEPLOYMENT.md:191 | That file does not exist in the repository. |
| Status table: "Public nginx listener — commented out by default"; "Host-level kill switch — implemented for iptables" | DEPLOYMENT.md:712-713 | Both were removed on 2026-08-25, as the same document says at lines 474-480 and `nginx/nginx.conf:148-160` says. |
| `nginx/nginx.conf`'s header points at `scripts/toggle_public_access.sh` as "the REAL kill switch" | nginx/nginx.conf:6 | The script does not exist. |
| Job-parameter defaults for `entropy_method`, `max_active_orbitals`, `isoval` (and `orbital_indices` as the way to render orbitals) | CONFIGURATION.md:146-148, 166-168 | All four are in `registry2/params.py`'s `RETIRED_PARAMS`, whose comment reads "Retired with the active-space rebuild … there is no ceiling to set". None is in `PARAMS`. |
| `cas_reco` has subtypes `explain`/`autocas`/`avas` | CONFIGURATION.md:145 | `TASKS` has `('cas_reco','')` and `('cas_reco','refine')` only. The list also omits `opt/min`, `geometry_set`, `pes_1d/ee` and `interp_pes/ee`, which do exist. |
| The active-space job is "entanglement-based, **or AVAS**" | HelpFlyout.tsx:170 | `avas_aolabels` is retired and there is no AVAS subtype. |
| "There is no size limit" on a recommended active space | README:449-453 | **True** — recorded here because CONFIGURATION.md:167 contradicts it and the code settles it in the README's favour. |

---

## README.md

### Opening claims and the approval gate

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 1 | README:35-40 | Every job pauses on a real graph interrupt and shows the exact input file before running; nothing runs until you approve | Ask for `run a single point HF/STO-3G calculation on water`. An approval card must appear carrying the full input text, and `data/jobs/` must gain nothing until Approve is pressed | high |
| 2 | README:38-39 | "The card comes up as soon as the setup is complete, and whichever button you press is answered straight away rather than after another round trip to the model" | Press Approve and time it: the submission confirmation should not wait on a model turn | high |
| 3 | README:40 | "Ask to see an input without running it and it stops short of the card" | `show me the ORCA input for a B3LYP/6-31G* optimisation of water, don't run it` → input printed in chat, no approval card, no job | high |
| 4 | README:42-44 | Missing parameters produce a specific question rather than a default | `run a CASSCF calculation on formaldehyde` → must ask for basis and active space, and must not submit | high |
| 5 | README:46-51 | A failed job changes nothing on its own; a **Troubleshoot** button reads the engine output, checks the manual, searches the web, and any corrected job still goes through the approval gate | Submit a job that fails (e.g. a nonsense basis), confirm nothing is resubmitted, press Troubleshoot, confirm the diagnosis quotes the real output and that any proposed fix arrives as a new approval card | high |
| 6 | README:23-26 | Numbers reported are parsed from the engine's output, not generated | Take one reported energy and grep for it verbatim in the job's raw output file | high |

### The capability matrix (README:63-88)

The whole table is a claim per cell. `scripts/check_capability_matrix.py`
exists to catch drift between `docs/QM_CAPABILITIES.md` and
`app/chemistry/registry2/capabilities.py` — **run it first** and treat a clean
run as covering the mechanical half. What it cannot check is whether the
README's own hand-written table agrees, which is what these rows are for.

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 7 | README:60-62 | Columns are in routing order: if you don't name a program, the leftmost supporting one runs | Ask for a plain HF/STO-3G energy with no engine named → PySCF. Ask for CASPT2 → BAGEL. Ask for NEB-TS → ORCA | high |
| 8 | README:67 | PySCF excited states cover HF, DFT, EOM-CCSD, CASSCF, NEVPT2, MC-PDFT, L-PDFT, CMS-PDFT | Ask for excited states at each of those methods on PySCF and confirm the job is accepted (or that the refusal names a different reason than "not supported") | high |
| 9 | README:73 | Conical-intersection optimisation: **not** on PySCF; ORCA at HF/DFT; BAGEL at CASSCF/CASPT2 | Ask for a CI optimisation on PySCF → must be refused and offered another engine | high |
| 10 | README:74 | Transition state by NEB is ORCA-only | Ask for an NEB-TS on PySCF and on BAGEL → both refused | high |
| 11 | README:79 | Scanning a bond/angle/dihedral is **not** available on BAGEL | `scan the O-H bond of water with CASSCF on BAGEL` → refused, not silently rerouted | high |
| 12 | README:82 | Nuclear-ensemble UV/Vis on PySCF is limited to HF, DFT, CMS-PDFT | Ask for a Wigner spectrum at CASSCF on PySCF → refused or routed elsewhere | high |
| 13 | README:85 | Active-space recommendation is PySCF/CASSCF only | Ask for one while naming ORCA → must offer PySCF instead of running | high |
| 14 | README:86 | Naming the orbitals yourself works on PySCF and BAGEL, never ORCA | Ask for an ORCA CASSCF with named orbital indices → must be refused and offer the two engines that can (also README:468) | high |
| 15 | README:88 | "Run your own input file, verbatim" is ORCA/BAGEL only, never PySCF | Paste a PySCF Python script and ask to run it verbatim → recognised but refused (HelpFlyout:197 makes the same claim) | high |
| 16 | README:97-99 | "Every method" means: PySCF = HF, DFT, MP2, CCSD, EOM-CCSD, CASSCF, NEVPT2, MC-PDFT, L-PDFT, CMS-PDFT; ORCA = that list minus the last four; BAGEL = HF, CASSCF, CASPT2 | Ask for a NEVPT2 job on ORCA → refused. Ask for MP2 on BAGEL → refused | high |
| 17 | README:90-95 | The active-space recommendation answers for a transition-metal molecule but says **on the job itself** that it is outside what was measured | Ask for an active space for ferrocene; the caveat must appear on the job/result, not only in chat | high |

### What the table can't show (README:103-176)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 18 | README:103-108 | One gradient job can cover several states and one NAC job several state pairs; where the program supports it the whole set comes from a single calculation | Ask for gradients on S1, S2 and S3 in one request → one job, three gradients. Check the raw output for a single SCF/TDDFT solve | high |
| 19 | README:108-109 | Where the program does not support it, the job runs the program once per state/pair and still returns one result | Same request on an engine that lacks multi-state gradients → still one job id, multiple engine invocations in the artifacts | medium |
| 20 | README:110-112 | On HF or DFT, couplings are ground-to-excited only | Ask for the S1–S2 coupling at TDDFT → refused with that reason | high |
| 21 | README:114-123 | For a multireference method only BAGEL computes an excited-state gradient; asking for excited-state MR gradients routes to BAGEL on its own, and asking on PySCF/ORCA is refused **before anything runs** | `gradient on S1 with CASSCF` → goes to BAGEL. Name PySCF explicitly → refused up front, no job | high |
| 22 | README:122-123 | Excited-state gradients at HF or DFT work on both PySCF and ORCA | Run one on each | medium |
| 23 | README:125-138 | A batch takes geometries from a scan, an interpolated path, a nuclear ensemble, an NEB run, or an uploaded set, and runs one calculation per geometry | Run a scan, then `run excited states at every geometry of that scan` | high |
| 24 | README:128-133 | Any batch member that solves for electronic states reports where those states were, in **absolute** energies, at every geometry | Run NACs over a scan; the result must carry absolute state energies per geometry, not only couplings | high |
| 25 | README:134-137 | In a batch constrained optimisation, naming a coordinate **without a value** holds it at whatever each structure already has | Run a constrained opt over a scan naming only the dihedral → each job holds its own starting value | medium |
| 26 | README:137-138 | When batch results share a scan coordinate, the finished set is plotted against it | Confirm a plot appears automatically | medium |
| 27 | README:140-142 | TDDFT, TDA-DFT, CIS and TD-HF are the same excited-state row with one flag, not separate calculations | Ask for TDA explicitly → the same task with `use_tda` set (CONFIGURATION.md:159) | medium |
| 28 | README:143-144 | CASPT2 always goes to BAGEL regardless of routing order | Ask for CASPT2 naming PySCF → refused or rerouted with a reason | high |
| 29 | README:144-147 | A CASSCF job needing oscillator strengths goes to BAGEL by preference; ORCA is used if named; PySCF cannot report one at all | `CASSCF excited states with oscillator strengths` → BAGEL. Add "use ORCA" → ORCA. Add "use PySCF" → refused | high |
| 30 | README:149-152 | NEVPT2, MC-PDFT, L-PDFT and CMS-PDFT are PySCF-only, all need an active space, and the three pair-density ones additionally need an **on-top** functional (tPBE/ftPBE, not B3LYP/PBE0) | Ask for MC-PDFT with B3LYP as the on-top functional → must be corrected or refused | high |
| 31 | README:154-156 | NEVPT2 gives energies only: no optimisation, no frequencies | Ask to optimise at NEVPT2 → refused, with that reason | high |
| 32 | README:157-159 | Of the four, **only CMS-PDFT gives transition intensities** | Ask for a UV/Vis spectrum at L-PDFT → told it has no intensities; at CMS-PDFT → intensities appear | high |
| 33 | README:163-169 | Excited states from every multireference method are of the **same multiplicity as the ground state** (a closed-shell molecule gets singlets) | Run SA-CASSCF on water and confirm every reported root is a singlet (the pre-2026-08-29 bug returned a triplet as S1) | high |
| 34 | README:171-172 | Orbitals are on every completed job, in its own drawer, and are not a separate calculation | Open any finished job's drawer | high |
| 35 | README:174-176 | Asking for a Gaussian or Psi4 calculation returns the input file in chat plus a plain statement it can't be run here | `write me a Gaussian input for water at B3LYP/6-31G*` | high |

### Building on earlier work (README:178-208)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 36 | README:180-183 | Any CASSCF-based job (CASSCF, CASPT2, NEVPT2, MC-PDFT, L-PDFT, CMS-PDFT) can restart from a previous job's converged orbitals by tagging the source job | Run a CASSCF, then tag it and run another; the approval card must show the reuse | high |
| 37 | README:183-184 | Orbital reuse is **same engine only** | Tag a PySCF CASSCF and ask for a BAGEL CASSCF from it → refused | high |
| 38 | README:184-185 | ORCA uses `MOREAD`, BAGEL uses `load_ref` | Inspect the generated input text on the approval card for each | medium |
| 39 | README:187-193 | A new job can run on a previous job's geometry; the agent takes the job id from the conversation and never asks; it uses the optimised geometry if there is one, otherwise the input geometry | "run that again with cc-pVDZ" after an optimisation → the card's geometry matches the optimised one | high |
| 40 | README:191-193 | A job with no single geometry (a scan, a Wigner ensemble) is **refused by name** rather than guessed at | Ask to reuse a scan's geometry → named refusal | high |
| 41 | README:195-199 | A nuclear-ensemble spectrum draws its geometries from a finished frequency job's normal modes; with none run, the agent sets the frequency calculation up first | Ask for a Wigner spectrum with no frequency job in the conversation | high |
| 42 | README:201-208 | For CASSCF-based ensembles every sample also starts from the frequency job's converged orbitals; this is shown filled in on the approval card and can be repointed or removed; if the frequency job cannot supply orbitals (DFT, or another program) the ensemble says so and falls back | Run a CASSCF frequency job then a Wigner spectrum; check the card. Repeat from a DFT frequency job and check for the stated fallback | high |

### What comes back (README:212-349)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 43 | README:214-216 | Every completed job carries orbitals with per-orbital energies and occupancies; clicking a row gives a 3D isosurface with an isovalue slider | Open a finished job | high |
| 44 | README:216 | CASSCF shows **fractional** natural-orbital occupations, not integer HF-style ones | Open a CASSCF job's orbital table and look for non-integer occupations | high |
| 45 | README:217-219 | Enlarging the panel keeps the list beside the isosurface | Expand the orbital viewer | low (sample) |
| 46 | README:221-223 | UV/Vis and IR spectra name the leading orbital-pair character per excited state, read from the engine's CI vectors | Compare a reported character against the engine's own output | high |
| 47 | README:223 | Vibrational modes animate on all three engines | Run a frequency job on each engine available and animate a mode | medium |
| 48 | README:223-224 | Nuclear-ensemble spectra pool across every sampled geometry with a per-state breakdown under the total curve | Open a finished Wigner spectrum | high |
| 49 | README:225-226 | Both the live preview and the finished figure plot energy in **eV** | Compare the two axes | high |
| 50 | README:226-229 | The preview's broadening slider re-renders with no server round trip (transitions fetched once, re-broadened in the browser) | Drag the slider with the network tab open — no request per frame | medium |
| 51 | README:229-230 | A two-handled energy window zooms one band | Use it | medium |
| 52 | README:230-232 | The finished figure trims its x-axis; the **downloaded spectrum file is untrimmed** | Download the data file and compare its range against the figure | high |
| 53 | README:234-235 | A job with no oscillator strengths or IR intensities says so instead of drawing a flat line | Try to plot a UV/Vis for a PySCF CASSCF job (no intensities available) | high |
| 54 | README:237-241 | Two methods' spectra can be drawn on one axis, each normalised to its own peak | "compare the UV/Vis of the TDDFT and EOM-CCSD runs" | high |
| 55 | README:241-243 | Same for a nuclear-ensemble against a single-geometry spectrum, and for several IR spectra; asking for wavelength redraws it in nm | Ask for the nm version | medium |
| 56 | README:243-245 | Two spectra can be **subtracted** rather than overlaid | Ask for the difference | medium |
| 57 | README:245-247 | An IR and a UV/Vis spectrum are **not** put on one axis; the reply says so | Ask for exactly that | high |
| 58 | README:249-259 | Five further charts exist from data already computed: MO levels with HOMO/LUMO and the gap; optimisation convergence drawn relative to the final energy; excited states as sticks scaled by oscillator strength and labelled with the orbitals that move; Wigner sample spread; and a thermochemistry breakdown (ZPE, thermal, entropy) | Ask for each by name against a suitable finished job | high |
| 59 | README:261-264 | An orbital-level diagram is **refused** for a CASSCF job, because natural orbitals carry occupancies but no orbital energies | Ask for an MO diagram from a CASSCF job | high |
| 60 | README:266-268 | Attaching a spectrum job to a prompt hands over the curve itself, so the agent can quote where a band sits and how tall it is | Attach one and ask "where is the strongest band and how tall is it" | medium |
| 61 | README:270-277 | An arbitrary described chart can be produced: x axis either a named number or one column per calculation; marks as lines, points, bars or energy levels; per-series colour and legend entry | Ask for the seven-method excitation-energy chart described in the text | high |
| 62 | README:275-277 | If one method never produced the quantity, its column stays with the slot empty and the reply says which ones those were | Include a method that lacks the quantity | high |
| 63 | README:279-287 | The **Plots** section lists every chart with a thumbnail, an editable name, and attach/download/delete buttons; one filter box; clicking a row opens it full size beside its numbers | Open the Plots section | high |
| 64 | README:283-287 | Asking for a change ("make the y axis log", "drop the CASSCF column", "colour S2 red") **edits** the plot rather than starting a new one, and each edit keeps the previous image so older messages still show what they were discussing | Edit a plot twice and scroll back | high |
| 65 | README:289-295 | Any chart restyles by asking: title, axis labels, font sizes, figure size, grid, axis ranges, colours, line/marker settings, legend position including beside the chart. "Bigger text" scales title, axis labels, ticks and legend together | Ask for bigger text and check all four scaled | high |
| 66 | README:293-295 | A chart downloads as SVG or PDF as well as PNG, at the size and font you set | Download all three | high |
| 67 | README:297-300 | A plot survives while any source job survives; deleting all its source jobs deletes it | Delete one of several sources, then all of them | high |
| 68 | README:302-304 | Everything on screen downloads, including a PNG of a 3D viewer in its **current** state (angle, isovalue, frame) and a vibrational mode as an animated PNG | Rotate, change isovalue, download, compare | high |
| 69 | README:305-311 | Every downloaded file is named `safename_descriptor.extension`, e.g. `20260817_water_Freq_HF_sto-3g_ORCA_78a32a61_mode3_3840cm-1.png`; renaming a job carries through; filesystem-hostile punctuation is stripped | Rename a job to `H2O CASSCF(6,6)/cc-pVDZ` and download something | high |
| 70 | README:313-316 | Every text viewer has a find bar with typo tolerance; Ctrl/Cmd+F focuses it without leaving the page; matches are counted and highlighted | Open raw output, press Ctrl+F, type a near-miss query | high |
| 71 | README:318-323 | Ticking finished jobs and choosing "Add to project" removes them from the job list and adds a project to the left sidebar showing job count and disk usage | Do it | high |
| 72 | README:325-330 | A project downloads as a single zip with a spreadsheet at the top listing every job by name, method, program, status, date and result, and each job's files keeping the engine's own names (an unpacked ORCA job still has `input.inp`) | Download and unzip one | high |
| 73 | README:332-336 | "Show archived" brings archived jobs back into view, each labelled with its project, and one click returns any of them; several can be returned at once from inside the project; a job lives in one project at a time so filing moves rather than copies | Exercise all four | high |
| 74 | README:338-343 | Deleting a project always asks which you mean: grouping only (jobs return untouched) or results too (which requires typing the project's name). Archived jobs count toward quota but are evicted last | Try both paths; check the eviction order claim against `app/auth/storage_quota.py` | high |
| 75 | README:346-348 | Screenshot caption vs alt text: the alt text says the numbers were "parsed out of ORCA's own output", the caption immediately below says "Every number is parsed from PySCF's own output" for the same figure | Look at `docs/screenshot-results.png` and see which engine the drawer actually shows. One of the two is wrong | medium |

### Getting a molecule in (README:351-407)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 76 | README:353-356 | Molecules resolve by name, SMILES, pasted XYZ or sketch, through PubChem and OPSIN, and are shown in 3D with numbered atoms; you don't have to run anything to look | Try each of the four inputs | high |
| 77 | README:358-362 | One switch in the molecule pane turns numbering off **everywhere at once** (structures, orbitals, vibrations), downloads follow what's on screen, and the same switch is in the corner of each viewer | Toggle it and download an orbital image and a mode animation | high |
| 78 | README:364-366 | Dropping an `.xyz` on the composer: one geometry becomes the active molecule, two become a start/end pair for interpolation or NEB, **three or more become a taggable set** you can pull frames from | Upload one of each | high |
| 79 | README:366-368 | Pasting the same geometries as text into the message does exactly the same thing by the same rules | Paste a three-geometry XYZ | high |
| 80 | README:368-371 | Atom-count lines are optional; a title above each block is kept; if the titles carry one number each, that number becomes the x axis of anything run over the set | Paste blocks titled "Torsion angle at 0", "at 10", "at 20", run a batch, check the plot's x axis | high |
| 81 | README:371-373 | ORCA and BAGEL input files upload the same way, the content lands in the chat itself, and "run this verbatim" fills a blind job's input from the attachment | Upload an `.inp` and say "run this verbatim" | high |
| 82 | README:375-381 | Pasted input is read before it runs: the app says what it is and offers to build the equivalent job properly; it reads the level of theory the input actually computes rather than the opening block (a BAGEL CASSCF input opens with Hartree-Fock); it counts the states | Paste a BAGEL CASSCF input and check it is not called an HF job, and that the state count is reported | high |
| 83 | README:383-385 | A verbatim run keeps every file it wrote; an orbital file requested in the input appears both in the download and in the orbital viewer, even though nothing else is parsed | Run a blind ORCA input that asks for an orbital file | high |
| 84 | README:387-392 | Basis sets and functionals are matched against the names each engine really recognises; a typo gets a short menu; the menu's last entry searches Basis Set Exchange **offline** (no network call) and confirms element coverage before offering it | Ask for `cc-pvzd` (typo), then pick the BSE entry for a set not in the menu; confirm no outbound request | high |
| 85 | README:394-402 | Functional aliasing: M06-2X → `M062X` on ORCA; SCAN → `SCANFUNC` on ORCA; ωB97X-D on PySCF → a supported near-equivalent **with a note saying why**; every rewrite is shown on the approval card; a genuinely ambiguous request (bare `-d3`) is asked about rather than chosen | Ask for each of the four on the named engine and read the card | high |
| 86 | README:404-407 | Only names the engine will really run are offered; asking for r2SCAN can no longer get you its exchange half | Ask for r2SCAN and check the resolved keyword on the card | high |

### Choosing a CASSCF active space (README:409-576)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 87 | README:415-419 | Asking for a recommendation asks exactly **one** question first: how many electronic states. The default is the ground state alone. You are **not** asked for a basis set | `what active space should I use for butadiene?` | high |
| 88 | README:421-425 | It searches literature for **your** molecule (uploaded papers → published work → open web) and says plainly when nothing has been published for it | Ask for a molecule with no literature | high |
| 89 | README:427-431 | Selection reads π normals at planar centres, lone-pair directions on heteroatoms and bond axes off the structure, ranks by approximate pair-coefficient entropy, and reports **three sizes with the cost of each** | Read the result: three sizes, each with a cost | high |
| 90 | README:433-437 | A planar nitrogen with three neighbours (pyrrole, an amide) is **not** given a lone pair | Ask for an active space for pyrrole and check no N lone pair is counted separately | high |
| 91 | README:441-445 | The answer does not depend on basis set or orientation: benzene gives (6e,6o) and butadiene (4e,4o) in STO-3G and aug-cc-pVDZ alike, and at any molecular orientation | Run all four combinations | high |
| 92 | README:445-447 | The one exception is Rydberg states: with no diffuse functions in the analysis basis you are told they were not looked for | Run in STO-3G and look for that statement | high |
| 93 | README:449-453 | **No size limit**: a large space is reported with determinant and CSF counts and which engines can reach it | Ask for an active space for something large | high |
| 94 | README:455-462 | With more than the ground state requested, a linear-response pass reports each state's energy, bright/dark, and character (n→π\*, π→π\*, Rydberg), then checks the recommended space contains them and says if one is missing | Ask for three states on formaldehyde | high |
| 95 | README:464-469 | Naming the orbitals outright works on BAGEL and PySCF; give as many numbers as the space is wide; asking on ORCA offers the two engines that can rather than ignoring you | Try on all three | high |
| 96 | README:471-474 | Named orbitals are used **only** when you name them: the app will not assemble a list from orbital numbers already in the conversation | Mention orbital numbers earlier in the conversation, then ask for a CASSCF without naming them | high |
| 97 | README:476-481 | What comes back in about a second: the recommended space plus two alternatives, every orbital classified σ/π/n/σ\*/π\* with dominant atoms, an isosurface viewer, the orbital ranking, and (unless turned off) a CASCI confirming the requested states are present; reported against the literature search including when they disagree | Time it and check every listed element is present | high |
| 98 | README:487-492 | The refinement is **offered after** the quick answer and runs only if accepted, because it takes minutes | Accept it and confirm it is not automatic | high |
| 99 | README:494-500 | The refinement's order: solve SA-CASSCF over the requested states → check the states are among the roots and restore missing character → only then drop orbitals pinned at 2.00/0.00 across every averaged state → re-solve and confirm nothing moved by more than 0.2 eV, putting back anything that did | Run it and read the ordered change list | high |
| 100 | README:502-506 | On uracil averaged over four states, both carbonyl lone pairs relax to ≈2.00 and an occupation-first cut removes both along with the n→π\* state | Reproducible claim: run uracil, 4 states, and check the occupations | medium |
| 101 | README:508-516 | The refinement returns every orbital's occupation, what each orbital is, an ordered list of every change with its justifying number, and **two orbital files**: one to restart a production CASSCF from and one in the natural-orbital basis the reported table describes | Download both and confirm they differ | high |
| 102 | README:518-522 | Two stated limits: a hard case's answer can depend on the optimisation path (treat one uracil run as one sample), and with only the ground state requested the occupations are the sole evidence | Prose; sample | low (sample) |
| 103 | README:524-529 | Each orbital is named π/π\*/n/σ/σ\* with the **weights reported next to it**, and genuinely mixed orbitals are labelled `n/sigma` rather than forced to one side | Look for an `n/sigma` label and its weights on a molecule with a heteroatom lone pair | high |
| 104 | README:531-537 | Each orbital carries how much density lies outside the molecule; past the halfway mark it is flagged and **stops** being described by which atoms carry it; this is available on PySCF and BAGEL but **ORCA tables carry neither the diffuseness nor the character column** | Compare the same molecule's tables on PySCF and ORCA | high |
| 105 | README:542-550 | For a molecule with no π system (water, ammonia, methane) every bond contributes σ and σ\* to the pool, so **water comes back as (8e, 6o)** with virtuals in it | Ask for water's active space and check for exactly (8e,6o) | high |
| 106 | README:554-556 | The basis is not upstream of the answer | Same as #91 | high |
| 107 | README:557-559 | The state count is the lever: ground state → the correlated valence space; excited states → the orbitals those states need, bright or dark | Compare a 1-state and a 3-state recommendation for the same molecule | high |
| 108 | README:560-564 | Rydberg states are reported but deliberately left **out** of the valence space, and you are told a CASSCF in that space gives valence states only | Run in aug-cc-pVDZ and look for the statement | high |
| 109 | README:566-567 | "Is (8e,8o) sensible for this?" runs no calculation and answers from the literature search | Ask it and confirm no job is created | high |
| 110 | README:573-576 | On water, cc-pVDZ produces no orbital above 0.22 diffuseness while aug-cc-pVDZ finds five between 0.63 and 0.94, the lowest just under 1 eV | Run both and compare the diffuseness column | medium |

### How it works, and resource behaviour (README:580-624)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 111 | README:606-609 | Jobs are fully detached subprocesses that outlive the request, the session and a backend restart; orphans are reconciled at startup | Submit a long job, restart the api container, confirm the job is still tracked and reaches a terminal state | high |
| 112 | README:613-614 | Close the tab and come back; nothing about the UI blocks while a job runs | Do it | high |
| 113 | README:615-619 | Every job takes four cores by default **enforced on the engine's own subprocess**, up to twenty run at once, and a new one is admitted only when the host has headroom | Check `OMP_NUM_THREADS`/`%pal` on a running worker; `scripts/spikes/spike_thread_caps.py` is named for this in CONFIGURATION.md:98 | high |

### Install (README:627-812)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 114 | README:632 | The one-liner `curl -fsSL .../scripts/install.sh \| sh` works, clones into `~/apps/NexusQC`, and installs from there | Only checkable on a scratch host. **Do not run against this deployment** | high |
| 115 | README:652-664 | The flag table: `--dir=PATH` (`NEXUSQC_DIR`), `--repo=URL` (`NEXUSQC_REPO`), `--bind=MODE` with values `localhost\|lan\|tailscale\|both`, `--non-interactive`, `--pull-model`, `--install-updater`, `--force-override`, `--help` | Verified against `scripts/install.sh:219-234` and its prologue — **all present and spelled as documented**. Re-check only if install.sh changes | medium |
| 116 | README:666-675 | `--non-interactive` needs `--bind` plus `NEXUSQC_ADMIN_EMAIL`, `_USERNAME`, `_FIRSTNAME`, `_LASTNAME`, `_PASSWORD` in the environment | Verified against `scripts/install.sh:245-250`; names match. Password must be ≥8 characters, which the README does not mention | medium |
| 117 | README:677-679 | In unattended mode nothing expensive or host-modifying happens without an explicit flag (no model pull, no systemd unit) | Read the `WANT_PULL_MODEL`/`WANT_UPDATER` defaults; confirm on a scratch host | high |
| 118 | README:681-685 | Re-running is safe: it asks before touching an existing `.env`, never touches a populated `data/`, and refuses to move a deployment forward, telling you to use `update.sh` | Scratch host only | high |
| 119 | README:687-689 | Five prerequisites (docker + compose v2 with a reachable daemon, git, openssl, curl) are all checked **before any question**, and each failure names the fix | Scratch host; `require_tools`/`require_docker` in `scripts/lib/common.sh` | high |
| 120 | README:691-696 | Ollama is not a prerequisite of the install: the installer only warns, everything else installs, but chat will not work without a tool-calling model | Scratch host | medium |
| 121 | README:698-700 | You do **not** need Node on the host | Confirm no `npm`/`node` invocation outside the image in `install.sh`/`extract_frontend.sh` | high |
| 122 | README:705-739 | The ten numbered installer steps, in that order and with those numbers | Scratch host: compare the printed step banners to the list | medium |
| 123 | README:728 | Step 7 (build) takes "ten to twenty minutes, once" | Time it | low (sample) |
| 124 | README:746-751 | The default model `qwen3.8:27b` is ~16.5 GB to download and **16.3 GB resident in VRAM**; 24 GB of VRAM is the practical floor | `ollama ps` on the host after a request; compare SIZE | high |
| 125 | README:756-767 | The model-size table: 108 scored trials; `qwen3.8:27b` 55/60 end-to-end, 31/36 elicitation, 30/30 grounding; 14B 14/30, 6/18, 12/12; 8B 0/29, 0/18, 1/1. Note the denominators differ per row, which is not explained — a reader cannot tell why 8B was scored over 29 tasks and 14B over 30 | Find the harness that produced them and confirm the denominators; this is exactly the "explain every figure" standard | high |
| 126 | README:772-776 | With the model warm on one RTX 5000 Ada: **first visible output ≈1.9 s**, a short turn complete in ≈4 s; cold, ≈11 s to load | `tests/backend/perf_02_ttft_and_concurrency.py` is named as the measurement — re-run it | high |
| 127 | README:778-786 | Four simultaneous conversations gave first-output times of 2.5, 7.8, 10.4 and 13.7 s; the cause is a full KV cache reserved per slot (~17 GB at 64k) | Same script | high |
| 128 | README:790-792 | PySCF is bundled and always available; ORCA and BAGEL are bind-mounted from your own install and never redistributed | Confirm no ORCA/BAGEL binary in the image: `docker compose run --rm api ls /opt` | high |
| 129 | README:794-802 | `QC_AGENT_LLM_NUM_CTX` must be set from `ollama ps`'s CONTEXT column; too low only shortens memory; too high truncates replies mid-sentence with nothing reported, and a truncated reply before a tool call means the approval card never appears | Compare the configured value against `ollama ps` on this host | high |
| 130 | README:806-811 | The four starter prompts each produce the stated result (`water` → structure + 3D viewer; the HF/STO-3G line → a background job with an approval card; the CASSCF line → questions instead of guesses; the butadiene line → a literature search then an offer to compute) | Type all four | high |

### Updating and shared service (README:813-922)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 131 | README:815-817 | The admin panel's Deployment section shows what is running, who has a calculation going or the app open, and what an update would break, and can run the update | Open it | high |
| 132 | README:819-824 | An update drains first: new jobs queue **and say why** while everyone stays logged in, and only once running jobs finish is everyone logged out for the restart. Browsers show an "updating" screen and reload themselves onto the new build | Submit a job, trigger a drained update, watch a second browser | high |
| 133 | README:825 | There is a rollback button and a list of past updates in the same place | Open it. **The rollback path is broken — see the falsified table above** | high |
| 134 | README:827-840 | `scripts/install_updater.sh` adds a `systemd --user` service; without it the panel reports everything but shows the host command instead of an Apply button; the api container is never given a docker socket | `docker inspect` the api container for `/var/run/docker.sock`; remove the unit and confirm the panel degrades as described | high |
| 135 | README:845-849 | The four `update.sh` invocations do what the comments say | `--dry-run` is safe to run; `--rollback` is falsified above | high |
| 136 | README:851-855 | `update.sh` refuses on a dirty tree, reports in advance in-flight jobs / a schema change / newly required configuration / a bind mount about to disappear, and takes a full backup first | `--dry-run` with a dirty tree; the bind-mount half is only partially true (see falsified table) | high |
| 137 | README:857-864 | It works out what is deployed from the image label and `frontend/dist/.build-commit`, and a build it cannot identify is treated as stale | `docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'` on the api container; `cat frontend/dist/.build-commit` | high |
| 138 | README:867-874 | The installer produces a multi-user deployment with accounts, per-user isolation, storage quotas, an append-only audit log, and an admin console behind the cogwheel in the sidebar; user/invite management, suspensions, deletions, storage and bug triage all happen there | Log in as admin and find each. **Note DEPLOYMENT.md:381 and :708 say user/invite management and the bug inbox are *not* in the console yet — the two documents disagree** | high |
| 139 | README:873-874 | Deployment-wide purges require typing a confirmation phrase | Try one | high |
| 140 | README:874 | Every user can download all of their own data as a zip and purge it themselves | Do it as a non-admin | high |
| 141 | README:876-889 | Sharing: find a colleague by name or username, send a finished calculation or a whole project, it appears under "Shared with me", nothing is copied until accepted, an offer can be withdrawn until answered | Exercise with two accounts | high |
| 142 | README:882-889 | A share is a real copy: it survives the sender deleting theirs, does not follow later renames or re-runs, occupies storage on both accounts, and an offer too large for the recipient's allowance is refused **with the actual numbers**. A scan travels with its images, a spectrum with its picture, a project arrives as their own project. Received work is labelled with who sent it. Conversations are not shareable | Each is separately checkable | high |
| 143 | README:891-897 | The storage view reports orphaned job directories, an admin can reclaim them in one click without touching job history, and a directory changed in the last hour is left alone **and said so out loud** | Create an orphan directory and check both behaviours | high |
| 144 | README:899-903 | HTTPS is mandatory (the cookie is `Secure`, so login over plain HTTP silently does nothing) and the last active admin cannot be deleted or suspended | Try to delete the last admin; try logging in over http:// | high |
| 145 | README:905-917 | Password reset: any admin issues a single-use link valid for **two hours**, which you send yourself (no mail server); the admin never sees the password; redeeming it ends every other session; an unused link can be revoked; issuing a second cancels the first; admins can do it for each other and themselves; **a reset cannot be issued for a suspended account** | Each clause is separately checkable in the admin console | high |

### Limitations (README:926-985)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 146 | README:930-932 | CASPT2 is BAGEL-only; EOM-CCSD oscillator strengths are ORCA-only; CASSCF oscillator strengths are on both ORCA and BAGEL and only PySCF has no route | Matches `CAPABILITIES` (verified: `bagel/casscf osc_strengths=True`, `pyscf/casscf=False`, `pyscf/eom_ccsd=False`). Check the app refuses accordingly | high |
| 147 | README:934-943 | ORCA refuses an excited-state gradient or NAC for **B3LYP and BLYP** and the app refuses the combination outright rather than substituting; the check matches **exact** functional names, so CAM-B3LYP or BP86 slips past and fails at run time instead | Ask for an ORCA TDDFT gradient with B3LYP (pre-submission refusal) and with CAM-B3LYP (submits, then fails) | high |
| 148 | README:945-952 | Bare `wb97x-d` is invalid on both PySCF and ORCA; plain `wb97x` works end to end on both; `wb97x-d3` works on ORCA but not PySCF; `wb97x-d3bj`, `wb97x-d4` and the VV10 forms are real ORCA keywords not offered as verified | Ask for each of the five | high |
| 149 | README:954-956 | NEB-TS is ORCA-only and its excited-state path is less verified; BAGEL CASSCF optimisation and frequencies are structurally confirmed but not convergence-verified | Consistency check against the registry, which does offer BAGEL `opt/min` and `freq` for CASSCF | medium |
| 150 | README:958-964 | The app is reachable over a LAN address and a tailnet address and nothing else; there is no public-internet listener | `docker compose port nginx 8443` and `ss -ltn`; confirm no third bind | high |
| 151 | README:966-968 | There is no general pre-flight validator for basis sets and keywords: an invalid basis is caught when the engine fails, and Troubleshoot turns that into a diagnosis | Submit a job with a made-up basis that survives the name matcher | medium |
| 152 | README:970-981 | Exactly these leave the machine: web-search query text, a compound name to PubChem, a systematic name to `opsin.ch.cam.ac.uk`, and literature query text to Semantic Scholar. **No structure you drew, geometry you computed, or result** ever leaves | Run the app behind a packet capture or an egress-logging proxy for one full session including a molecule lookup, a literature search and a job. This is the highest-value single check in this file | high |
| 153 | README:970 | The prose says "**Four** things do reach the public internet" and then lists three bullets (the second bullet holds two services) | Cosmetic, but count it while checking #152 | low |

---

## docs/CONFIGURATION.md

I diffed every `QC_AGENT_*` this document names against every one read
anywhere under `app/` and `server/`: **no documented variable is unread by the
code**, which is the failure mode that would matter most. The rows below are
the value-level claims.

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 154 | CONFIGURATION.md:3-6 | Every setting is overridable by environment variable, read from a project-root `.env`, and an explicitly exported variable always wins over the file | Set one both ways and check which applies (`app/config.py:39` loads the file) | high |
| 155 | CONFIGURATION.md:15 | `QC_AGENT_LLM_MODEL` default `qwen3.8:27b`, requiring Ollama ≥ v0.32.13 | `ollama --version` on the host; the app's resolved model in the logs | medium |
| 156 | CONFIGURATION.md:20 | `QC_AGENT_MODEL_KEEPALIVE_INTERVAL` default 60 s, `0` disables; the warmer calls Ollama's **native** `/api/generate` with `keep_alive: -1` and no prompt | Watch `ollama ps` over five idle minutes with it on and off | medium |
| 157 | CONFIGURATION.md:21 | `num_ctx` sent through Ollama's `/v1` endpoint is silently dropped, so the app can only be told the window | Send one and watch `ollama ps`'s CONTEXT column (the doc says this was verified) | medium |
| 158 | CONFIGURATION.md:23 | `QC_AGENT_LLM_FIXED_PROMPT_TOKENS` default 10000, "measured at 8,668 tokens with 16 tools on 2026-08-24"; `tests/backend/agent_01_token_budget.py` re-measures it | Run that script and compare | high |
| 159 | CONFIGURATION.md:24-25 | `QC_AGENT_LLM_HISTORY_FLOOR` 4 with a warning when the floor is what is holding messages in; `QC_AGENT_LLM_HISTORY_WINDOW` 40 and no longer the binding cap | Drive a long conversation and look for the warning | medium |
| 160 | CONFIGURATION.md:27-32 | Ollama unloads an idle model after ~5 minutes; reloading measured **11.4 s against 2.9 s warm** on the lab host | Re-measure | medium |
| 161 | CONFIGURATION.md:57-61 | Engine path defaults: `/opt/orca/orca`, `/opt/bagel/bin/BAGEL`, `/opt/intel/oneapi/setvars.sh`, the Boost/ScaLAPACK/OpenBLAS lib dirs, `/usr/bin/mpirun` | Compare with `app/config.py`. **Note `QC_AGENT_ORCA_PLOT_BIN` exists in the code and is undocumented**, while row 57 says `orca_plot` "is expected alongside" the ORCA binary — a user with it elsewhere is told there is no way to say so | medium |
| 162 | CONFIGURATION.md:67-71 | Resource defaults: `N_CORES` 4, `MAX_CONCURRENT_JOBS` 20, `MAX_CPU_PERCENT` 80, `MAX_MEM_PERCENT` 80, `CORE_IDLE_THRESHOLD_PERCENT` 20 | Compare with `app/config.py` and the admin console readout | high |
| 163 | CONFIGURATION.md:73-99 | The cap is applied to the subprocess, not requested: `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS` on every worker, `BAGEL_NUM_THREADS` for BAGEL, one thread per ORCA rank, and an ORCA input the app did not build has its `%pal` clamped to `N_CORES` on the way to disk | Submit a blind ORCA input with `%pal nprocs 64` and read the input file actually written | high |
| 164 | CONFIGURATION.md:98-99 | `PYTHONPATH=$PWD python3 scripts/spikes/spike_thread_caps.py` checks all of that against real running jobs | Run it | medium |
| 165 | CONFIGURATION.md:84-85 | Setting `N_CORES` near the machine's core count makes every job sit at `pending` with no error; "the app logs the resolved value at startup for this reason" | `docker compose logs api \| grep -i core` | medium |
| 166 | CONFIGURATION.md:108-110 | Multireference convergence is applied identically across all three engines: `1e-6` energy-only, `1e-7` for opt/freq, 200 macro-iterations | Read the generated input for a CASSCF on each engine | high |
| 167 | CONFIGURATION.md:116-119 | External-service timeouts: PubChem 15 s (as a scoped socket timeout), web search 10 s per engine, Semantic Scholar key optional and degrades gracefully, `QC_AGENT_SCRAPER_CONTACT` in the User-Agent | Check the User-Agent on a scrape; block PubChem and time the failure | medium |
| 168 | CONFIGURATION.md:125 | `QC_AGENT_SERVER_CORS_ORIGINS` defaults to the two Vite dev origins — and `docker-compose.yml` deliberately sets it **empty** in the deployment | `docker compose exec api env \| grep CORS` should show it empty | high |
| 169 | CONFIGURATION.md:126 | `QC_AGENT_IMAGINARY_FREQ_THRESHOLD_CM1` 50 is the single source of truth for all three engines **and the UI** | Grep the frontend for a second hard-coded threshold | medium |
| 170 | CONFIGURATION.md:127 | `QC_AGENT_DRAFT_HOLD_SECONDS` 900: a draft nobody finishes stops holding job summaries after that, timed from the last change; `0` waits indefinitely | Start a draft, finish a job, wait | medium |
| 171 | CONFIGURATION.md:133-137 | The job-parameter table is a transcription of `app/chemistry/registry2/params.py`'s `PARAMS` tuple | Diff the table against `PARAMS` | high |
| 172 | CONFIGURATION.md:141-148 | The task/subtype taxonomy is exactly: `single_point` (`gs`/`ee`/`nac`/`grad`), `opt` (`constrained`/`ci`), `freq`, `opt_freq`, `pes_1d`, `interp_pes`, `neb_ts`, `batch`, `wigner_spectra`, `cas_reco` (`explain`/`autocas`/`avas`), `blind` | **Already falsified.** `sorted(registry2.TASKS)` is `('batch',''), ('blind',''), ('cas_reco',''), ('cas_reco','refine'), ('freq',''), ('geometry_set',''), ('interp_pes',''), ('interp_pes','ee'), ('neb_ts',''), ('opt','ci'), ('opt','constrained'), ('opt','min'), ('opt_freq',''), ('pes_1d',''), ('pes_1d','ee'), ('single_point',{gs,ee,grad,nac}), ('wigner_spectra','')`. The three `cas_reco` subtypes named do not exist; `refine`, `geometry_set`, `opt/min`, `pes_1d/ee` and `interp_pes/ee` are missing from the list | high |
| 173 | CONFIGURATION.md:150-153 | **Any parameter not in the table has no default and is required**; the agent asks rather than guessing | Pick a parameter absent from the table and confirm it is elicited | high |
| 174 | CONFIGURATION.md:157-169 | Each default: `max_steps` 200; `temperature_K` 298.15; `use_tda` False; `want_oscillator_strengths` False except `wigner_spectra` where it is always True; `interpolation_method` `idpp`; `n_images` 6; `fwhm_eV` 0.2; `low_freq_cutoff_cm1` 100.0; `entropy_method` `exact_fci`; `max_active_orbitals` 12 (can only narrow); `isoval` 0.04; `n_states` falls back to 1 | The first eight are real (each is in `PARAMS`) — read them off an approval card. **`entropy_method`, `max_active_orbitals`, `isoval` and `orbital_indices` are in `RETIRED_PARAMS` and no longer exist**, and `n_states` is in neither, so check where its fallback actually lives | high |
| 175 | CONFIGURATION.md:167 | `max_active_orbitals` 12 "can only narrow it, never widen past 12" — set against README:449-453's "**There is no size limit**" | **Settled from code: README is right.** `params.py:295-306` retires `max_active_orbitals` with the comment "Retired with the active-space rebuild … there is no ceiling to set". Still worth confirming in the app that a >12-orbital recommendation is actually returned | high |
| 176 | CONFIGURATION.md:178-181 | Runner-level defaults not shown on the card: BAGEL CASPT2 `ms_caspt2` True, `shift` 0.2, `frozen_core` True; ORCA `cube_grid_points` 80 | Read a generated BAGEL CASPT2 input | medium |

---

## docs/QM_CAPABILITIES.md

Generated from `app/chemistry/registry2/capabilities.py`, so rather than
transcribing 415 lines: **run `scripts/check_capability_matrix.py` first**.
A clean run means the tables match the code, and then only the hand-written
analysis outside the generated markers needs a human. These are the claims a
*user* would test.

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 177 | QM_CAPABILITIES.md:6-9 | The tables are regenerated by `scripts/generate_capability_docs.py` and `scripts/check_capability_matrix.py` fails on drift | Run both; the check must exit non-zero on a deliberately edited cell | high |
| 178 | QM_CAPABILITIES.md:44-48 | A capability resting on `unverified` or `gap` evidence shows as **not claimed**, and the routing table refuses to offer it | Find a `gap` cell (e.g. PySCF `casscf` oscillator strengths) and confirm the app refuses that combination | high |
| 179 | QM_CAPABILITIES.md:29 | Versions: PySCF 2.14.0, geomeTRIC 1.1.1, ASE 3.29.0, ORCA 6.1.1, BAGEL 1.2.2 | `docker compose exec api pip show pyscf geometric ase`; `orca` and `BAGEL` version banners in a job's output | high |
| 180 | QM_CAPABILITIES.md:29-30 | Reproducible with `scripts/spikes/spike_{pyscf,orca,bagel}_caps.py` | Run the PySCF one at least | medium |
| 181 | QM_CAPABILITIES.md (pyscf `eom_ccsd` row) | PySCF EOM-CCSD gives energies but **no** oscillator strengths, which is why ORCA is the default engine for that method | Ask for EOM-CCSD with intensities and confirm the routing | high |
| 182 | QM_CAPABILITIES.md (pyscf `casscf` row) | PySCF has no analytic CASSCF Hessian, so frequencies use this app's **numerical** one; and there is no MECI optimizer at all | Run a PySCF CASSCF frequency job and check the artifacts show a numerical Hessian; ask for a PySCF CI optimisation and confirm refusal | high |
| 183 | QM_CAPABILITIES.md (pyscf `nevpt2` row) | NEVPT2 excited states go through a multi-root CASCI on state-averaged orbitals because NEVPT2 refuses a state-averaged FCI solver; a practical ceiling near 26 active orbitals | Run one and read the log | medium |
| 184 | QM_CAPABILITIES.md (pyscf `mcpdft` row) | With state averaging, MC-PDFT states can come out **reordered** against their MCSCF labels; and a single-state MC-PDFT need not equal the first root of a state-averaged one | Run both and compare | high |
| 185 | QM_CAPABILITIES.md (pyscf `dft` row) | Since `pyscf-dispersion` was added, `wb97x-d3bj`, `wb97m-d3bj`, `b3lyp-d3bj` and `wb97x-d4` **do** run on PySCF, while `wb97x-d3`/`wb97x-d` remain blacklisted upstream | Ask for each on PySCF | high |
| 186 | QM_CAPABILITIES.md:12-16 | A "Claims not confirmed" section exists at the end recording which documentation-derived claims did not survive contact with the software | Read it and spot-check one | medium |

---

## docs/DEPLOYMENT.md

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 187 | DEPLOYMENT.md:16-19 | Setting `QC_AGENT_DATABASE_URL` is the single switch that activates the whole auth layer; without it no auth or admin routes are mounted and the checkpointer stays on SQLite | Start `server.main` without it and confirm `/api/admin/*` 404s | high |
| 188 | DEPLOYMENT.md:31, 203-208, 899 | HTTPS is mandatory: over plain HTTP login "just appears to do nothing at all, no error" | Try it | high |
| 189 | DEPLOYMENT.md:104-105 | Pinned versions: Postgres 16, Redis 7, nginx 1.27, `python:3.11-slim-bookworm` | Matches `docker-compose.yml` and the `Dockerfile` (verified). Confirm on the running containers | medium |
| 190 | DEPLOYMENT.md:121-138 | Piped from curl, only the ~190-line prologue comes off the pipe; everything after runs from a file on disk you can read first | Read `scripts/install.sh`'s prologue and its `exec` | high |
| 191 | DEPLOYMENT.md:168-192 | Step 2's three values (`QC_AGENT_POSTGRES_PASSWORD`, `QC_AGENT_JWT_SECRET`, `QC_AGENT_LAN_BIND`), plus `QC_AGENT_TAILSCALE_BIND`, and that both bind variables are required for `docker compose up` to even **parse** the file | Unset one and run `docker compose config` | high |
| 192 | DEPLOYMENT.md:189-192 | Points at `docker-compose.dev.yml`'s `ports: !override` "for the pattern" | **Already falsified: that file does not exist.** The `!override` advice itself is still sound | high |
| 193 | DEPLOYMENT.md:194-201 | `APP_UID`/`APP_GID` must be added to `.env` or job artifacts end up owned by a uid you can't delete without sudo | `ls -ln data/jobs` on this deployment | high |
| 194 | DEPLOYMENT.md:210-214 | `scripts/gen_intranet_cert.sh` can be run on its own at any time and gets the subjectAltName list right; `nginx/nginx.conf` generates nothing itself | `openssl x509 -text -in nginx/certs/intranet.crt \| grep -A1 "Alternative"` | high |
| 195 | DEPLOYMENT.md:219-226 | The by-hand `openssl req` command produces a usable certificate | Run it into a scratch directory and inspect | medium |
| 196 | DEPLOYMENT.md:232-235 | Only one certificate is needed now; the second public block and its placeholder certificate were removed | `nginx/certs/` still contains `public.crt`/`public.key` on this host, and `backup.sh:186-188` still copies them. Confirm nginx starts without them | medium |
| 197 | DEPLOYMENT.md:247-254 | `cp docker-compose.override.yml.example docker-compose.override.yml`, edit both the `volumes:` paths and the `QC_AGENT_*_BIN` variables, using the same absolute path on both sides | Compare with this deployment's own override | high |
| 198 | DEPLOYMENT.md:256-259 | `docker/entrypoint.sh` sources oneAPI automatically when mounted and skips it harmlessly with a log line when not | `docker compose logs api \| head` for the entrypoint line | high |
| 199 | DEPLOYMENT.md:263-279 | The by-hand build/start sequence works and `docker compose logs -f api` ends with uvicorn listening on `0.0.0.0:8000` | Read the logs | medium |
| 200 | DEPLOYMENT.md:281-295 | Step 6 is easy to miss: nginx serves `frontend/dist` from a bind mount, `docker compose build` does not refresh it, and `scripts/extract_frontend.sh "$(git rev-parse HEAD)"` does, recording the source in `frontend/dist/.build-commit` | `cat frontend/dist/.build-commit` | high |
| 201 | DEPLOYMENT.md:297-308 | A host `npm run build` produces the same artefact, "verified byte for byte … on Node 24.19.0" | Rebuild on the host and `diff -r` against the extracted bundle | medium |
| 202 | DEPLOYMENT.md:312-324 | `scripts/install_updater.sh` installs a `.path` unit and a oneshot service, named with a hash of the checkout's absolute path so several checkouts do not collide; `--remove` and `--status` work | `systemctl --user list-units 'nexusqc-updater-*'` | high |
| 203 | DEPLOYMENT.md:326-332 | The api container is never given a docker socket; it writes a request into `data/deploy` and the host runner validates it against a fixed set of actions | `docker inspect` the api container's mounts | high |
| 204 | DEPLOYMENT.md:344-350 | The bootstrap-admin command as written | **Already falsified: missing `--first-name` and `--last-name`.** Also verify the "refuses if an admin already exists" half | high |
| 205 | DEPLOYMENT.md:354-358 | `https://<your-LAN-IP>:8443` is where you log in; new users join by invite only, no open registration | Try to reach a registration endpoint without a token | high |
| 206 | DEPLOYMENT.md:362-370 | The one-time `chown` recipe for a deployment that previously ran as root | Only on such a deployment | medium |
| 207 | DEPLOYMENT.md:376-382 | The admin console covers storage quotas, live usage, concurrency caps, bulk purges and the audit log; user/invite management and the bug-report inbox are **not** in it and go through the API | Directly contradicts README:869-871. Open the console and settle it | high |
| 208 | DEPLOYMENT.md:385-406 | The five documented `curl` examples (login, create invite, list users, read/patch config, audit log) work as written | **None of them carries `-k` or `--cacert`, and the documented deployment uses a self-signed certificate**, so each fails on certificate verification as printed. Also confirm `per_user_kb_quota_bytes` is the real config key (it is — `app/auth/storage_quota.py:53`) | high |
| 209 | DEPLOYMENT.md:414-421 | `docker compose run --rm api python -m server.admin_cli reset-all --confirm` clears users, sessions and invite tokens; `./data` is preserved unless `--wipe-data`; the audit log and bug reports survive with user references nulled | Flags verified against `server/admin_cli.py:157-159`. Exercise on a scratch stack only | high |
| 210 | DEPLOYMENT.md:427-434 | Quota defaults: KB 2 GB per user, geometry/blind uploads 500 MB per user, job artifacts **and** chat history 18 GB per user as one shared pool, everything all users 200 GB global | Verified against `app/config.py:644-657`. Confirm the admin console shows the same | high |
| 211 | DEPLOYMENT.md:437-443 | Concurrency: 20 total (clamped to `QC_AGENT_MAX_CONCURRENT_JOBS`, not resizable live), 5 per user, 4 cores per job | Verified against `app/config.py:665`. Try to PATCH the total above 20 and confirm the clamp | high |
| 212 | DEPLOYMENT.md:452-456 | Eviction is oldest-first after every job submission and every KB upload, plus every ~5 minutes from a background watcher; a pending or running job and the pre-seeded manual corpus are never evicted | Fill a quota and watch what goes | high |
| 213 | DEPLOYMENT.md:458-461 | The audit log is genuinely append-only: a Postgres trigger rejects `UPDATE`, `DELETE` and `TRUNCATE` | `docker compose exec postgres psql -c "delete from admin_audit_log"` must error | high |
| 214 | DEPLOYMENT.md:465-473 | Two ways in and no third: the LAN bind, the tailnet bind, plus loopback | `ss -ltn` and `docker compose port nginx 8443` | high |
| 215 | DEPLOYMENT.md:546-560 | What `backup.sh` captures, and the three documented invocations | **Partially falsified** (plots, projects.json, scraped). Run `--list` and inspect a real backup directory's contents | high |
| 216 | DEPLOYMENT.md:566-568 | The documented crontab line: `0 3 * * * cd /path/to/NexusQC && ./scripts/backup.sh >> backups/backup.log 2>&1` | The `backups/` directory does not exist unless `QC_AGENT_BACKUP_DIR` is unset — and two lines earlier the doc tells you to point that elsewhere. As printed the redirect fails and the cron job never runs. Install it on a scratch host and check | high |
| 217 | DEPLOYMENT.md:570-575 | `restore.sh` stops the `api` container, restores the database, restarts it, does **not** touch `.env` or certificates, and separately offers to restore `data/` from a `--full` archive | Exercise on a scratch stack. Note it also ignores `.env` when picking the database name — see `deploy.md` | high |
| 218 | DEPLOYMENT.md:589-596 | `update.sh` reports before touching anything, refuses past anything destructive without an explicit decision, takes a full backup unconditionally, and asks how to handle a running job rather than guessing. A rollback only undoes code | `--dry-run` with a job running | high |
| 219 | DEPLOYMENT.md:598-618 | Dependency changes are reported package by package in the shown format, a comments-only change says so, and an added package carries the system-dependency warning | `scripts/check_destructive.sh --from <a commit that changed requirements.txt> --to <the next>` | high |
| 220 | DEPLOYMENT.md:620-645 | Both build stamps come from the image, `extract_frontend.sh` reads `QC_AGENT_BUILD_COMMIT` back out of the image, an unstamped build reads as stale, and `QC_AGENT_BUILD_COMMIT=$(git rev-parse HEAD) docker compose up -d --build` stamps a hand-run build | `docker inspect` the label and `curl -k https://host:8443/api/version` | high |
| 221 | DEPLOYMENT.md:647-650 | When only the build is behind, the checkout is left alone and nothing is written to `.update-log` | `cat .update-log` after a rebuild-only update | medium |
| 222 | DEPLOYMENT.md:652-658 | Failure advice is situational: a destructive update names the backup and `restore.sh` rather than `--rollback` | `tests/backend/deploy_03_failure_advice.py` covers this | medium |
| 223 | DEPLOYMENT.md:660-664 | The health check asks Compose which port it publishes and tries every address Compose names; `QC_AGENT_UPDATE_HEALTH_URL` overrides | Change the published port in the override and run `--dry-run` | high |
| 224 | DEPLOYMENT.md:666-672 | `.update-log` records whether the deployment came up healthy, with an `unhealthy` verb that `--rollback` skips past | `cat .update-log` — the file's four columns are `verb date target previous` | high |
| 225 | DEPLOYMENT.md:683-696 | The deployment variable table's defaults: login/register rate limits 10 per 60 s keyed on nginx's `X-Real-IP`, session TTL 604800, admin storage cache 20 s, pool size 20, server host/port overridden to `0.0.0.0`, backup dir `./backups` retained 30 days | Compare against `app/config.py`; hit the login endpoint 11 times in a minute and expect a 429 | high |
| 226 | DEPLOYMENT.md:702-716 | The "what is and is not finished" table | Two rows are stale (public listener, host kill switch) — see the falsified table. Check the rest, especially "admin console UI … user/invite management and the bug-report inbox aren't in it yet" against README:869-871 | high |

---

## frontend/src/app-shell/HelpFlyout.tsx (the in-app tutorial)

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 227 | HelpFlyout:81-85 | Step 1: name, SMILES, raw XYZ, or the sketcher behind **the pen icon in the molecule panel on the right**; the 3D structure appears there once it resolves | Find the pen icon exactly where described | high |
| 228 | HelpFlyout:88-93 | The example prompt button prefills the composer with "Optimise the geometry of water with B3LYP/6-31G(d)" and closes the flyout | Click it | high |
| 229 | HelpFlyout:97-100 | ORCA and BAGEL inputs can be edited **by hand on the approval card**; PySCF is driven through its Python API so there is no file to edit | Open an approval card for each of the three | high |
| 230 | HelpFlyout:102-105 | Jobs survive closing the tab **and logging out**; clicking any job in the right-hand panel gives energies, orbitals, spectra, geometries and raw output | Log out with a job running, log back in | high |
| 231 | HelpFlyout:112-127 | Panel layout: left = conversations, knowledge base, Files (`.xyz` and `.inp`/`.input`/`.json` uploads attachable from there or the composer's + button); centre = chat, approval cards and plots; right = active molecule, recent jobs, job manager across every conversation. Panels collapse and resize; molecule and orbital views expand full-screen | Walk the UI | high |
| 232 | HelpFlyout:136-198 | The eleven job types and their identifiers: `single_point/gs`, `single_point/ee`, `single_point/grad`, `single_point/nac`, `opt/min`, `freq`, `opt_freq`, `cas_reco`, `pes_1d`/`interp_pes`, `neb_ts`, `wigner_spectra`, `batch`, `blind` | Enumerate `registry2.TASKS` and compare — `opt/min` is real (`tasks.py:215`) even though CONFIGURATION.md:143 omits it | high |
| 233 | HelpFlyout:169-172 | Active-space recommendation is "entanglement-based, or AVAS", can also **explain a space you already chose**, and is PySCF only | **AVAS is already falsified**: `avas_aolabels` is in `RETIRED_PARAMS` and there is no `cas_reco/avas` subtype. Ask for "an AVAS active space" and see what you actually get. The explain half is real (README:566) — ask it to explain (8e,8o) | high |
| 234 | HelpFlyout:178-180 | NEB-TS "finds the transition state between two structures you supply as endpoints. ORCA only" | Try with one structure and confirm it asks for the second | high |
| 235 | HelpFlyout:186-193 | Batch runs over "3+ structures tagged in the molecule panel" as well as over a scan/path/ensemble/NEB, one independent job per geometry | Tag three structures and run a batch | high |
| 236 | HelpFlyout:194-198 | Blind input: ORCA or BAGEL only, dictated **or attached**, same approval gate, results as raw output; a pasted PySCF Python script is recognised but never executed | Paste a PySCF script | high |
| 237 | HelpFlyout:202-206 | Every structure named, pasted or drawn is kept as a numbered frame; step through with a slider; attach any frame to a message to run on that geometry | Build three structures and step through | high |
| 238 | HelpFlyout:208-214 | Sketched structures get explicit hydrogens, distance-geometry embedding and a force-field clean-up before use; atoms are numbered **from 1** everywhere; the hash button in the molecule panel and in each viewer's corner hides numbering, and downloads follow it | Sketch something and check the 3D coordinates are sensible; verify 1-based numbering | high |
| 239 | HelpFlyout:216-223 | An uploaded geometry file: one geometry → active molecule; two → both ends of a path; **three or more → a `geometry_set` job**; nothing runs, it just holds them | Upload each. Note the README (line 366) calls the same thing "a taggable set" without naming a job type — check which the UI actually creates | high |
| 240 | HelpFlyout:232-235 | Attaching one or more finished jobs to a message lets you ask about them together, and comparing energies across jobs produces a chart **inline in the conversation** | Attach two jobs and ask for a comparison | high |
| 241 | HelpFlyout:239-250 | Failure handling: the notice carries a **Troubleshoot** button, nothing is resubmitted, a corrected job is approved like any other, and "I never rerun a calculation on my own initiative". A finished-but-wrong calculation can be asked about directly | Same as #5, plus ask about a suspicious result | high |
| 242 | HelpFlyout:253-267 | It can explain a method, help choose a basis, search uploaded manuals for exact keyword syntax, search published literature, and write an input for a program it cannot run; the "Try" button prefills the TDDFT-vs-EOM-CCSD prompt | Click the button; ask for a manual keyword lookup | medium |

---

## frontend/src/chat/WelcomeMessage.tsx (the first screen a new user sees)

The `ROWS` table here is a **hand-written duplicate** of engine routing, with a
comment saying it mirrors `app/chemistry/jobs/registry.py` — which is no longer
where routing lives. Three cells are already falsified against
`registry2` (see the table at the top). Treat the whole table as suspect and
check every cell.

| # | Source | Claim | How to check it in the running app | Priority |
|---|---|---|---|---|
| 243 | WelcomeMessage:13-24 | Every cell of the "What can it run?" table, and the meaning of the colouring ("Coloured = the engine chosen by default") | Ask for each calculation with no engine named and see which one runs. **Verified wrong already: BAGEL scans, BAGEL opt "CASSCF/CASPT2 only", BAGEL freq "numerical, HF only", and CASSCF oscillator strengths attributed to ORCA alone** | high |
| 244 | WelcomeMessage:15 | BAGEL frequencies are "numerical" | Registry offers BAGEL `freq` for HF, CASSCF and CASPT2; check whether the runner really does them numerically and whether the word belongs in a user-facing table at all | medium |
| 245 | WelcomeMessage:19 | PySCF EOM-CCSD is "energies only"; ORCA is the default and adds oscillator strengths | Matches `CAPABILITIES`. Confirm the routing | high |
| 246 | WelcomeMessage:17, 22, 23 | CASPT2 is BAGEL "default (only option)"; NEB-TS is ORCA "default (only option)"; active-space recommendation is PySCF "default (only option)" | All three match the registry. Confirm in the app | high |
| 247 | WelcomeMessage:20 | "Orbital (MO) visualisation" is listed as a calculation with a default engine | It is no longer a job type (CONFIGURATION.md:146-148: it is the `orbital_indices` parameter on a `single_point`). Check whether asking for it as a calculation still works | medium |
| 248 | WelcomeMessage:190-192 | "ORCA and BAGEL are optional and must be licensed and installed separately; without them, PySCF still covers most of this table" | Bring up a stack with no override file and check which rows go grey — the table is static, so it will claim ORCA/BAGEL rows on a PySCF-only deployment | high |
| 249 | WelcomeMessage:30-49 | The four example prompts prefill the composer (rather than sending) and each is a complete runnable request: "Show me caffeine", "Optimise the geometry of water with B3LYP/6-31G(d)", "Run a CASSCF(6,6)/cc-pVDZ calculation on formaldehyde and show me the active orbitals", "What active space would you recommend for the first excited state of butadiene?" | Click each and then send it. The CASSCF one is the most interesting: it names a space, so it should **not** trigger the elicitation described in README:810 | high |
| 250 | WelcomeMessage:78-82 | "I work out the setup, ask about anything genuinely ambiguous rather than guessing, and show you the exact input file before a single calculation runs" | Same as #1 and #4 | high |
| 251 | WelcomeMessage:113-142 | The four orientation cards: numbered frames reusable; all three programs wired in with automatic selection and override by name; jobs survive a closed tab; a failure changes nothing and Troubleshoot explains it | Each is covered by a row above; check the wording matches the behaviour | medium |
| 252 | WelcomeMessage:146-154 | "Open the tutorial" opens the HelpFlyout, and "What can it run?" expands the table | Click both | low (sample) |

---

## Cross-document contradictions worth settling in one sitting

These are places where two documents say different things, so at least one is
wrong regardless of what the app does. Each is already a row above; collected
here so they can be resolved together.

1. **Admin console scope.** README:869-871 says user/invite management,
   suspensions, deletions and bug-report triage "all happen there rather than
   through raw API calls". DEPLOYMENT.md:381-382 and :708 say user/invite
   management and the bug inbox are *not* in the console yet and go through
   the API. (#138, #207, #226)
2. **Active-space size ceiling — settled, CONFIGURATION.md is the stale one.**
   README:449-453 says "There is no size limit"; CONFIGURATION.md:167
   documents a `max_active_orbitals` ceiling of 12. The parameter is in
   `RETIRED_PARAMS` with the comment "there is no ceiling to set", so the
   README is correct and the configuration reference documents a retired
   parameter — along with `entropy_method`, `isoval`, `orbital_indices` and
   three `cas_reco` subtypes that no longer exist. Filed in `deploy.md`.
   (#93, #172, #174, #175, #233)
3. **BAGEL's capability rows.** README's matrix, the in-app welcome table and
   `registry2` disagree about BAGEL optimisation, frequencies and scans.
   The registry is the source of truth. (#243)
4. **Which engine produced the screenshot.** README:346 (alt text, ORCA) vs
   README:348 (caption, PySCF). (#75)
5. **The task taxonomy.** CONFIGURATION.md:143-145 omits `opt/min` and
   `geometry_set`; both exist in `registry2/tasks.py`, and HelpFlyout uses
   both. (#172, #232, #239)
