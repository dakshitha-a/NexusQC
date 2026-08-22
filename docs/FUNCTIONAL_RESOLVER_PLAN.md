# Plan: a per-engine DFT functional resolver

Status: implemented 2026-08-22, in `app/chemistry/jobs/functional.py`.
Kept as the record of why each rule exists and what was measured to
justify it; `docs/PARSER_GAPS.md` carries the individual naming traps.

Every measurement below was taken on this host against the running dev
stack, PySCF 2.14.0, ORCA 6.1.1, BAGEL 1.2.2, not read out of a manual.

## Why

People name a functional the way they say it out loud: "b3lyp/631gd",
"r2scan and ccpvdz", "wb97x-d/6-31g\*". Every other parameter in a job
draft gets mechanically repaired before it reaches an engine. The
functional does not. `param_normalize.py` has `normalize_method()` and
`normalize_basis()` and no equivalent for `functional`, so whatever
string the model extracted is written verbatim into the engine's input
file.

The only stage that looks at it is `suggest_functional_options()`, which
is a *suggester*, not a resolver: `difflib.get_close_matches` at cutoff
0.5 over a per-engine name pool, offered as a menu, never written back
into the draft.

That is survivable when the engine complains. ORCA rejects an unknown
keyword outright, the job fails fast, and the troubleshoot flow reads the
error and proposes a fix. It works, at the cost of a round trip, a failed
job and a second approval.

It is not survivable when nothing complains. Measured on water/STO-3G,
every row converged, nothing printed a warning:

| user typed | today's top suggestion | what it computes | E (Eh) | error |
|---|---|---|---|---|
| `r2scan` | `MGGA_X_R2SCAN` | r2SCAN exchange, no correlation | −74.966394 | +0.320 |
| `m062x` | `MGGA_C_M062X` | M06-2X correlation, no exchange | −66.299921 | +9.013 |
| `wb97x-d` | `HYB_GGA_XC_WB97XD` | ωB97X-D with no dispersion term | −75.306429 | - |
| `b3lyp-d3` | `B3LYP` | B3LYP, dispersion silently dropped | - | - |
| `tpssh` | `TPSS0` | a different hybrid entirely | - | - |

Reference: `r2scan` −75.286778, `m06-2x` −75.312665, `tpssh` −75.324533.

The troubleshoot flow cannot reach any of these, because there is no
error to read. Closing that is the point of this work; one-shot
resolution is the same fix seen from the user's side.

## Scope: DFT only, and only on two engines

**Why no other method needs this.** `hf`, `casscf`, `caspt2`, `ccsd`,
`eom_ccsd` are a closed set of five, resolved through a hand-written
synonym table and a normalizer that validates its own rewrites. Basis
sets have their own oracle in `_pyscf_basis_is_valid`. Neither namespace
contains members that are valid *and* incomplete.

libxc does. Of its 981 codes: 278 compound (`_XC_`), 363 exchange-only
(`_X_`), 224 correlation-only (`_C_`), 77 kinetic-energy (`_K_`), and 39
bare aliases. A list that itself mixes complete functionals (`B3LYP`,
`CAMB3LYP`) with components (`B88`, `LDA_X`). All 981 parse. DFT is the
one field where "this is a real libxc name" and "this is the calculation
you asked for" came apart.

**Why BAGEL is out entirely.** Confirmed three ways: 48 scraped BAGEL
manual pages contain zero matches for `dft`/`b3lyp`/`kohn-sham`/
`exchange-correlation`; `strings` on the BAGEL 1.2.2 binary finds no
`libxc`/`xc_func`/`b3lyp` symbols; and the capability registry has no
`bagel + dft` row at all. The app already refuses correctly and one layer
earlier than this work touches, `route_engine("dft", …, "bagel")`
returns `engine=None`, `"BAGEL cannot run this job."`, with
`alternatives=('pyscf', 'orca')`, for every DFT task including TDDFT
(`single_point/ee`). A BAGEL DFT draft never reaches the stage where a
functional would be resolved, so the resolver is simply never invoked for
it and the empty BAGEL pool in `keyword_suggest.py` stays empty and
correct.

## The asymmetry that shapes the design

Both engines have a component namespace. Only one of them is dangerous.

**PySCF** takes `MGGA_X_R2SCAN` as an `xc` value like any other and
computes with it. Silent wrong answer.

**ORCA** exposes `X_BECKE`, `C_P86`, `X_TPSS`, `X_R2SCAN`, but only as
values for `Exchange`/`Correlation`/`LDAOpt` **inside a `%method`
block**, a different namespace from the simple-input line. `! X_TPSS` is
`UNRECOGNIZED OR DUPLICATED KEYWORD(S)`. Confirmed by running it.

So ORCA cannot silently compute half a functional. Its failure mode is a
wasted job, not a wrong number. Both are worth fixing; only one of them
can mislead a result that gets written up.

## Design

### 1. Completeness oracle (PySCF)

Validated during planning, not hypothesised.

```
_, fn_facs = libxc.parse_xc(name)          # component (id, factor) pairs
names       = [ID2NAME[int(i)] for i, _ in fn_facs]
kinds       = {kind_token(n) for n in names}      # X / C / XC / K
COMPLETE   iff (X or XC) and (C or XC), and K absent
```

`ID2NAME` inverts `libxc.XC_CODES`, preferring the `FAMILY_KIND_NAME`
form over a bare alias when both map to one id. The prefixed name is the
one carrying the kind token.

**Two traps confirmed live.** `XC_CODES` values are `numpy.int32` for 942
of 981 entries, so an `isinstance(v, int)` filter silently drops almost
the entire table. This cost a debugging round during planning. And 20
values are not ids at all but recipe strings (`REVPBE0` is
`".25*HF + .75*PBE_R, PBE"`). Reading those as alias indirection and
skipping them, as an earlier draft did, lost `revpbe0` from the pool
while keeping `revpbe`.

Verified verdicts: `r2scan` COMPLETE, `MGGA_X_R2SCAN` EXCHANGE-ONLY,
`MGGA_C_M062X` CORRELATION-ONLY, `tpssh` COMPLETE, `GGA_K_REVAPBE`
KINETIC, and, the case a structural prefix check alone would miss,
bare `B88` correctly EXCHANGE-ONLY.

Anything not COMPLETE is never offered and never accepted.

### 2. Runnability oracle (PySCF)

Parsing is not running. `pyscf.scf.dispersion.parse_dft(name)` raises
`NotImplementedError` for a hard-coded blacklist, `wb97x-d`,
`wb97x-d3`, `b97m-d3bj2b` and others. That no install can work around.

**Order matters, and is the opposite of the obvious one.** `parse_dft`
runs *first*: it resolves composites such as `wb97x-3c` that `parse_xc`
rejects outright, and returns `(xc, nlc, disp)`. `parse_xc` and the
completeness check then run on the resolved `xc`, never on the raw input.

Note this pair does not catch everything, which is what the two extra
checks in the implemented version are for: `HYB_GGA_XC_WB97XD` passes
both and runs, silently omitting dispersion. Raw `FAMILY_KIND_NAME` codes
are kept out of the pool entirely (nobody types those), and the blacklist
is matched on a punctuation-free key so the short unseparated spelling
`wb97xd` cannot slip past either.

### 3. A real-run verified pool (ORCA)

`keyword_suggest.py` used to state that ORCA had "no equivalent 'ask the
engine' validity oracle". That is true of library calls and false of
ORCA. A single-atom single point gives a clean binary verdict in
**~0.2 s**:

- valid → `FINAL SINGLE POINT ENERGY` / `ORCA TERMINATED NORMALLY`
- invalid → `UNRECOGNIZED OR DUPLICATED KEYWORD(S) IN SIMPLE INPUT LINE`

A full sweep of the scraped pool takes 57 s (219 candidates, 128
accepted, 91 rejected, none inconclusive). So the ORCA pool
stops being *scraped* and becomes *verified*, which is what CLAUDE.md
already demands of engine behaviour ("derived from real runs, not
documentation").

A ten-keyword pilot already found things the manual cannot tell you:

| keyword | ORCA verdict |
|---|---|
| `B3LYP`, `PBE0`, `R2SCAN`, `TPSSH`, `WB97X-D3`, `WB97X-D4`, `M062X`, `M06`, `M06L` | accepted |
| `M06-2X` | **rejected** |
| `B3LYP-D3`, `B3LYP-D3BJ` | **rejected** |
| `B3LYP D3BJ` | accepted |
| `X_TPSS`, `B97X-D3`, `WHPBE0` | rejected, confirmed scrape noise |

Two consequences. `M06-2X`, the spelling a user is most likely to type,
and the one today's suggester ranks first, is not an ORCA keyword at
all; `M062X` is. And dispersion on ORCA is a **separate keyword, not a
suffix**, so the resolver must emit different *shapes* per engine, not
merely different spellings.

The sweep needs ORCA present, so it cannot run in CI or on a host without
a licence. Run it once here, commit the verified name list as data, and
keep the scraper as the way to regenerate it, the same posture the
existing scraped manuals already have.

### 4. Normalization, so spelling stops mattering

- **Match key**: casefold, drop every non-alphanumeric. `M06-2X`,
  `m062x`, `M062X` all key to `m062x`. Matching happens on the key; what
  comes back is always the engine's own real spelling.
- **Dispersion split**: recognise a trailing `-d`, `-d3`, `-d3bj`,
  `-d3zero`, `-d4`, `-d3(bj)` and resolve `(base, dispersion)`
  separately. This is what makes `b3lyp-d3` resolvable at all. String
  distance has no way to know that dropping `-d3` changes the chemistry
  while dropping a hyphen does not.
- **Per-engine output shape**: PySCF wants one token (`b3lyp-d3bj`);
  ORCA wants two (`B3LYP D3BJ`). Verified above.
- **Never offer a raw libxc code** (`FAMILY_KIND_NAME`) in response to a
  short name. This is what keeps `HYB_GGA_XC_WB97XD` out of the menu.

### 5. A curated table, kept small

Only for requests the mechanical layers cannot reach. Every row carries
the evidence that put it there:

| request | PySCF | ORCA | note shown to the user |
|---|---|---|---|
| `wb97x-d` | `wb97x-d3bj` | `WB97X-D3` | blacklisted on PySCF; D3BJ is the supported near-equivalent |
| `wb97x-d3` | `wb97x-d3bj` | `WB97X-D3` | same |
| `b3lyp-d3` | `b3lyp-d3bj` | `B3LYP D3BJ` | `B3LYP-3C` is a composite method, not B3LYP+D3 |

If an entry can be derived by layers 1–4, it does not belong here.

## Where it plugs in

`normalize_functional(functional, engine) -> (resolved, note, options)`
in `app/chemistry/jobs/param_normalize.py`, called from
`_build_spec_or_error` in `app/agent/tools.py` immediately after
`normalize_basis`.

**The engine is already resolved at that point**. `_build_spec_or_error`
takes `engine` as a parameter, and it is registry2's resolved engine by
the time a ready draft reaches it. No restructuring needed. (The remark
in `param_normalize.py`'s docstring about running "before
`default_engine()` resolves which engine the job will actually use"
describes the basis rewrite's own history and should be corrected here.)

Four outcomes, matching what `normalize_basis` already establishes:

- **exact**, validates as given. Return unchanged, suppress the menu. A
  correct choice is never second-guessed.
- **rewrite**, one confident resolution. Rewrite the draft and add a
  `param_note`, exactly as a `6-31gd` → `6-31g*` repair is surfaced.
- **ambiguous**, several complete, runnable candidates. Hand them to the
  existing menu, which keeps its current numbering.
- **unsupported here**, valid on the other engine but not this one. Name
  the engine that can, and offer this engine's nearest supported form.

`suggest_functional_options()` then draws from the same oracle rather
than raw `XC_CODES`, so resolver and menu cannot disagree.

## Steps

1. **Oracle module.** PySCF completeness + runnability, and the pool they
   imply. *Evidence:* verdict printed for every name in the tables above,
   including `B88` and `GGA_K_REVAPBE`.
2. **Normalization.** Match key, dispersion split, per-engine output
   shape. *Evidence:* `m062x` / `M06-2X` / `M062X` resolve identically on
   each engine, to that engine's own spelling.
3. **ORCA verification sweep.** Run the scraped pool through ORCA, commit
   the verified list. *Evidence:* the committed list, plus the count of
   scraped names it rejected.
4. **Curated table**, each row verified on this host.
5. **Wire in** `normalize_functional`; re-source the menu from the same
   oracle; correct the "no oracle" comment in `keyword_suggest.py`.
6. **Tests.** A table-driven `tests/backend/` script: real phrasings →
   expected resolution per engine, with the component-only class covered
   explicitly as its own regression, since that is the class that fails
   silently.

## What implementation changed about the plan

Four things the plan did not anticipate, all found by testing the oracle
rather than trusting it:

- **A fourth check was needed.** `parse_dft` returns `disp="d3"` for
  `b3lyp-d3` and `"d3"` is absent from its own `DISP_VERSIONS`; the SCF
  then dies with `ValueError: Unknown dispersion version d3`. The
  two-oracle design would have offered `b3lyp-d3` as valid.
- **A blacklist spelling loophole.** PySCF blacklists `wb97x-d` and
  `wb97x_d` but not `wb97xd`, which therefore ran and computed ωB97X-D
  with no dispersion term. Matching is on a punctuation-free key now.
- **The ORCA probe basis mattered.** STO-3G reported all 43 double
  hybrids as inconclusive (`RI-MP2 needs an AuxC basis`); recording those
  as rejections would have deleted every double hybrid from the pool.
- **A pre-existing bug surfaced.** `_build_spec_or_error`'s plain path
  passed `params` to `_keyword_options_for_job`, which reads `method`
  from that dict, but `method` is a separate argument, so the functional
  menu had never appeared for an ordinary single_point/opt/freq draft at
  all. The scan and neb_ts builders already folded it in explicitly; this
  path never did. Fixed alongside.

The curated table stayed small, as intended: three rows, one of which
(`scan` → `SCANFUNC`) exists only because ORCA's functional collides with
its own geometry-scan keyword.

## Out of scope

- **BAGEL.** No DFT, refused at routing, resolver never invoked. See
  above.
- **Basis-set resolution.** `normalize_basis` already works and is not
  part of this change.
- **Guessing at different chemistry than was asked for.** A resolver that
  cannot reach a confident answer asks; it never silently substitutes a
  functional the user did not name. That rule is what makes the rewrite
  path safe, and it is the rule `param_normalize.py` already states.

## Risk

The one real risk is a rewrite that resolves confidently to the wrong
thing. Trading a loud failure for a quiet one, which is the defect being
closed. Mitigation is the discipline the basis normalizer already uses: a
rewrite is only emitted when the result passes both oracles, and every
rewrite is surfaced as a `param_note` on the approval card before the job
runs. Nothing is rewritten out of sight.
