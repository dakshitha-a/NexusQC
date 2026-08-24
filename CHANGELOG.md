# Changelog

All notable changes to NexusQC are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is load-bearing, not decoration: `scripts/release.sh` refuses to
publish a version that has no section here, so a release cannot happen without a
note saying what changed.

## [Unreleased]

### Added

- **A verbatim run keeps the files it wrote.** If a pasted ORCA or BAGEL input
  asks the engine to write an orbital file, that file is now in the job's
  download and in the orbital viewer, with the same table of orbital energies,
  occupancies and characters a job this app built for you gets. Nothing else
  about a verbatim run is interpreted, and that has not changed: the orbitals
  are a file the engine wrote, not a reading of its output.


- **Excited states along a scan or an interpolated path.** Ask for a scan and
  say how many states you want, and every point on it gets them: one curve per
  electronic state on a shared energy zero, instead of a single ground-state
  line. It works the same way for a stepped bond, angle or dihedral as it does
  for an IDPP, LIIC or linear path between two structures, because this app
  builds the geometries itself either way and each point is its own
  calculation. Say nothing about excited states and you get the ground-state
  scan you always got. The number of states means what it means for your
  method, and the app says which reading it used: for CASSCF and CASPT2 the
  count is the state-averaged roots and includes the ground state, while for
  TDDFT, CIS and EOM-CCSD it is the number of excited states above it.

- **Describe the chart you want, and get it.** Plotting is no longer a numeric
  x axis and a line. Ask for the excitation energies of seven methods with the
  method names along the bottom and a stack of horizontal lines for each state,
  colour coded with a legend, and that is now a plot the agent draws rather
  than one it correctly refuses. The x axis is either a numeric field or one
  column per calculation, named however you like; the marks are lines, points,
  bars or energy levels; and every series carries its own colour and legend
  entry.
- **A Plots panel in the instrument panel.** Every chart the app has drawn,
  in one place: the ones you asked for and the spectra jobs produce on their
  own. Each row has a thumbnail, a name you can rename by double-clicking,
  and buttons to attach it to a prompt, download it, or delete it. One filter
  box at the top narrows the list.
- **Plots can be edited by asking.** "Make the y axis log", "drop the CASSCF
  column", "colour S2 red". Every plot is saved with the recipe that drew it,
  so a change is a change to that recipe rather than a new chart built from
  scratch, and each edit keeps the previous image so an older message in the
  conversation still shows what it described.
- **Click a plot in the panel to enlarge it.** A flyout opens with the chart
  full size, the numbers behind it as a table, and, for a plot that has been
  edited, buttons to look back at earlier versions.
- **Attach a plot to a prompt and ask about it**, the same way you already
  can with a job. The agent is given the plot's recipe and the numbers behind
  it, not a description of the picture, so questions like "which method is
  the outlier here" are answered from the values.

- **Functional names resolve per engine.** Say a functional the way you say
  it out loud and the right keyword reaches the right engine: ask for M06-2X
  and ORCA gets `M062X`, because ORCA rejects the hyphenated spelling; ask
  for SCAN and ORCA gets `SCANFUNC`, because plain `SCAN` is its
  geometry-scan keyword. Every rewrite is shown on the approval card before
  anything runs, and a request that is genuinely ambiguous, such as a bare
  `-d3` where the two damping schemes give different energies, is put back
  to you as a question rather than guessed at.
- **Dispersion-corrected functionals on PySCF**, via `pyscf-dispersion` in
  `requirements.txt`. `b3lyp-d3bj`, `wb97x-d3bj`, `wb97m-d3bj` and the `-d4`
  variants all failed at the SCF before this. Note that `wb97x-d` and
  `wb97x-d3` are blacklisted inside PySCF itself and no install changes
  that; the resolver now points those at PySCF's supported near-equivalent
  and says why.
- **An admin control for orphaned job directories**, in the console's
  storage view. These are directories left behind without a job record, by
  an interrupted delete or an artifact written after its job was removed.
  Nothing listed them and they counted toward nobody's quota, so nothing
  reclaimed them on its own.

### Changed

- **The app no longer freezes while the agent is working on a job summary.**
  Opening a conversation, or just having one open, used to wait for any turn
  running in it to finish, which for an ordinary turn is around a minute. That
  wait is gone: reading a conversation no longer queues behind writing to it.
  The same wait was also stalling the background job watcher, so a job
  finishing in one conversation could delay the "your job is done" notice in
  every other one.
- **A stuck approval card.** A card could survive the request it belonged to,
  after which every button on it answered "No job approval is pending" and the
  only way out was reloading the page. Two things caused it: the server only
  told the browser about approvals that existed, never that one had gone away,
  and the browser put the card back when the server rejected it. Both fixed.
- **Re-plotting a spectrum no longer changes older messages.** UV/Vis, IR and
  nuclear-ensemble spectra were each stored under a single fixed name per
  job, so re-drawing one at a different broadening silently replaced the
  image in every earlier message that had shown it. Each render is now kept
  separately and a message stays pointing at the one it described.
- **A missing value leaves a gap instead of deleting a column.** Comparing a
  quantity across several jobs used to drop any job that did not have it, so
  asking for oscillator strengths across seven methods quietly produced a
  five-method chart, with nothing on the picture saying the other two had been
  asked. Those jobs now keep a labelled but empty column, and the reply names
  what was missing. A plot is refused outright only when nothing requested
  resolves anywhere, and that refusal now states the real reason, since a field
  that is absent and a field that is present but needs an index are different
  mistakes to fix.
- **`plot`'s `field` and `width` arguments moved into its `spec`.** One place
  configures a plot now, rather than two top-level arguments that each applied
  to only some kinds.
- **Tracking is now one active tracker at a time.** Each plan or feature gets
  its own; `docs/TRACKER.md` is whichever is in motion, and a finished one
  moves to `docs/trackers/`. The job-system overhaul's tracker was archived
  there as the first of them.

### Fixed

- **A pasted BAGEL calculation was described as the wrong one.** A BAGEL input
  is a script rather than a declaration: a CASSCF run opens with a Hartree-Fock
  section because those orbitals are the starting guess, and a CASPT2 run
  carries a CASSCF section ahead of its SMITH one for the same reason. The app
  read whichever came first, so a three-state CASSCF calculation was announced
  as a Hartree-Fock ground-state energy. It now reads the highest level of
  theory the input contains, and counts the states, on BAGEL and on ORCA alike:
  neither program has a keyword that says "excited state" for a multireference
  method, so the number of roots is the only thing that does.

- **A verbatim run's own output files were deleted before you could download
  them.** Every completed BAGEL job gets swept for the intermediates the engine
  leaves behind, keeping the files the app knows are real results. A verbatim
  run has none it knows about, because the input you pasted chose its own
  filenames, so the sweep took everything. The same sweep was also removing the
  orbital file every CASSCF and CASPT2 job writes so that a later job can start
  from its orbitals, which meant that starting a job from a BAGEL job's
  orbitals had nothing to start from.


- **Opening a job's preview from the Job Manager no longer takes two clicks.**
  Clicking a job's name did nothing at all, which looked like the app being
  slow to answer and was not: the name was the one part of the row that did
  not open the preview, because renaming a job lived on a double-click there
  and the single clicks leading up to it had to be thrown away. Renaming is
  its own button now, next to delete, and every part of the row that is not a
  button opens the preview on the first click.
- **A preview stays open when the job list has a bad moment.** The list
  refreshes itself every few seconds, and a single refresh that failed
  replaced the whole panel with an error line, taking an open preview down
  with it.
- **A long job name no longer pushes the stop and delete buttons out of
  view.** In both job lists a name that did not fit widened the whole list
  until the buttons at the end of the row sat off the edge of the panel,
  behind a horizontal scrollbar you had to find and drag before you could
  cancel or delete anything. The buttons now stay pinned at the right, and
  the name fades out where it runs out of room. Hover it to read the whole
  thing.
- **Molecular orbitals are no longer corrugated.** Lobes came out with fine
  ripples running across them, which looked like structure in the orbital and
  was nothing of the kind: it was the cube grid's own staircase showing
  through, because the viewer applied a single smoothing pass to the surface it
  builds from that grid. It now applies enough of them. The shapes are the same
  shapes, just without the texture the grid was printing onto them.
- **The download and enlarge buttons for the orbital and vibration viewers
  are back in the viewer's own top-right corner.** They had drifted up to
  the corner of the whole section, which for those two put them over the
  orbital dropdown and the frequency table instead of over the picture they
  act on. The frequency and orbital tables get that space back.
- **Running the test suite no longer clutters everyone's job list.** Test
  scripts submit real jobs, and because they submit them directly rather
  than through the app, those jobs had no owner recorded — and a job with
  no owner is shown to everyone on purpose, so that anybody can clear it.
  The result was that every test run added jobs to your list that nobody
  removed. A run now records what was there when it started and deletes
  only what it added, and skips entirely rather than guessing if it has no
  record to compare against.
- **The concurrent-jobs limit did not limit much.** With the limit set to
  one job at a time, two ran. The scheduler decided how many jobs to let
  through by counting the ones already running, and it counted them by
  reading each job's status file from disk. Starting a job does not write
  that file straight away, so within one pass the scheduler could not see
  what it had just started, and let one extra job through every pass.
- **One person's queue could take every slot ahead of everyone else's.**
  Submit six jobs, have a colleague submit one right after, and theirs
  waited for all six of yours rather than being taken second. The
  round-robin that is supposed to prevent exactly this moved its place in
  the queue on every attempt, including attempts it refused. Once the job
  limit is reached everyone is refused, so the pointer ran off the end and
  the next pass started from the top, handing whoever happened to be first
  every slot that freed. It now moves only past someone who actually got a
  job started. Nobody loses a turn: every waiting person is still
  considered on every pass, so this only changes who goes first.
- **ORCA reported excitation energies with nothing to measure them from.**
  A TDDFT, TDA, CIS, TD-HF or EOM-CCSD job on ORCA gave you excitation
  energies and no ground-state energy at all, so nothing could place the
  states on an absolute scale. ORCA does print one, but not where it looks:
  in an excited-state run the line labelled "FINAL SINGLE POINT ENERGY" is
  the *first excited state*, not the ground state, and reading it as the
  ground state would have been an error that looks like physics. The
  converged SCF total is now recorded for TDDFT and its relatives, and the
  CCSD total for EOM-CCSD, which is the one those excitations are actually
  measured from and sits about 1.4 eV away from the SCF energy on water
  alone. PySCF already reported both.
- **Half a functional could be offered as a whole one.** Asking PySCF for
  `r2scan` could return `MGGA_X_R2SCAN`, r2SCAN's exchange half with no
  correlation functional at all. It is a real libxc code, it converges, and
  it lands 0.32 Eh from the right answer without printing a warning.
  Component-only codes are no longer offered at all.
- **The admin purge skipped jobs the console listed.** `POST
  /api/admin/purge/jobs` reported `count: 0` against a console showing 299
  finished jobs, because the quota modules asked `result.json` whether a job
  had finished while everything else asked `status.json`. There is now one
  answer to that question.
- **Downloads arrived without a file extension.** A Wigner ensemble's
  sampled geometries came down named `ensemble_xyz`, with nothing to open
  it. Every file a job hands you is now named for the job, what it is, and
  its real format.
- **The functional menu never appeared** for an ordinary single-point,
  optimization or frequency job, so a misspelled functional there got no
  suggestions at all.

- **First and last name at signup**, required alongside email/username/
  password, surfaced in the admin console's Users and Invites sections (who
  an account or a redeemed/created invite actually belongs to) rather than
  in the JWT itself. Every route already re-reads the user row from the
  database rather than trusting token claims, so a name belongs there, not
  in a token that would go stale until reissue.
- **`scripts/install.sh`**, an interactive first-time setup: generates
  fresh secrets and this host's `APP_UID`/`APP_GID`, asks how the stack
  should be reachable (localhost always on; LAN and/or Tailscale opt-in,
  detected automatically where possible) and generates a matching TLS
  certificate, detects ORCA/BAGEL on the host or asks for their paths or
  lets either be skipped (PySCF-only in that case), checks Ollama
  reachability and offers to pull the configured model, then builds,
  starts the stack and creates the first admin account.
- **`scripts/backup.sh --full`** additionally archives `data/jobs`,
  `data/kb`, `data/uploads`, `data/geometry_uploads`, `data/bug_reports`
  and `data/molecules` alongside the existing database/config backup;
  `scripts/restore.sh` restores that archive too when present, behind its
  own separate confirmation. The plain (non-`--full`) backup is unchanged.
- **`scripts/update.sh`**, the standard way any deployment moves forward:
  fetches the deployment's own `origin`, reports what the change would do
  before touching anything (reusing `scripts/check_destructive.sh`), takes
  an unconditional full backup, asks explicitly before restarting past any
  in-flight job, and supports `--dry-run`/`--drain`/`--force`/`--rollback`.

- **Declarative custom plotting.** `plot(kind="custom")` turns any tagged
  job's real result fields into a plot you describe (which fields, log
  scale, axis labels), resolved at runtime against that job's actual
  summary with no separate "known fields" schema to fall out of date.
  A bad field path refuses cleanly, listing the fields that really are
  there, rather than guessing or fabricating a value.
- **Bond/angle/dihedral queries by atom index** (`geometry_parameters`)
  against a tagged job or molecule-panel frame, returning a table; asked
  of a tagged multi-geometry master (a scan, a batch, a geometry set, a
  Wigner ensemble) instead, an ordered table or a histogram, whichever
  fits that master's shape.
- **A new job can run on a specific prior job's own geometry** instead of
  whatever is in the molecule panel, "same geometry as job X," "repeat
  that with a bigger basis." Uses that job's optimized geometry if it
  produced one, otherwise its input geometry; a job with no single
  geometry of its own (a scan, a batch, an ensemble) is refused by name.
- **A per-user danger zone.** Every signed-in user, not just admins, can
  download a zip of everything they own (jobs, KB uploads, geometry/input
  uploads) and self-purge the same three categories, a still-running job
  is always cancelled first, without touching their conversations or the
  account itself.
- **Attach a blind-input file to chat.** Uploading an ORCA/BAGEL input
  file (`.inp`/`.input`/`.json`) and attaching it now injects its raw text
  into the conversation, the same one click a `.xyz` geometry upload
  already used, so asking to run it verbatim fills a blind job's input
  from what was attached, with nothing to retype by hand.
- **Fuzzy, typo-tolerant find** on every plain-text document viewer (raw
  job input/output, a knowledge-base manual or paper, an uploaded file).
  One shared component, so a misspelled or unfamiliar-spelling query still
  finds the right word everywhere at once.
- Every plot now downloads as a symmetric, high-resolution 8×6 PNG with
  larger, more legible fonts throughout, and the UV/Vis and IR spectrum
  panels gained their own download buttons. A potential-energy scan's live
  chart now shows every electronic state's curve while the scan is still
  running, not just the ground state, instead of waiting for the
  server-rendered plot once the scan completes.

- **Standalone energy-gradient and non-adiabatic-coupling job types**
  (`single_point/grad`, `single_point/nac`), on all three engines. Gradients
  cover HF/DFT/MP2/CCSD/CASSCF on PySCF, HF/DFT/MP2/CASSCF on ORCA and
  HF/CASSCF/CASPT2 on BAGEL, including excited-state gradients on HF/DFT.
  NAC covers PySCF's SA-CASSCF, ORCA's ground-to-excited HF/DFT coupling and
  BAGEL's CASSCF/CASPT2 coupling (which also reports the transition dipole
  and oscillator strength BAGEL computes alongside it for free). The job
  drawer shows a per-atom vector table and the norm for either. ORCA refuses
  an excited-state gradient/NAC for the B88-containing functionals this app
  checks for (B3LYP, BLYP) outright. A documented `%method` LibXC rewrite
  was tried and returned a wrong ground-state energy, so there is no working
  substitute here (see the Limitations section of the README). Confirmed as
  a genuine ORCA incapability rather than a bug in this app, along with
  ORCA's separate CASSCF-NAC absence, and logged as such rather than left
  open pending further investigation.
- **`wb97x-d` (bare, no dispersion-version digit) checked explicitly given
  how commonly it's requested**, and found invalid on both engines this app
  supports, for opposite reasons: PySCF's libxc parser accepts the name but
  its TDDFT gradient driver has no implementation for it, while ORCA's own
  functional list has no entry without an explicit dispersion version and
  refuses it outright. Bare `wb97x` is confirmed working on both engines and
  is now the example this app suggests; `wb97x-d3` works on ORCA only. See
  the Limitations section of the README for the full breakdown, including
  the further ORCA keywords (`wb97x-d3bj`, `wb97x-d4`, `wb97x-v`, `wb97m-v`)
  that are real but not yet verified working on this host.
- **Registry v2 (`app/chemistry/registry2/`), dark-launched.** Replaces the
  hand-maintained per-job-type engine and parameter dictionaries with four
  factored, declarative tables and one derivation. `capabilities.py` records
  what each (engine, method) pair can compute on this host, cell by cell, with
  the evidence for every claim; `tasks.py` states which of those properties a
  task needs, and support is **derived** from the pairing rather than
  enumerated anywhere. A capability resting on `unverified` or `gap` evidence
  is unroutable, so an untested claim can never reach a user's job. Served
  alongside the existing payload under a new `v2` key on
  `GET /api/job-registry`; the v1 keys are byte-identical and the frontend is
  untouched.
- `docs/QM_CAPABILITIES.md`'s tables are now generated from that code by
  `scripts/generate_capability_docs.py`, between explicit markers so the
  hand-written analysis around them survives regeneration.
  `scripts/check_capability_matrix.py` verifies the whole cross-product
  against a golden table derived from the document's observations rather than
  from the code it checks, and fails on doc/code drift.
- **A *Troubleshoot* action on failed jobs.** A failed job now states plainly
  in the conversation that it failed and that nothing was changed or
  resubmitted. Pressing *Troubleshoot* composes one message carrying the last
  25 lines of the job's real output, read off disk by code, not chosen by the
  model, and runs it through the ordinary chat-turn path.

### Removed

- **The dual dev/production checkout workflow**, superseded by
  `scripts/install.sh`/`scripts/update.sh`: `scripts/dev_stack.sh` (and its
  `docker-compose.dev.yml` overlay and `sync_dev_stack.sh` wrapper),
  `scripts/promote.sh`, `docs/deployment-ledger.md`, and the
  `.deployment-role`/`.promotion-log` convention. A commit no longer needs a
  separate checkout to verify it before a deployment can move to it,
  `scripts/update.sh` reports the same destructive-change impact and takes
  the same unconditional backup on its own, against whichever single
  checkout is actually running.
- **Auto-retry.** A failed job used to silently start an agent turn that
  investigated and resubmitted a corrected job on its own initiative, capped at
  three attempts per chain. It spent someone's compute on a guess they had
  never agreed to, a CASSCF run on this hardware can be hours, and it hid the
  failure, because the user's first sign of trouble was a new approval card
  rather than a clear statement that their calculation had died. Gone with it:
  `MAX_AUTO_RETRIES`, `count_failed_in_chain()`, `submit_job`'s
  `retry_of_job_id` parameter and its carry-forward logic, the
  `_retry_count`/`_retried_from` spec bookkeeping, the "retry N of M" note on
  the approval card and the retry banner in the job drawer.

### Fixed

- **Deleting a user who had ever performed an audited action returned a
  500.** `admin_audit_log.actor_user_id` was declared `ON DELETE SET NULL`,
  but that table also carries a `BEFORE UPDATE` trigger that rejects every
  write, because the admin action history is meant to be append-only and
  enforced as such by the database. The two were mutually exclusive by
  construction: Postgres's cascade tried to null the actor, the trigger
  refused, and the whole delete aborted. It was not an admin-only problem.
The self-service danger zone logs `purge_own_data` with the user
  themselves as the actor, so any ordinary user who purged their own data
  quietly became undeletable.

  The foreign key is the half that went. The trigger carries the guarantee
  the table exists for, and nulling the actor is the wrong behaviour for an
  audit log anyway: "who purged every job" becoming NULL destroys the
  record at exactly the moment it matters, which is after that account is
  gone. Audit rows now keep their actor across a user deletion, and a new
  `actor_username`, captured when the row is written, keeps them readable
  once there is no user row left to join against. Existing rows are
  deliberately not backfilled. They genuinely did not capture one, and
  guessing would put an invention into an append-only record.

  Two things fall out of this. `server/admin_cli.py`'s lockout-recovery
  reset no longer disables the immutability trigger around its
  `DELETE FROM users`, with no foreign key there is no write to permit, so
  nothing anywhere turns that trigger off any more. And the admin console's
  audit view now names the actor rather than showing a bare uuid.

### Changed

- **Nuclear-ensemble spectra are now plotted against energy in eV**, in the
  live preview as well as the finished figure. The preview had been reading
  in nanometres, borrowed from the single-job UV/Vis spectrum it shares its
  broadening arithmetic with, which meant the preview and the figure it was
  previewing put the same band at opposite ends of the axis. Charts also now
  carry the numbers at either end of the x-axis, which they never did. An
  axis with a name but no scale is fine for a sparkline and useless the
  moment there is a control for choosing a range.

- **A two-handled energy window on the ensemble preview**, for reading one
  band rather than the whole spread. Narrowing it rescales the intensity
  axis to what is left, so a weak shoulder beside a strong band becomes
  legible instead of a bump on the baseline. Like the broadening slider, it
  costs no network request: the pooled transitions are fetched once.

- **The finished ensemble figure trims its own x-axis** to where the total
  curve still reaches 8% of its peak. A Gaussian summed over a few hundred
  pooled transitions stays visibly non-zero for several eV either side of
  the absorption it describes, and on an axis drawn from the full pooled
  extent that tail was most of the picture. The spectrum file that
  downloads alongside the figure is deliberately untrimmed. That one is
  the data, not the view of it.

- **Ensemble spectra are broadened by 0.2 eV by default**, down from 0.4 eV.
  That figure was inherited from single-geometry UV/Vis spectra, where a
  handful of stick transitions genuinely need that much smearing to read as
  a band at all. An ensemble already carries its width in the spread of its
  samples, and broadening it as hard as a stick spectrum washes out the
  structure it was run to resolve. The number now lives in one place
  instead of three copies that had to be changed together.

- **Asking for an ensemble spectrum without a frequency calculation now
  offers to run one.** The spectrum samples a molecule's vibrations, so it
  needs somebody's normal modes; the old question just asked which finished
  frequency job to use, which strands both the user who has one but not its
  id to hand and the user who has none at all. The question now points the
  first at the Jobs panel's "Attach to prompt" button and offers the second
  the frequency calculation itself as the next thing to approve.

- **Enlarging the orbital or vibrational-mode panel now shows the table
  alongside the viewer.** Expanded, a panel covers the whole drawer, including
  the table the selection came from, so reaching a different orbital or mode
  meant shrinking the panel first. Both tables are now a column beside the
  viewer, clickable in place and showing the energies, occupancies and orbital
  character alongside what is rendered; the scrubber remains for walking a long
  list quickly, and the table scrolls to follow it.

- The 2D sketcher's lazy chunk drops from 28.7 MB (8.5 MB gzipped) to 7.6 MB
  (1.2 MB gzipped) of JS the browser must parse before the editor can paint.
  `ketcher-standalone`'s default build inlines its ~21 MB Indigo wasm binary as
  a base64 string inside the JS bundle; switching to its `dist/binaryWasm`
  entry point loads the same wasm as a real separate asset via a Web Worker
  instead (11.8 MB, fetched and compiled natively by the browser rather than
  parsed as a giant string literal). Verified live under both `vite dev` and a
  genuine static file server over the production build (nginx's own mime.types
  already serves `.wasm` correctly, confirmed against the compose image): the
  worker initializes, the `.wasm` asset returns 200 with `application/wasm`,
  Indigo actually parses a pasted SMILES correctly with no console or network
  errors, and the round trip through "Use this structure" produces the right
  molecule.
- Viewer PNG captures ("Download this view as a PNG" on the molecule and
  orbital viewers) now render at up to 3x the on-screen resolution rather than
  exactly the on-screen canvas, capped at 4096px of actual backing-store
  pixels per edge. The capture is otherwise identical, same camera, zoom,
  isovalue and background swap, and a manual rotation/pan survives it. Just
  sharper, which matters once a figure lands in a paper or a slide rather than
  staying on screen.

### Fixed

- The molecular-orbital viewer was left spinning after the isosurface panel's
  orbital slider was dragged. `FrameScrubber` reports every `pointermove`, many
  of which name the same orbital, and each was answered with a fresh
  `{index, spin}` object that `MoCubeViewer`'s fetch effect had in its
  dependency array. React compares those by reference, so every pointermove
  re-fired a real server-side cube render. A measured drag across a 36-orbital
  table issued 42 requests, which queued behind the browser's six connections
  per origin (starving job polling and the SSE stream with them) and left the
  one being waited on last in line. The effect now depends on the selection's
  primitive fields, aborts superseded requests instead of merely ignoring them,
  and waits 200 ms for the selection to settle before asking for anything: the
  same drag now costs one render. The identity half of the fix also stops
  `NebFrameViewer` re-requesting its frame's orbital on every job poll.

- `cas_reco`/`autocas` used to refuse a job outright whenever the AVAS pilot
  space couldn't seat as many electronic states as requested, on water/
  STO-3G with the default `O 2p` AVAS labels, the pilot space is (6e,3o),
  exactly one many-electron configuration, so even two states were
  impossible and the whole recommendation (entropy plot included) never
  ran. AVAS itself has no notion of state count; it's a one-electron
  orbital-selection method, so gating the recommendation on `n_states` was
  never something the algorithm itself asked for. The recommendation now
  always runs, and only the final CASSCF step clamps `n_states` down to
  whatever the recommended space can actually host, saying so via
  `n_states_requested`/`n_states_clamped_note` rather than refusing.
- The chat no longer goes silent while the agent follows up on a job of its own
  accord. When a job finished or failed, `job_watcher` ran an
  investigate-and-retry turn that held the conversation's lock for its whole
  duration, but told the frontend nothing until it was over, so the composer
  looked idle and a message sent into it blocked with no explanation. Measured
  on a real incident: ordinary turns take 53–77 s and that one is several LLM
  round trips longer, so two prompts sent during one read as a hang that then
  "suddenly started again". The watcher now announces the turn before it starts
  and the chat shows what it is doing. The user is **not** locked out. The
  composer stays enabled and a message sent meanwhile is queued and answered
  next, which is what already happened, only now visibly.

### Added

- The chat model is kept loaded in VRAM by a background keep-warm loop
  (`QC_AGENT_MODEL_KEEPALIVE_INTERVAL`, `0` to disable), removing the cold
  reload, 11.4 s against 2.9 s warm. That Ollama's ~5-minute idle eviction
  otherwise charged to whoever sent the first message after a quiet spell. It
  calls Ollama's native API on an interval: the OpenAI-compatible `/v1` endpoint
  the app uses for chat silently ignores `keep_alive`, and eviction by another
  tenant on a shared Ollama can undo it at any time.

- Download buttons throughout: the raw input, raw output, KB source preview and
  job geometry flyouts; a PNG of any 3D viewer's **current** state. Same camera,
  zoom, isovalue and frame, which no server-rendered image can reproduce; and the
  running vibrational motion as an animated PNG.
- Downloads are now named after the job rather than its id:
  `20260817_water_Freq_HF_sto-3g_ORCA_78a32a61_mode3_3840cm-1.png` instead of
  `78a32a61bab7.png`. Renaming a job renames its downloads. The date is UTC and
  the short id is retained because job labels are not unique. The same
  calculation run twice would otherwise produce two identically-named files.
  Extensions are the engine's real ones (`.inp`, `.json`, `.out`).

- A separate, destructible development stack (`docker-compose.dev.yml`,
  `scripts/dev_stack.sh`). It runs the same compose file on its own compose
  project, port and secrets, and is deliberately never published on the
  LAN address a deployment's users reach.
- `scripts/promote.sh`, the only way the production deployment moves. It refuses
  any commit without a passing verification row in `docs/deployment-ledger.md`,
  takes a backup first, and can drain running jobs (stopping admission, then
  waiting) rather than killing them.
- `scripts/check_destructive.sh`, which reports what a promotion will do before
  it does it: jobs that will be killed, columns the deployed database will
  silently not get, newly required configuration that would abort `compose up`
  after the old containers are gone, and bind mounts no file on disk would
  recreate.
- `docs/WORKFLOW.md` as the primary guide to branching, merging, pushing,
  releasing, testing and promoting.

### Changed

- `scripts/release.sh` now lists every branch not merged into `main` before
  publishing, and requires a typed confirmation to publish without them.
- `scripts/backup.sh` now backs up `docker-compose.override.yml`,
  `.deployment-role` and `.promotion-log`. The override file is untracked and is
  the only thing that bind-mounts the licensed engines, so its loss is
  unrecoverable and silent until the next container recreate, which is exactly
  what had already happened on the development host, with no copy anywhere.
- `scripts/dev_stack.sh reset` keeps `data/kb`, `data/scraped`, `data/molecules`
  and `data/bse_basis_cache`. Those are seeded content rather than test residue,
  and a reset that costs an hour of reseeding the vector store is a reset nobody
  runs. `reset --all` wipes them when the knowledge base is what changed.

### Fixed

- `POST /api/jobs/{id}/render_plot` referenced a `spec` that was never defined in
  that function, which would have been a `NameError` on every plot download.
  Found while renaming the downloads; it now reads the spec it needs.
- `api.downloadPlotPng` never appended its `<a>` to the document and revoked the
  object URL on the line after `.click()`. Both work in Chrome and are
  historically flaky elsewhere; the logic now lives once in
  `frontend/src/lib/download.ts`.
- `scripts/backup.sh` read `QC_AGENT_BACKUP_DIR` from the environment only, and
  otherwise wrote inside the repository. Both of its callers, cron and
  `promote.sh`. Have nearly-empty environments, so the fallback applied: the
  first promotion would have left the production checkout dirty and every
  subsequent promotion been refused by its own clean-tree gate. Configuration is
  now read from the environment first and the deployment's `.env` second, the
  same order is applied to the Postgres user and database name, and `/backups/`
  is gitignored as a backstop.

## [1.0.0] - 2026-08-17

First public release.

### Added

- Conversational agent over PySCF, ORCA and BAGEL, with every calculation gated
  behind a structural human approval step rather than a prompt instruction.
- Job types: single-point, geometry optimisation, frequencies, combined
  optimisation + frequencies, CASSCF, CASPT2, TDDFT/TDA/CIS/TD-HF, EOM-CCSD,
  conical-intersection optimisation, potential-energy scans, NEB transition-state
  search, orbital visualisation, active-space recommendation, nuclear-ensemble
  (Wigner) absorption spectra, and raw custom ORCA/BAGEL input.
- Basis Set Exchange integration: an offline, per-engine-translated escape hatch
  for exact published basis sets, including general-contraction handling for
  BAGEL and `%basis NewGTO` generation for ORCA.
- Multi-user deployment: Postgres, Redis and nginx via Docker Compose,
  invite-only registration, per-user ownership isolation, storage quotas, an
  append-only admin audit log, and an admin console covering invites, users and
  bug reports.
- Retrieval-augmented knowledge base over engine manuals, consulted mechanically
  on every job-input generation rather than at the model's discretion.
- `scripts/check_public_safe.sh` and a pre-push hook, so host-specific paths and
  credentials cannot reach a public remote by being forgotten.

### Fixed

- Wigner sampling applied `1/sqrt(mu)` twice, making every displacement too small
  by `sqrt(mu)`. About 4% for a hydrogen-dominated mode, but a factor of 2.2 for
  a 5 amu C=O stretch and 3.4 for the heaviest modes of a twelve-atom molecule.
  The reduced-mass helper separately fabricated `mu = 1.0 amu` for every ORCA
  mode, because ORCA's printed normal modes are unit-normalised where PySCF's are
  mass-deweighted. Both are replaced by a rescaling-invariant reduced mass paired
  with an explicitly unit-normalised direction.
- `job_context_summary` omitted a completed job's own method and basis, so "use
  the same method as the attached job" was unanswerable by any tool the agent had.
- The pre-push history scan could report a pass having examined nothing, on the
  two pushes it exists to guard: a first push to a remote that has never seen the
  branch, and a force-push after a history rewrite. In both cases the revision
  range failed to resolve, the error was discarded, and an empty commit list read
  as "this push touches nothing". An unresolvable range is now a hard error, and
  the hook recognises an unknown remote tip and widens the scan to every commit
  being pushed instead of narrowing it to none.
- The same scan blocked on its own redaction placeholders once run against the
  rewritten history, and blocked permanently on regenerable test telemetry that a
  later commit had already deleted. The placeholder exemptions are narrow and
  commented; the telemetry rule now warns about history while still blocking the
  working tree, because a hygiene rule that immutable history cannot satisfy is
  one that gets bypassed along with the rules that matter.
