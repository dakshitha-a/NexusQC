# Changelog

All notable changes to NexusQC are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file is load-bearing, not decoration: `scripts/release.sh` refuses to
publish a version that has no section here, so a release cannot happen without a
note saying what changed.

## [Unreleased]

### Added

- **A coupling or gradient calculation now tells you where its states were.**
  Working out the derivative coupling between two electronic states means
  solving for those states first, on every engine, so their energies exist by
  the time the coupling does. They were being discarded. A run of couplings
  along a scan could tell you how strongly the states coupled at every
  geometry and not what any of those states cost, which made "and plot the
  state energies against the angle" a request to run the whole scan again.
  Absolute state energies, and the excitation energies above the ground
  state, now come back beside every coupling and every gradient, from PySCF,
  ORCA and BAGEL, for every level of theory that can produce them. Where an
  engine does not print the energy gap between a coupled pair, that gap is
  worked out from the same energies instead of being left blank.

- **Running a calculation over a set of geometries reports the numbers it
  computed.** A set of plain energies over a set of structures used to report
  only that it had finished: nineteen of nineteen complete, and not one
  energy, with every value sitting in the per-geometry jobs underneath it.
  It now reports the state energies along the set, and the excited-state,
  gradient and coupling runs report absolute energies beside their own
  results.

- **Geometries pasted into the message work like an uploaded file.** Paste
  three or more structures and they become a set you can run over, the same
  as dropping an `.xyz` on the composer. Atom-count lines are optional, so
  what you have in front of you can go in as it is. Titles above each block
  are kept, and if they carry one number each ("Torsion angle at 0", "at
  10"), that number becomes the x axis of anything run over the set instead
  of an image count from 1.

- **Plots can be placed on an axis you name.** For the case where what a job
  stored is not the coordinate the figure is about. It positions the points;
  the values still come from the calculation.

### Fixed

- **A set of geometries is now plotted against its own coordinate.** A run
  over an uploaded set was drawn against image number, so a torsion scan from
  0 to 180 degrees came out as points 1 to 19 and the real angles had to be
  explained underneath the picture.

- **Plots of a single job stopped depending on how many other jobs were
  open.** Naming the job to plot was ignored for custom charts, so the same
  chart drew correctly with one calculation in the conversation and was
  refused, with a confusing message about list indices, once a second one
  finished.

- **A run over a set of geometries names the jobs underneath it.** They were
  reachable in the job list and the drawer the whole time, but nothing told
  the assistant they existed, so asking it for a per-geometry number it could
  have read got an apology and an offer to run everything again.

- **Runs over one set of geometries no longer share a single name.** The name
  came from the title of whichever structure happened to be first, so a set
  of couplings, a set of excited states and a set of energies over the same
  structures were all called the same thing, in the job list, in the drawer
  and in every downloaded file. They are now named by formula and by what was
  run at each geometry.

- **Admins can issue a password reset.** Someone who has forgotten their
  password no longer needs an admin with database access: any admin opens the
  account in the Users section and issues a reset, which hands back a
  single-use link valid for two hours. They send it over themselves, since this
  deployment has no mail server and nothing is emailed on anyone's behalf. The
  person opens it, chooses their own password, and is signed in. The admin
  never sees or picks the password, which is why this is preferable to setting
  a temporary one for them.

  Redeeming a link ends every session the account had open, because the usual
  reason someone needs one is that they no longer know what else is signed in
  as them, and it cancels every other outstanding token for that account so a
  recovered account has no spare key left lying around. A link sent to the
  wrong person can be revoked while unused. Admins can do this for each other
  and for themselves. A reset cannot be issued for a suspended account:
  restoring one is a separate decision and this must not become a way around
  it. Issuing and redeeming are both recorded in the audit log; the token
  itself never is.


- **An opt-in refinement tier for the active-space recommendation.** The quick
  recommendation is chosen without ever running a CASSCF, which is what makes it
  cost a fraction of a second, and the cost of that is that nothing measures
  what it predicted. Ask for the refinement and the space is solved, checked
  against the states you asked for, corrected if one is missing, trimmed of
  orbitals that carry no correlation, and re-verified. It takes minutes rather
  than a second and is offered after the quick answer, never started for you.

  It hands back the reasoning, not just a smaller number: every orbital's
  occupation and what that orbital actually is, and an ordered list of every
  change with the measurement that justified it, written so you can reproduce
  the space by hand. Measured over seventeen benchmark molecules, eleven of the
  fourteen that finished and have a literature space land on it exactly,
  including uracil at (14e,10o).

- **Orbital character is reported with the numbers behind it.** Every orbital
  now carries its pi, lone-pair and sigma weights alongside its label, and an
  orbital that is genuinely both a lone pair and sigma is labelled `n/sigma`
  rather than being forced to one side. Some orbitals really are both: a lone
  pair on a heteroatom is an sp hybrid, so it overlaps the sigma framework by
  construction, and no threshold separates them cleanly. When you disagree with
  a label, the weights are there to overrule it.

### Fixed

- **An active-space refinement now gives the same answer twice.** The
  refinement solver converged to `1e-6` with no gradient tolerance at all, on
  the recorded argument that it starts from orbitals which are already close
  and compares its outputs at the 0.01 eV scale. Measured over five identical
  runs of acrolein, that setting moves the ground-state energy by 36 meV and
  the fifth root by 0.459 eV, and changes the character of two roots from one
  run to the next. Since the loop decides what to do next by comparing root
  characters, a character that moves changes which correction it applies. PySCF
  reported the calculation as converged in all five.

  The cause is reduction order in the threaded linear algebra, confirmed
  because the same loose settings pinned to one BLAS thread reproduce exactly.
  The tolerances are now `1e-8` with a `1e-5` gradient over 100
  macro-iterations.

  **This is not free on every system, and the cost depends on size.** A small
  molecule pays nothing measurable: acrolein runs at 4.1 s against 3.3 s on the
  same eight threads. A larger one pays real time. Uracil's refinement was
  recorded at 154 s and now takes 282 s when it converges, and 926 to 974 s
  when it does not, because failing to converge inside 100 macro-iterations
  also buys a second attempt through the slower solver. Uracil converged once
  in three tries, so that molecule now sits at the edge of the iteration
  budget. In exchange its answer stopped moving: three repeats used to give two
  different active spaces and now give one. Worth knowing for anyone tempted
  to go further: tightness
  is not monotone. At `1e-10` nothing converges at all and the entire scatter
  comes back, because a criterion the optimiser cannot reach leaves it stopping
  in an arbitrary place exactly as a criterion it reaches too early does.

  This also retires the guidance in `docs/CAS_ENGINE_METHOD.md` that
  differences below about 0.3 eV per state should be treated as not measured.
  That floor was real, and it was a property of these settings rather than of
  CASSCF.

- **Rydberg states could not be found in the basis the app itself chooses for
  them.** Whether a Rydberg state could be described was decided by testing the
  smallest primitive exponent in the molecule against 0.05. `def2-svpd` is what
  the app switches to whenever excited states are requested, and its smallest
  exponent on carbon is 0.067, so the answer was always no and every
  excited-state recommendation reported that Rydberg states had not been looked
  for.

  That is worse than a missing note, because the Rydberg label is only ever
  assigned when this check passes. Measured on formaldehyde in `def2-svpd`, the
  n to Rydberg 3s state comes out at 7.50 eV against a published 7.30 and was
  being labelled a valence transition, and a state not recognised as Rydberg is
  no longer excluded from the active space, which is how a diffuse orbital ends
  up in a valence space it cannot help. The same rule also called aug-cc-pVDZ
  non-diffuse for N2 and for F2, since those atoms' added shells are less
  diffuse in absolute terms than carbon's ordinary ones.

  No single exponent cut can work, which the orbital-table code had already
  concluded and written down. It measures the orbitals instead, and that
  measurement is now shared, so the orbital table and the Rydberg check can no
  longer disagree about what diffuse means. The question is also now asked of
  the calculation rather than of the basis set's name, which is the honest form
  of it: a basis that helps carbon may do little for fluorine.

  A refinement asked for excited states also ran its own analysis in
  `def2-svp`, with nothing diffuse in it, while the recommendation that
  produced its starting space ran in `def2-svpd`. It now follows the same rule.

- **A refinement no longer stops early blaming a state it never had.** Before
  removing an orbital the calculation checks that no requested excited state is
  lost by the removal. That check looked only at the space after the cut, so a
  state the space could not describe in the first place counted as lost by
  every removal, forever, and the refinement stopped a step early reporting
  that the state had disappeared. Uracil showed this plainly: it reported an
  n to pi\* state disappearing on a run where none of the reported states was
  n to pi\* at all. The check now compares before against after, which is what
  "lost" means. A state missing from both is a real problem and a different
  one, and blocking the removal never recovered it.

- **Orbitals added to rescue a missing state were chosen against the wrong
  ones.** When the calculation decides which orbitals a requested state needs
  that the space does not already have, it read the active orbitals as a fixed
  window. That window is only correct while the active orbitals happen to sit
  together, and the step that trims a space to what the requested states use
  leaves them scattered. After such a trim the comparison was made against a
  set of orbitals that were not the active ones, so the orbitals it then added
  were chosen on a false premise, with nothing reported amiss. The orbitals are
  now gathered before they are read.

- **A refined active space now says what it is conditioned on.** The
  calculation solves for more electronic states than were asked for, so that a
  state which moves down the list can still be found, and it reported only the
  number requested. Since the space depends on that count, a result carrying
  only the request could not be compared against another one or matched against
  a published space. Both numbers are now reported. Relatedly, if the
  spin-adapted solver cannot be loaded the calculation no longer proceeds in
  silence: mixing states of different spin makes every reported state character
  meaningless rather than merely less accurate, so the result now says so.

- **A password change now leaves an audit record.** `POST
  /api/auth/change-password` is the only path that writes a password hash, and
  unlike every admin action it recorded nothing, so an account whose password
  stopped working could not be investigated at all -- there was no way to tell
  whether it had been changed, from which session, or when.


- **Deleting a user handed back every invite token they had redeemed.**
  `invite_tokens.redeemed_by` is a foreign key declared `ON DELETE SET NULL`,
  and registration decided whether a token had been spent by reading that
  column, so removing an account quietly made its invite live again. An
  admin-role invite resurrected this way minted another admin until it
  expired. Both the registration guard and the revoke guard now decide on
  `redeemed_at`, a plain timestamp nothing cascades to; `redeemed_by` is
  unchanged and still resolves the invite list's "redeemed by" column, which
  is the only record of how an account came to exist. The admin console was
  already deriving its status from `redeemed_at` and so had been reporting
  these tokens as "redeemed" while the backend accepted them.


- **Excited-state CASSCF in the recommendation engine was averaging over
  triplets.** Asking for five states of a closed-shell molecule did not give
  five singlets: the solver returns the lowest roots of any multiplicity, and on
  o-nitrophenol three of the five were triplets. Because a triplet's transition
  density from the singlet ground state is zero, the character reported for
  those roots was meaningless, and a singlet you had asked about could be pushed
  out of the root count entirely and reported "missing". Production CASSCF jobs
  were never affected; the recommendation engine, its verification step and the
  benchmark harness were. Excitation energies from those paths move by up to
  2.3 eV, and several molecules that previously failed to converge now converge
  in roughly a fifth of the time.

- **Lone pairs on nitro, carboxyl and carboxylate groups were labelled sigma in
  the orbital table of every CASSCF job.** An orbital was only called a lone
  pair if a single atom carried most of it, and those groups hold their lone
  pairs across two equivalent oxygens, so neither atom cleared the bar. An
  in-plane lone pair is symmetric about the molecular plane exactly as a sigma
  bond is, so it then fell through to being called sigma. On o-nitrophenol this
  mislabelled the two orbitals its first two excited states are built from.

- **The recommendation could not see carbonyl lone pairs at all.** The reference
  directions it projects onto were built as pure p functions, while a lone pair
  on a heteroatom is an sp hybrid. Measured on uracil, an orbital that is 72%
  lone pair scored 2% against the old reference. Those orbitals were therefore
  missing from the recommended space, and any excited state built on them was
  reported as missing too.

### Changed

- **The active-space recommendation was rebuilt, and no longer asks you for a
  basis set.** It used to compute its whole selection -- the valence seeding,
  a pilot CASCI and its orbital entropies -- in whatever basis you named, so
  the basis was upstream of the answer and a different one could recommend a
  different space. The rebuilt engine reads the directions that matter off the
  molecular structure itself (the pi normal at each planar centre, the
  lone-pair directions on each heteroatom, the axis of every bond) and projects
  onto a fixed minimal reference basis, which makes the recommendation
  measurably identical from STO-3G to aug-cc-pVDZ. It is also unchanged by how
  your geometry happens to be oriented, which the previous version was not. You
  are asked how many states you want instead, because that does change the
  answer.

- **There is no longer a twelve-orbital limit.** That ceiling was never about
  chemistry: every recommendation ended by running a full state-averaged
  CASSCF, so the recommendation had to fit inside what CASSCF could afford, and
  a larger request was refused outright. The recommendation no longer runs that
  CASSCF. A large space now comes back with its determinant and CSF counts and
  which engines can actually reach it, and the choice is yours. A recommendation
  takes about a second.

- **Excited states are now identified by what they are made of.** A quick
  linear-response pass reports each state's energy, its character (n->pi*,
  pi->pi* or Rydberg) and whether it is bright or dark, and the recommendation
  is then checked to confirm those states are actually present in it. Dark
  states matter here: a dark n->pi* state needs a heteroatom lone pair, and the
  previous behaviour -- widening the space by whichever orbital maximised the
  number of configurations -- could not know that, so the orbital was left out
  and the state quietly vanished. Rydberg states are found and reported but
  deliberately kept out of a valence space, with a note saying so. Note that
  the recommended space itself does not yet change with the state count: the
  code that would add a missing state's orbitals is written but not yet
  connected, and the verification reports when a state is absent.

- **Open-shell molecules get a recommendation.** Both previous runners refused
  anything with unpaired electrons outright, which is unfortunate for the
  species most likely to need a multireference treatment in the first place.

- **The recommendation is checked before you see it.** Unless you turn it off,
  a CASCI runs in the chosen space to confirm the states you asked for are
  really there with the character predicted. A space too large to check that
  way is reported as unverified rather than passing quietly.

- **`cas_reco` has one subtype where it had two.** `autocas` and `avas`
  differed only in whether an entropy pilot ran; the new engine always does
  both the projection and the ranking. Both names still work as synonyms.

### Fixed

- **The assistant was told to call five tools that do not exist.** The system
  prompt named `search_active_space_literature`, `explain_active_space`,
  `search_knowledge_base`, `search_academic_literature` and `web_search`. The
  first two are dispatched by the `active_space` tool and the last three by
  `search`, so none of them was ever bound. Nothing raised; the model was told
  to call something that was not there and the turn degraded quietly, which is
  why it went unnoticed. A check now fails if the prompt names a tool the model
  has not been given.

- **A recommendation for a molecule with no pi system could come back
  describing nothing.** Water, ammonia and methane have no pi system, and
  selecting on pi and lone-pair character alone returns orbitals that are all
  doubly occupied -- one configuration, no correlation at all. Every bond now
  contributes its sigma and sigma* to the candidate pool, so water comes back
  as (8e, 6o) with virtual orbitals in it.

### Removed

- **The entropy pilot and everything that configured it**, superseded by the
  rebuilt engine: `run_recommend_active_space` and `run_avas_active_space`'s
  parameters `entropy_method`, `dmrg_bond_dim`, `max_active_orbitals`,
  `avas_aolabels`, `entropy_pilot_states` and `active_occupied_orbitals`, along
  with the two elicitation rules that refused a DMRG pilot where block2 was
  absent and a state-averaged one where it was present. The block2 constraints
  those rules encoded still hold and are recorded in
  `app/chemistry/cas/verify.py`, where they still apply.

### Fixed

- **The browser test suite now removes the accounts it creates.** Each spec
  deletes its own test account at the end, but the request went out without the
  header the CSRF check requires, so the server refused it and nothing looked
  at the answer. Every run of the suite therefore left one dormant `qatest_`
  account per spec sitting in the user list. Deployments only ever see this if
  the suite has been run against them.

- **A picture saved from a path, scan or geometry set is now named after the
  job it came from.** Capturing image 4 of a NEB path saved it as
  `molecule_view.png`, the same name as image 5 and as anything else you
  captured that session, so a handful of images off one calculation arrived as
  a pile of files that only their order told apart. They now carry the job's
  own name and the frame number, like every other download. A capture that
  fails also says so now, instead of the button quietly giving up.

- **Deleting an account now deletes its project archives too.** They used to
  survive their owner, and because a project with no recorded owner is
  deliberately visible to everyone, deleting someone's account quietly turned
  their private archives into ones the whole deployment could see. The jobs
  inside them go as well, which is what deleting an account already did to
  every other kind of data it held.

- **A scan no longer runs some of its images twice.** Only reachable when a
  calculation was submitted from a second process against a running server,
  which is how this project's own test scripts do it, so ordinary use was
  unaffected. Where it did happen, a three-image scan quietly ran five
  calculations and billed all five to the owner's storage, while showing the
  three it was supposed to.

### Added

- **Turn the atom numbers off.** Every 3D viewer numbered every atom, always,
  and because those numbers are part of the scene they ended up in every image
  and animation you exported. There was no way to get a clean picture of a
  structure or an orbital out of the app.

  One switch now governs the lot. It sits in the molecule pane and in the
  corner of each viewer, so it is reachable from a job drawer without scrolling
  back to the instrument panel, and flipping it in either place moves both.
  Structures, orbital isosurfaces and vibrational animations all follow it, and
  so does anything you download: what you save is what you were looking at. It
  starts on, so nothing you already had on screen changes, and it is remembered
  between visits.

- **Share a job or a project archive with another person.** Find a colleague by
  name or username, send them a copy, and it arrives in a "Shared with me"
  section in their sidebar. Nothing moves until they accept, so nobody can fill
  your storage without your say-so, and you can take an offer back until it is
  answered.

  What they get is a genuine copy, not a window onto yours. It keeps working
  after you delete your own, which is the whole point, and the other half of
  that bargain is that your later renames and re-runs do not reach it. It costs
  storage on both accounts, and an offer that will not fit in the recipient's
  allowance is refused with the actual figures rather than being made to fit by
  deleting something of theirs.

  A scan or an ensemble travels with all of its images. A spectrum travels with
  the picture. A shared project arrives as their own project holding their own
  copies of every job in it. A received job is badged with who sent it.

  Conversations are not shareable. A received job arrives unattached, and can be
  added to a conversation like any other.

- **A "clear selection" button in the job manager.** Selecting jobs offered two
  things to do with them and no way to change your mind short of unticking
  every row by hand. It sits beside the other two as an icon, so it does not
  crowd them.

- **The job search box and the "Show archived" toggle now share one line.** The
  toggle had a row to itself directly underneath, in the one panel that grows
  to fill the space it is given, so that row was a row of jobs not shown.

- **Project archives: finished jobs can be bundled under a name and filed
  away.** The job manager was a single flat list of every job ever run, with no
  way to group a study's calculations and no way to get them off the list once
  they were done with. Thirty rows from last month sat on top of this month's.

  Tick the jobs you are finished with, choose "Add to project", name it, and
  they leave the job list. The project appears in the left sidebar beside your
  conversations, knowledge base and files, showing how many jobs it holds and
  how much disk they take. It can be renamed, opened to see what is in it, and
  downloaded as one zip.

  That zip has a spreadsheet at the top listing every job in it by name,
  method, program, status, date and result. A directory of engine output files
  says nothing about which calculation produced which, and this is what makes
  an archive worth coming back to a year later. Underneath it, each job's files
  keep the names its program gave them, so an unpacked ORCA job still has an
  `input.inp` you can rerun.

  Nothing is hidden permanently. "Show archived" brings archived jobs back into
  the job manager, each labelled with its project, and one click sends any of
  them back; several can go back at once from inside the project. Typing a
  project's name into the job search finds its jobs. A job lives in one project
  at a time, so filing it into another moves it rather than copying it.

  Deleting a project asks which of two things you mean, every time, with
  neither preselected: delete just the grouping, and the jobs return to the job
  list untouched, or delete the results too, which asks you to type the
  project's own name first. There is also a "delete all my projects" in the
  account danger zone, which does take the jobs with it.

  Archived jobs are not exempt from the storage quota, deliberately, because a
  category nothing can reclaim would let a quota fill up with data nothing
  could free. They are the last thing it reaches for instead: everything
  unfiled goes first, whatever the dates say.

  Two notes on how it works, since both were deliberate. Filing a job into a
  project never moves its files; it is a label, and the job directory stays
  exactly where the quota accounting, the conversation panel and every download
  route already look for it. And a project download is streamed rather than
  built in memory: a single orbital cube runs to several megabytes, and a
  study-sized archive assembled in a worker thread would be hundreds. A
  200 MB archive now costs the server about a megabyte of memory to serve.

- **Three more levels of theory on PySCF: NEVPT2, MC-PDFT and L-PDFT.** All
  three build on a CASSCF wave function, so each needs an active space stated
  the way CASSCF does, and any of them can start from a previous job's
  converged orbitals. MC-PDFT and L-PDFT also need an on-top functional, which
  is a different thing from a Kohn-Sham one and has its own field on the
  approval card: tPBE and ftPBE rather than B3LYP or PBE0.

  What each one can do was settled by running it here rather than by reading
  the documentation, and the answer is not uniform. MC-PDFT and L-PDFT give
  energies, excited states, gradients on both ground and excited states,
  non-adiabatic couplings, geometry optimization, constrained optimization,
  frequencies and optimize-then-frequencies. NEVPT2 gives energies and excited
  states only, because PySCF has no NEVPT2 gradient at all; asking it to
  optimize a structure or take frequencies now says that, and says what to use
  instead, rather than starting a job that cannot finish.

  Of the three, none gives you transition intensities, so a UV/Vis spectrum is
  refused up front, naming the missing intensities, instead of sampling a whole
  ensemble and finding nothing to broaden at the end of it.

- **CMS-PDFT, which is the one that does give intensities.** PySCF computes
  transition dipoles for exactly one multi-state pair-density variant, and it
  is this one rather than L-PDFT. So CMS-PDFT is now the way to get a UV/Vis
  spectrum, or a nuclear-ensemble spectrum, out of a multireference
  calculation without going to ORCA. It does everything L-PDFT does otherwise,
  and L-PDFT remains the better multi-state method when intensities are not
  what you are after.

  Excited states from all four of these now mean states of the same
  multiplicity as the ground state, matching the convention TDDFT has always
  followed here. This is not cosmetic: asked for several roots, the underlying
  solver returns the lowest of any multiplicity, and a transition from a
  singlet ground state to a triplet has an intensity of exactly zero. Every
  CMS-PDFT oscillator strength came back as numerical noise until the state
  average was made spin-pure.

### Added

- **A thermochemistry breakdown: what separates an electronic energy from a
  free energy.** Zero-point, thermal and entropy contributions as a waterfall,
  so you can see which correction is actually deciding the number. Frequency
  jobs run from now on record the electronic energy the rest of their
  thermochemistry was already built from; earlier ones did not, and cannot be
  charted without re-reading their raw output. BAGEL frequency jobs still
  report no thermochemistry at all, and the chart says so rather than guessing.

- **Four charts from data your jobs already produced and nothing showed.** Ask
  for the molecular orbital levels around the gap, how an optimization
  approached its minimum, each excited state's energy and brightness with the
  orbitals it involves, or how a Wigner ensemble's samples are spread. They
  restyle, download and attach like every other plot, and an optimization now
  saves its trace automatically the way a spectrum does.

  A molecular-orbital diagram is refused for a CASSCF job rather than drawn.
  Those export natural orbitals, which carry occupancies but no orbital
  energies, and a diagram would show a stack of levels at zero and a
  HOMO-LUMO gap measured from a number nobody calculated.

- **Two spectra can be subtracted instead of overlaid.** Once two methods
  agree closely an overlay stops answering how they differ, because the curves
  sit on top of each other.

- **The sticks under a UV/Vis spectrum are named.** They were always drawn and
  never labelled, so you could see a band had two transitions under it and not
  which states they were. The brightest few now carry their state and
  oscillator strength.

- **A legend can be told to sit beside a chart instead of on it.** Ask for the
  legend "outside" and it leaves the data alone, which is what a comparison of
  seven methods needs. Spectra also make room for their own legend now: it used
  to sit on the tallest peak, invisibly at the normal font size and
  unmissably once you enlarged the text.

- **An x axis can be converted, not just relabelled.** A scan coordinate can be
  drawn in different units the same way a y axis always could.

- **Plots can be downloaded as SVG or PDF, not only PNG.** Ask for a vector
  format and the download hands you one, at whatever size and font you set. The
  app still shows a PNG on screen, because a PDF cannot be displayed in a web
  page and a chart you can see is worth more than one you cannot.

### Changed

- **A CASSCF job that needs oscillator strengths now runs on BAGEL by
  default**, rather than ORCA. Both engines compute them, so this is a
  preference rather than a capability, and ORCA still runs the job if you name
  it. Nuclear-ensemble spectra follow the same route, since they always
  compute intensities.

### Fixed

- **BAGEL now computes oscillator strengths for CASSCF, so a CASSCF UV/Vis or
  nuclear-ensemble spectrum can be run on it.** BAGEL could always do this; the
  app never asked. It builds the block that produces transition dipoles only
  for CASPT2, so a CASSCF job with intensities switched on had the request
  quietly dropped, returned energies with nothing beside them, and said nothing
  about why. A fifty-sample ensemble is the expensive version of that: fifty
  calculations, no spectrum at the end of them.

  A run that asks for intensities and does not get them now says so instead of
  leaving a blank. Nothing changes for a job that did not ask, and a job that
  names no engine still goes to ORCA. Ask for BAGEL and you get BAGEL.

  Existing ensembles that already finished without intensities cannot be
  repaired after the fact and need re-running.

- **"Make the font bigger" now makes the font bigger.** Asking for larger text
  on a plot set one size that governed almost nothing: the title, the axis
  labels, the tick numbers and the legend each carried their own fixed size,
  and every one of them overrode it. The plot redrew looking identical, which
  reads as the app ignoring you. The font size is now the base that all four
  scale from, and naming one of them specifically still wins. An unstyled plot
  is drawn with exactly the sizes it always was.

- **Three more plots that quietly refused to be restyled.** A comparison bar
  chart threw the whole style block away before drawing. A nuclear-ensemble
  spectrum overwrote it with the calculation's own settings, so it was the one
  spectrum in the app that could not be retitled, and it filed the calculation
  away as though that described the chart. A distribution of bond lengths or
  angles took no styling at all and answered "cannot redraw" to any edit. All
  three now behave like every other chart. One visible side effect, worth
  knowing if you compare an old distribution against a new one: distributions
  were the last chart still drawing on matplotlib's own smaller default text,
  and they now use the same sizes as everything else.

- **Asking for an SVG or a PDF says it is not available yet, rather than
  handing back a PNG.** The option had been accepted and read by nothing since
  it was written: plots are saved, served and downloaded as PNGs throughout.
  Real vector export is the next piece of work on this; until then the answer
  is honest.

- **The concurrency benchmark says when it cannot measure, instead of
  guessing.** It judged how much this app adds on top of the model server by
  dividing one measurement by another, on a machine whose GPU is shared with
  other people's work. It now takes that baseline twice in the same run, and
  the two readings have come back as far apart as three-to-one, one of them
  claiming four users at once were faster than one. When the two disagree,
  the split between the app's share and the host's is reported as unavailable
  rather than asserted. The plain timings are still printed, since those are
  what somebody actually waits.

  It also takes more samples on both sides, which was worth doing on its own.
  What none of it supports is the old reading that this app roughly doubled
  the model server's penalty. What remains is the model server's memory: each
  simultaneous conversation needs its own key-value cache, and at this
  model's context length one of those fills most of a card. README.md already
  said so.

- **The whole-account download no longer holds your whole account in memory.**
  "Download all my data" built the entire zip in memory before sending a byte
  of it, which for a real account is the largest archive this app can produce.
  It now streams, the same way a project archive does. Measured on an account
  holding a 200 MB job: the server's memory use while sending it went from the
  size of the archive to nothing measurable. What you get is unchanged, down to
  the paths inside the zip.

- **The collapsed sidebar's icons do something now.** Conversations, Knowledge
  base, Files and Projects each showed an icon that told you the section
  existed and did nothing when clicked, so the only way in was to expand the
  sidebar by hand and then open the section: two gestures for one intention.
  Each icon now opens the sidebar onto its own section and scrolls to it. Which
  sections are open is also remembered between visits, as the right-hand panel's
  already were.

- **The instrument panel no longer drags the rest of the window up with it.**
  With the molecule viewer open and the panes below it expanded, a scrollbar
  appeared that pushed the sidebar and the chat pane upward and left a black
  band along the bottom of the screen. Closing the molecule pane made it go
  away, which was the clue: that pane is the tall one, and nothing in the
  instrument panel could shrink to absorb it.

  Three things had to line up for it. The panel's sections cannot compress, and
  the molecule one has no size limit at all, so an open 3D viewer plus the job
  and plot lists comes to more content than the panel has room for on a shorter
  window. The panel had no scrollbar of its own, so the excess escaped it. And
  the row holding the three panels had been left able to scroll vertically,
  which was never intended: it was asked only to handle horizontal overflow,
  and the browser quietly enables the other direction along with it. So the
  overflow scrolled the entire layout rather than the one panel that had too
  much in it.

  The instrument panel now scrolls its own contents, the job manager keeps a
  usable minimum height instead of being squeezed to nothing on the way, and
  the row is pinned so no panel can ever scroll the whole window again.

- **Every job now really does run on four cores, on all three engines.** The
  per-job core budget was a number the app believed rather than one it applied.
  PySCF was the worst of it: the line meant to cap it set an environment
  variable after the library had already read it, so a PySCF job quietly opened
  one thread per core on the whole machine (255 of them here) and spent its time
  contending rather than calculating. On a benzene Hartree-Fock test that made
  it twice as slow as the same job on four cores. ORCA was asking for four MPI
  ranks and then letting each of the four use every core, which its own manual
  says not to do, and that cost about a third of the wall time on a benzene
  def2-TZVP run. BAGEL was reading the one variable that was set correctly, but
  only by luck: it prefers `BAGEL_NUM_THREADS`, which nobody was setting, so on
  a host whose profile happened to define it the job ran at whatever that said.

  All three are now given their thread limits when their process is created,
  which is the only moment any of these libraries will listen. An ORCA input the
  app did not build itself, a raw input or one you edited on the approval card,
  has its `%pal` clamped to the same budget on the way to disk, and an input
  asking for fewer cores keeps what it asked for. Orbital cubes rendered on
  demand, which run inside the API process rather than as a job, are capped too.

  This also repairs the admission gate, which decides whether the host has room
  by assuming each running job costs four cores. That assumption was off by a
  factor of sixty for PySCF, so a machine the scheduler believed was
  comfortably loaded could be oversubscribed many times over. Nothing about the
  concurrency limits changes: they count jobs, not cores.

- **A state-averaged CASSCF no longer returns triplets among its excited
  states.** Asked for several states of a closed-shell molecule, the
  underlying solver returned the lowest states of *any* spin, so what came
  back labelled S1 could be a triplet: on a water test case three requested
  states came back as singlet, triplet, singlet. Every root now has the
  multiplicity you declared for the molecule, which is what TDDFT has always
  done here. Excitation energies from a state-averaged CASSCF, CASPT2, NEVPT2
  or MC-PDFT calculation will move as a result, by around 2 eV on that test
  case. A single-state calculation is unaffected, and so are ORCA and BAGEL,
  which never had the problem.

- **A state-averaged CASSCF now optimizes and takes frequencies on a state,
  not on the average of several.** Asking for a geometry optimization or a
  frequency calculation from a CASSCF averaged over several roots quietly
  worked on the mean of those roots, which is not a surface any molecule moves
  on. The frequencies that came out of it carried spurious zero modes, and the
  enthalpy and Gibbs energy were built on that mean as well. Both now follow
  one state, the ground state unless you name another, and the job reports
  which one it followed. A single-root CASSCF is unaffected.

- **The capability table in the README claimed a spectrum PySCF cannot
  produce.** It listed EOM-CCSD and CASSCF under nuclear-ensemble UV/Vis
  spectra for PySCF, which neither can do there for want of oscillator
  strengths; those requests have always been routed to ORCA instead. The table
  is now derived from the capability registry rather than maintained by hand.


- **Asking for a number of excited states now gets you that many.** Asking for
  two excited states from CASSCF or CASPT2 used to run a two-state
  calculation, which is the ground state plus one excited state, because the
  count those methods take includes the ground state and the app expected that
  conversion to be made before the job was set up. The approval card showed the
  number you had given, so there was nothing to notice. You now say how many
  excited states you want, the same way for every method, and the app works out
  the extra state a CASSCF needs; the approval card shows both numbers.

- **The agent no longer invents details of a job it cannot see.** Asking for
  the ground-state energies of several calculations in one table could produce
  a confident answer with a wrong active space in it, and a paragraph of
  reasoning built on that wrong number. The cause was that every result it
  looked at carried a full table of molecular orbitals, one row per orbital,
  which crowded out the very results it had just gone to fetch. Those tables
  are still there and the orbital viewer still shows them; they are simply no
  longer pushed at the agent, which asks for the handful of numbers it needs
  instead. Answers about several calculations at once are now assembled from
  the stored results in one step, and if anything genuinely had to be dropped,
  the agent is told so and fetches it again rather than filling the gap.

- **HOMO and LUMO energies are reported as unavailable when they are.** A
  CASSCF or CASPT2 calculation run through BAGEL has no orbital energy for the
  orbitals in its active space, which is a property of the method rather than
  a gap in this app. Those are now reported as unavailable, with the reason,
  instead of as zero.

### Added

- **Any plot can be restyled by asking.** Titles, axis labels, font sizes,
  figure size, resolution, grid lines, axis ranges, legend position, colours,
  line and marker settings, and PNG/SVG/PDF output. This works on every kind
  of plot, including the UV/Vis, IR, nuclear-ensemble and energy-surface
  spectra, which previously could not be adjusted at all after they were
  drawn; changing one keeps the same plot and adds a version rather than
  making a new one. Asking for a setting that does not exist gets you the
  list of the ones that do. A plot you do not restyle looks exactly as it did.

- **A single reply can show more than one chart**, so "plot each method
  separately" is now something the agent can actually do.

### Changed

- **Declining a job now answers you straight away.** Turning down an approval
  card used to be followed by a full agent turn whose only job was to ask what
  you wanted to change, which meant sitting in front of an empty chat pane for
  the best part of a minute after an action you had just taken yourself. The
  app writes that reply itself now, naming the calculation you turned down the
  same way the job list does, and it leaves the setup in place so you can say
  what to change and carry on from there. If you had asked for more than one
  thing in the same breath, the agent still picks up the rest.

- **Cancelling a job is acknowledged immediately.** Stopping a calculation
  used to be followed by a full agent turn to tell you it had stopped, which
  was a slow way to learn something you had just done yourself and the jobs
  list had already shown you. The app writes that line itself now, naming the
  calculation the same way the job list does. Nothing else about cancelling
  changed, and a job that finishes or fails on its own is unaffected.

- **A calculation you asked to run reaches its approval card in one step.**
  Once the agent had everything it needed, it used to take another full turn
  purely to hand the job over for your approval, and sometimes it simply did
  not: about one calculation in five stopped there, set up and ready, with no
  card ever appearing. The card now comes up as soon as the last question is
  answered. Nothing else about approving changed. You still see the exact
  input, and nothing runs until you say so. Asking to see an input without
  running it works as before and stops short of the card.

- **Long conversations stopped getting slower.** Past about forty messages
  the app rebuilt the front of what it sends the model on every single step,
  which threw away the work the model had already done on the identical text
  a moment earlier. On this machine that was roughly ten seconds per step,
  several times a turn, and it looked like the shared graphics card being
  busy rather than anything the app was doing. The same conversation now
  costs a fraction of a second per step. Nothing about what the agent
  remembers has changed.

### Fixed

- **The agent no longer offers to use tools that were removed.** Six places
  where a calculation could be refused ended by telling the agent to call
  something that no longer exists, so instead of a clear explanation you
  could get it confidently trying a step that was never going to happen.
  Setting a scan's end structure and asking for an exact published basis set
  were the two worst, each naming two removed tools in one sentence.

- **Background updates no longer appear as though you wrote them.** When the
  app told the agent about a finished job, or you pressed Troubleshoot, that
  message was shown in the transcript as one of yours, complete with the
  words "system notice, not from the user" inside your own message bubble.
  They now read as what they are: a short, quiet line saying what the app
  did.

- **The limit on how many jobs run at once is now actually a limit.** It was
  enforced within a single pass of the scheduler's dispatcher and not between
  passes, and a burst of submissions makes those passes fire back to back, so
  a deployment configured to run one job at a time could start several. What
  the check counts is jobs whose status file says they are running, and a job
  that has just been let through has not written that file yet, so each pass
  started counting from zero against a picture that had not caught up. The
  scheduler now tracks what it has let through until the job is finished
  with, which also restores the round-robin turn-taking between users that
  this made look broken.

- **An update no longer reports a healthy deployment as dead.** The health
  check it runs after restarting the stack was hardcoded to port 8443, so any
  deployment that publishes on a different port -- which the shipped override
  example shows you how to do -- waited out the full five-minute timeout and
  was then told it had never come up. It now asks Docker Compose which port
  the deployment actually publishes, and tries every address compose names.

- **`scripts/update.sh` can now advance a deployment that shares a directory
  with its git checkout.** It decided whether there was anything to do by
  comparing `git HEAD` against the target, which is the checkout's opinion
  rather than the deployment's. Where the two are the same directory, which is
  what `scripts/install.sh` produces, committing without rebuilding made the
  update report "already up to date" and send you to a hand-run
  `docker compose up --build` that skips the backup, the impact report and the
  job drain. The api image and the built frontend bundle now each record the
  commit they were built from, and the update reads those back. A build it
  cannot identify counts as out of date rather than current, so the first run
  against an existing deployment rebuilds once and is accurate from then on.

- **A failed update no longer becomes the baseline you roll back to.** The
  line recording an update was written to `.update-log` before the health
  check had been considered, so a deployment that never came up was recorded
  exactly like one that did. It is now written after the verdict, and
  `--rollback` returns to the most recent commit the deployment is known to
  have actually run rather than simply to the previous one.

- **`tests/run_backend.sh` no longer wipes every job on the stack.**
  `p1_07_purge_status_source.py` exercises the deployment-wide job purge, and
  it was in the default run, so a full suite run destroyed every job on the
  stack rather than only the ones the suite created. It is now opt-in, the way
  `sec_10_*` already was, and has to be invoked by name.

- **Recovery advice after a failed update now matches what the update did.**
  `--rollback` moves code and nothing else, so after a destructive change it
  would leave the old code running against a migrated database. Every failure
  path used to suggest it anyway. The ones where it cannot work now name the
  backup directory and `scripts/restore.sh` instead.

### Changed

- **Approving a job now confirms it instantly.** The message that follows a
  submission used to be written by the model, which meant waiting through a
  full agent turn to be told something the app already knew: that the job you
  had just approved was running. That is a full model turn, tens of seconds on
  this machine, and the answer was the same every time, because the wording was
  dictated to the model rather than composed by it. The app now
  writes that confirmation itself, the moment the job starts, naming the job
  the same way the job list and the drawer do.

  Asking for several calculations at once still works the way it did. When you
  do, the agent takes the turn back after the confirmation and puts the next
  approval card in front of you by itself; the difference is that you see the
  first job confirmed straight away instead of at the end. A job you decline,
  and any submission that turns out to be invalid, still get a real reply from
  the agent, since those are the cases where there is something to say.

### Fixed

- **A job finishing while you are setting up the next one no longer eats the
  approval card.** Reported as "where is the card for the casscf job?", asked
  twice in one conversation. A completed job's summary is not a message the
  app appends, it is a full agent turn, and starting one while the graph is
  paused at an approval discards that approval outright: the card disappears,
  the submit step is left permanently unfinished, and clicking Approve
  afterwards does nothing at all. Assembling a calculation now takes
  precedence over reporting on one. Summaries wait from the moment you ask for
  a calculation until it ends in a submission or a rejection, then arrive
  together in a single message rather than one per job. The jobs list still
  shows each job finishing as it happens, so nothing looks stalled while a
  summary waits.

  Two smaller pieces of the same fault came with it. The old check for "is an
  approval open?" ran before the code took the conversation's lock, so during
  a turn that takes a minute the check was made about thirty times, always
  before the card existed, and was then let through at exactly the wrong
  moment; it is now re-checked with the lock held. And a job *failing* turned
  out to destroy an open card the same way, which had nothing to do with
  drafting: a death notice now waits out that one window. It is otherwise
  still delivered immediately, mid-draft included, since finding out that a
  calculation died should not wait for the next one to be written.

  `QC_AGENT_DRAFT_HOLD_SECONDS` (default 900, `0` to wait indefinitely) covers
  a draft that is started and then abandoned, so an unfinished setup cannot
  silence a conversation's summaries for good.

- **A CASSCF or CASPT2 request with no virtual space is refused before the
  approval card, on every task rather than only on scans.** The check existed
  but was called from the scan builder, so an ordinary single point -- which
  is the shape the problem was first found in -- went straight to a card. It
  also tested CASPT2 alone, when BAGEL CASSCF fails the same way and worse:
  water in STO-3G with a (4,4) active space leaves nothing above the active
  orbitals, and BAGEL neither returns a result nor stops, filling its output
  with `cblas_dgemm` errors while the job runs on. The identical calculation
  in cc-pVDZ finishes in about eight seconds. Someone who approved the first
  card waited forever for a job that had already failed. The message now says
  why an empty virtual block is fatal for the method actually requested,
  rather than describing a CASPT2 perturbation to a CASSCF user.

- **A functional written where the level of theory goes is moved to the right
  field instead of being dropped.** Asked for "a B3LYP-D3 single point", the
  model writes `method="B3LYP-D3"`, because that is how a chemist says it.
  The method was correctly rejected and the dispersion correction then
  vanished: the card read `B3LYP` under a note saying "which is how ORCA
  spells it" -- true of what it had been handed, and quietly wrong about what
  was asked for. The draft path already moved a subtype written on the method
  axis onto the task axis; this is the same move one axis over. A card now
  carries `B3LYP D3BJ` and names `D3ZERO` as the other damping. A request the
  engine genuinely cannot settle on its own, PySCF's bare `-D3`, still goes
  to the user rather than being resolved silently.


### Added

- **A nuclear-ensemble spectrum starts every sample from the frequency job's
  orbitals.** A CASSCF or CASPT2 ensemble runs one excited-state calculation per
  sampled geometry, and each used to start from its own fresh guess. Nothing
  held the active space to the same orbitals from one sample to the next, so
  neighbouring geometries could converge to different spaces and the pooled
  spectrum quietly mixed them. The job to take orbitals from was already known,
  since an ensemble cannot exist without the frequency calculation it samples,
  so it is filled in rather than asked for. It appears on the approval card, so
  you can point it at a different job or take it out, and a frequency job that
  cannot supply orbitals, one run at DFT or on another program, is reported and
  falls back to a fresh guess per sample. Works from a plain frequency job or an
  optimization-plus-frequency one.

- **Every orbital now says how far outside the molecule it lies.** The table
  named each orbital's character, and every measurement behind that label
  assumed the orbital sits on the atoms. One that does not got a label anyway,
  which on a set of diffuse functions describes nothing: water in aug-cc-pVDZ
  has five such orbitals, and each was being given an atom to sit on by a
  population analysis of something centred nowhere. Each row carries the fraction of its
  own density beyond the molecular envelope, and past the halfway mark it is
  flagged and stops claiming an atom. Occupied orbitals sit below 0.01 and a
  basis without diffuse functions produces nothing above 0.3, so if nothing is
  flagged the note tells you how to tell "no such orbital" from "this basis
  could not have shown one". On water, cc-pVDZ finds nothing while aug-cc-pVDZ
  finds five, the lowest just under 1 eV. It is a measure of spatial extent
  rather than a Rydberg assignment, which would need a principal quantum number
  and a quantum defect. PySCF and BAGEL; ORCA tables carry neither this nor
  character, for the same reason.

- **Choose the active orbitals yourself.** A CASSCF or CASPT2 active space has
  always been chosen by count: ask for twelve electrons in nine orbitals and the
  engine takes the nine orbitals around the HOMO. If you have looked at a
  previous job's orbitals and know which nine you want, you can now name them,
  and the calculation uses exactly those. BAGEL and PySCF both support it; ORCA
  has no way to express it, and asking for it on an ORCA job offers you the two
  engines that do rather than quietly ignoring the request. The list is only
  ever used when you name the orbitals yourself. The agent will not assemble one
  from orbital numbers that happen to be lying around in the conversation,
  because a guessed active space looks exactly like a chosen one on the approval
  card and computes something else entirely.


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

- **An orbital could be labelled with a bond the molecule does not have.** When
  two atoms carried most of an orbital, the table named them as a pair, and the
  hyphen in "C1-C2" reads as a bond. Nothing checked that the two atoms were
  bonded. In uracil that made 24 of the 33 pair labels wrong, the worst of them
  naming the two carbonyl oxygens on opposite sides of the ring, 4.53 angstroms
  apart, once as a sigma bond and once as a pi bond. It is almost entirely a
  problem with empty orbitals, which are typically the out-of-phase combination
  of two equivalent groups rather than a two-centre bond, and those are exactly
  the ones you read off the table when choosing an active space. The
  measurement was never wrong, only the wording, so a pair that is not bonded
  now falls back to "delocalized over" the same way three atoms already did.
  Real bonds are still named as bonds.

- **PySCF projected reused orbitals through the wrong geometry.** Seeding a
  CASSCF from an earlier job's orbitals associates them with that job's
  structure, and the structure it used was the one the source job started from.
  For anything that moved the nuclei, an optimization or the optimization half
  of an opt-plus-frequency run, the orbitals were written at the structure it
  finished on instead, so the guess was built through basis functions centred on
  the wrong atoms. As usual nothing said so: a guess came back and the
  calculation converged. It now uses the optimized structure whenever the source
  job produced one. PySCF only; BAGEL and ORCA store the geometry with the
  orbitals and handle this themselves.

- **Reusing a BAGEL job's orbitals also silently reused its geometry.** Starting
  a CASSCF or CASPT2 calculation from a previous job's converged orbitals is
  meant to save the fresh guess and nothing else. BAGEL stores the geometry in
  the same reference archive, though, and reads both back unless told not to,
  so the calculation ran on the structure the orbitals came from rather than
  the one that was asked for. Nothing about that looks wrong from the outside:
  the job converges, reports results and writes a full summary, just for the
  wrong molecule. Every job type that can reuse orbitals now keeps its own
  geometry and projects the archived orbitals onto it.

- **A pi orbital could be reported as a lone pair.** The orbital table names each
  orbital's character, and it decided between a lone pair and a bond by asking
  which atoms carried the orbital before asking what shape it had. Any orbital
  with one atom above 15% and no second one was called a lone pair, whatever it
  actually looked like. On a uracil CASSCF job that caught orbital 25, which is
  a pi orbital carrying 37% on one nitrogen and the rest spread over three more
  atoms. The row said "n" and, in the same breath, "delocalized over N2, N1, O8,
  C3". A lone pair is now required to sit on one atom in earnest, which is the
  same test that already decided whether the orbital could be named after an
  atom at all, so a row can no longer contradict itself.

- **Linear molecules had half of every pi pair labelled sigma.** A linear
  molecule passes the test for being planar, since all its atoms do lie in a
  plane, but it lies in infinitely many of them and the one that gets picked is
  arbitrary. Its pi orbitals come in degenerate pairs that a calculation may
  return in any mixture, so measuring them against an arbitrary plane reported
  the mixture rather than the orbital: on CO2 that gave two pi orbitals where
  there are four, with the other two called sigma. Linear molecules are now
  measured by rotating about the molecular axis instead, which has each
  degenerate pair as a whole eigenspace and so cannot be thrown by the mixture.
  CO2, acetylene, HCN, N2 and CO all come out right, including CO's carbon lone
  pair, and the check covers the first two.

- **Orbital shape was decided from a single probe point.** Telling sigma from pi
  meant sampling the orbital just above and just below the molecular plane and
  comparing signs, which is the right question asked in a fragile way: probe
  above a bond midpoint and an antibonding orbital has a node there, probe above
  a nucleus and an in-plane lone pair has a node there. Both happen constantly.
  On the same uracil job the pi* orbital 30 measured 0.0025 where its real scale
  was 0.29, and two oxygen lone pairs measured 0.001 and 0.003, so three
  orbitals had their labels decided by which way the numerical noise pointed.
  Each orbital is now integrated against its own mirror image in the plane,
  which asks the whole orbital rather than one point. On that molecule every
  orbital comes back at exactly plus or minus one, with no threshold left to
  tune. `scripts/validate_orbital_character.py` is the standing check.

- **Dominant transitions were measured from the wrong reference.** A CASSCF or
  CASPT2 job reports which orbital an electron moved out of and into, which only
  means anything relative to a reference configuration. That reference is picked
  as the heaviest one across all the states, deliberately, because a
  state-averaged calculation does not guarantee that the lowest root is the
  closed-shell-like one. BAGEL and PySCF print raw determinants, though, so an
  open-shell singlet comes out as two lines that get correctly summed into one
  configuration while a closed-shell determinant has nothing to sum with, and
  the comparison quietly favoured the open-shell one. On a three-root uracil
  CASSCF that made an excited state's own leading configuration the reference
  for every state: the ground state was reported as an excitation, the state
  that had become the reference was reported as having none, and the rest were
  described as transitions into an orbital that is doubly occupied and can
  accept nothing. The reference is now chosen before the spin partners are
  summed. ORCA was never affected, since its table is already spin-adapted.


- **A pasted BAGEL calculation was described as the wrong one.** A BAGEL input
  is a script rather than a declaration: a CASSCF run opens with a Hartree-Fock
  section because those orbitals are the starting guess, and a CASPT2 run
  carries a CASSCF section ahead of its SMITH one for the same reason. The app
  read whichever came first, so a three-state CASSCF calculation was announced
  as a Hartree-Fock ground-state energy. It now reads the highest level of
  theory the input contains, and counts the states, on BAGEL and on ORCA alike:
  neither program has a keyword that says "excited state" for a multireference
  method, so the number of roots is the only thing that does.

- **Reading a pasted input got better across all three programs.** ORCA writes
  the convergence level and the coordinate system into the optimization keyword
  itself, so `TightOpt`, `COpt` and `L-Opt` were read as inputs asking for
  nothing in particular and therefore as single points. It writes the
  approximation family in front of the method too, so `DLPNO-CCSD(T)` and
  `RI-MP2` now resolve to coupled cluster and MP2, and `STEOM-DLPNO-CCSD` to
  EOM-CCSD rather than to plain coupled cluster. The composite methods and the
  wB97 family are recognised as DFT, with the exception of HF-3c, which is
  Hartree-Fock. A PySCF script's method is read the same way a BAGEL input's
  is, since a script builds the SCF object before the CASSCF one that wraps it,
  and its state count is read from either `nroots` or a state average. A pasted
  transition-state search now says plainly that it was not recognised, instead
  of being described as the nearest job type this app does have; it still runs
  verbatim, which is what pasting it was for.

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
