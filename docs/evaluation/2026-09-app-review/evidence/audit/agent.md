# code:agent — static audit of `app/agent/` + `server/routes/chat.py`/`threads.py`

Commit `0dcb865`. Read-only. Read before filing: `docs/ARCHITECTURE.md`
"The agent graph" (275-336), "The approval gate" (338-716) in full, and
`docs/MODEL_CONTEXT_BUDGET.md` in full.

**What came back clean is at the bottom.** The approval gate's core
mechanism is sound; the findings against it are about paths that reach
around it, not about the gate itself.

---

### R-000: A user can read another user's job results by passing that job's id to `POST /messages` (`job_ids`) or to the troubleshoot route
- surface: code:agent
- class: security
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `server/routes/chat.py` only. Checked every handler in that file
  for `check_owner_or_admin`; `tag_job_frame` has one for `"job"`,
  `attach_upload` scopes by caller id, `post_message` and
  `troubleshoot_job` have none. Did not check `server/routes/jobs.py`
  (it does check, on 15 handlers) or the admin routes.
- repro: as user A, own thread T. `POST /api/threads/T/messages` with
  `{"text":"summarise this","job_ids":["<user B's job id>"]}`. B's full
  `job_context_summary` (energies, geometry, orbital tables) is injected
  into A's conversation as a HumanMessage and answered by the model.
  Same with `POST /api/threads/T/troubleshoot/<B's failed job id>`, which
  injects B's spec parameters and 25 lines of B's raw engine output.
- observed: `server/routes/chat.py:631-651` (`post_message`) calls only
  `_require_thread(thread_id, request)` — a check on the *thread* — and
  passes `body.job_ids` straight through to `_run_turn`, which at
  `chat.py:361` does `job_context_summary(jid)` with no owner argument.
  `job_context_summary` (`app/chemistry/jobs/summarize.py:390`) has the
  signature `def job_context_summary(job_id: str) -> str` — there is no
  owner parameter to pass. `troubleshoot_job` (`chat.py:654-703`) is the
  same shape: `_require_thread(...)` then
  `compose_troubleshoot_message(job_id)` at `chat.py:677`.
- expected: the same `check_owner_or_admin("job", job_id, current_user_or_none(request))`
  the sibling route already uses at `chat.py:280`, and that
  `server/routes/jobs.py` uses on every job-scoped handler. Note that
  `plot_ids` on the *same* request IS scoped —
  `chat.py:438: plot_context_summary(owner_user_id, pid)` — so the
  asymmetry is inside one function.
- evidence: `server/routes/chat.py:361`
  `messages.append(HumanMessage(content=f"{prefix} {job_context_summary(jid)}"))`;
  `server/routes/chat.py:676-677`
  `_require_thread(thread_id, request)` / `text = compose_troubleshoot_message(job_id)`;
  contrast `server/routes/chat.py:280`
  `check_owner_or_admin("job", body.job_id, current_user_or_none(request))`.
- pointer: ownership is enforced per-route, and these two routes take a
  job id as data rather than as the route's subject, so they were missed.
  `check_owner_or_admin` no-ops for unowned jobs, which is the deliberate
  policy, so adding it does not break the "unowned jobs are visible to
  everyone" rule.
- note: the attacker needs the id (12 hex chars, not guessable), so this
  is a boundary crossing rather than a browsing hole — but ids leak
  routinely: shared conversations, the unowned-job list, a screenshot, an
  admin console. The same gap exists one level down in the tool layer:
  `check_job_status`, `plot`, `geometry_parameters` and
  `list_ensemble_geometries_in_window` all read a caller-named `job_id`
  with no owner scoping, so "check job <B's id>" typed into chat reaches
  the same data. Fixing the two routes does not close that; scoping
  belongs in `job_context_summary`/`get_job_manager().result()` or in a
  shared helper the tools call. Would be settled by running two accounts
  on the compose stack and issuing the curl above.

---

### R-000: The active-space literature search reads every user's private uploaded papers, because it passes `state=None` into the one KB path that exists to scope by owner
- surface: code:agent
- class: security
- severity: S1
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `app/agent/active_space_lit.py`'s default backends only. The
  model-facing `search` tool (`tools.py:2875`) correctly forwards
  `state=state` for both `"manuals"` and `"papers"`, and
  `_kb_context_for_job` (`tools.py:161`) is `doc_type="manual"` only, so
  neither is affected. Not checked: whether any other module calls
  `search_knowledge_base.func` with `state=None`.
- repro: user B uploads a private paper on molecule M. User A asks about
  an active space for M; the agent calls `active_space` → 
  `search_active_space_literature` → `active_space_lit.search`, whose
  knowledge-base tier retrieves B's paper verbatim into A's conversation
  and into the resulting job's `literature_notes`.
- observed: `app/agent/active_space_lit.py:203`
  `kb = kb or (lambda q: search_knowledge_base.func(q, doc_type="paper", k=5, state=None))`.
  `app/rag/query_tool.py:39` reads the owner off that state:
  `owner = (state or {}).get("owner_user_id")`, and with `owner` falsy it
  falls through to an unfiltered search. Its own comment (lines 43-51)
  states the harm exactly: *"without this scoping any user's chat could
  trigger a search that surfaces another user's private upload verbatim
  into the model's context."*
- expected: `search_active_space_literature` already receives
  `state: Annotated[AgentState, InjectedState]` (`tools.py:3528`) and so
  has `owner_user_id` in hand; it should thread it into
  `active_space_lit.search`, which should pass it to the kb lambda. The
  `doc_type="paper"` here is precisely the case
  `query_tool.py`'s comment calls "the more privacy-sensitive case".
- evidence: `app/agent/active_space_lit.py:203` (quoted above);
  `app/rag/query_tool.py:39-53`; `app/agent/state.py:299-307`
  (`owner_user_id` … "Read by `search_knowledge_base` … so one user's chat
  can never surface another user's private KB uploads").
- pointer: `active_space_lit.search` takes its backends as injectable
  callables so tests can drive it without a network call
  (docstring, lines 186-190); the production default was written for that
  signature and never grew the owner argument the tool already holds.
- note: settled by uploading a paper as one user and searching as another
  on the compose stack. Related to the previous finding: both are cases
  where a scoping rule that exists is not applied on one path. The
  `explain_active_space` branch (`tools.py:3671`) calls the same
  `active_space_lit.search` and is affected identically.

---

### R-000: On the `run_when_ready` path the approval can silently evaporate on click, because that path re-validates with the external checks that `submit_draft` deliberately turns off
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: the two blocking `check_external`-gated checks in
  `registry2/elicitation.py`: `source_geometry_job_id` (line 673) and
  wigner `source_frequency_job_id` (line 751). Both return `_ask(...)`,
  i.e. they flip a `ready` verdict to `incomplete`.
  `initial_orbitals_job_id` (line 929) is drop-with-a-note and leaves the
  verdict `ready`, so it does not trigger this. Not checked on the
  explicit `submit_draft` path, which is correct by construction.
- repro: draft a job with `{"source_geometry_job_id": "<id>"}` and
  `run_when_ready=True` so the card appears from inside
  `update_job_draft`. Delete that source job (or let a quota eviction
  take it) while the card is on screen. Click Approve. Everything before
  `interrupt()` re-runs, `validate_draft` now returns a question, no
  `interrupt()` is reached, the resume value goes nowhere, and the user's
  click produces an elicitation question instead of a job.
- observed: `app/agent/tools.py:3352` (in `_draft_command`, the single
  funnel both draft tools pass through)
  `verdict = validate_draft(draft, state or {})` — `check_external`
  defaults to `True`. When that verdict is `ready` and the run intent is
  set, line 3363 goes straight to `_submit_ready_draft(...)`, which calls
  `interrupt()` at `tools.py:3972`. Compare `tools.py:3916`, inside
  `submit_draft`: `verdict = validate_draft(draft, state or {}, check_external=False)`.
- expected: `check_external=False` on any path that can reach
  `interrupt()`, for the reason `validate_draft`'s own docstring gives
  (`app/chemistry/registry2/elicitation.py:563-570`): *"That check is
  right at elicitation time and wrong at submission time, because
  everything before the approval `interrupt()` re-runs when the user
  clicks Approve. If the answer changed in between … a re-validating
  submitter would return a question instead of resuming, and the approval
  would disappear with no error at all."* `docs/ARCHITECTURE.md:338-390`
  makes the same argument for why `submit_draft` never redoes network
  resolution.
- evidence: `app/agent/tools.py:3352` vs `app/agent/tools.py:3916`;
  `app/chemistry/registry2/elicitation.py:563-570`.
- pointer: `_submit_ready_draft` was factored out of `submit_draft` so
  `_draft_command` could reach the card directly (its docstring,
  `tools.py:3930-3941`), but the `check_external=False` guard stayed
  behind in `submit_draft` rather than moving into `_submit_ready_draft`
  or being applied at the `_draft_command` call site.
- note: the fix direction is to re-validate with `check_external=False`
  immediately before `_submit_ready_draft`, or to pass the flag through
  `_draft_command`. `run_when_ready=True` is what the system prompt calls
  "the ordinary case" (`prompts.py:41-43`), so this is the common path,
  not an edge one. What would settle it: raise a card via
  `run_when_ready` with a `source_geometry_job_id`, delete the source
  job, click Approve, and check whether `snapshot.interrupts` empties
  with no submission — the same measurement
  `tests/backend/draft_01_summary_defer.py` already makes for the
  neighbouring case.

---

### R-000: The troubleshooting message tells the model to call three tools that are not bound to it
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `app/agent/troubleshoot.py`'s composed message, i.e. every press
  of the Troubleshoot button. Cross-checked every tool name in
  `prompts.py` and in `job_watcher.py`'s `_agent_notice` against
  `STATIC_TOOLS`; those two are clean. `troubleshoot.py` is the only
  offender found.
- repro: let any job fail, press Troubleshoot, read the injected message
  in the transcript, and compare the three names in it against
  `get_all_tools()`.
- observed: `app/agent/troubleshoot.py:126-131`:
  `"Consult search_knowledge_base(doc_type='manual') for the engine's own documentation … and web_search for the specific error text … not search_academic_literature, which covers published papers rather than software errors."`
  None of `search_knowledge_base`, `web_search` or
  `search_academic_literature` is in `STATIC_TOOLS`
  (`app/agent/tools.py:5345-5352`), which is what `get_all_tools()`
  returns and therefore all the model is offered. The three were folded
  into one `search(source=...)` tool (`tools.py:2875`), whose sources are
  `("manuals", "papers", "scholar", "web")` (`tools.py:2871`).
- expected: the message should name `search(source='manuals')` and
  `search(source='web')`, exactly as `prompts.py:100-106` already does
  for the same workflow. A model told to call a non-existent tool either
  emits an invalid call (a wasted ReAct iteration and an error
  ToolMessage) or ignores the instruction and troubleshoots without
  consulting the manuals at all — which is the whole value of the
  feature.
- evidence: `app/agent/troubleshoot.py:126-131`; `app/agent/tools.py:5345`
  `STATIC_TOOLS = [set_geometry, lookup_capabilities, active_space, start_job_draft, update_job_draft, submit_draft, check_job_status, plot, geometry_parameters, list_ensemble_geometries_in_window, convert_energy_units, search, resolve_basis_from_bse]`.
- pointer: the four-tools-into-one collapse
  (`docs/MODEL_CONTEXT_BUDGET.md`, "Where this landed. Phase 2, done")
  updated `prompts.py` and missed this second prompt surface.
- note: `web_search` and `search_academic_literature` still exist as
  `@tool`-decorated functions in `web_search.py`/`scholar_search.py`, and
  `search_knowledge_base` in `app/rag/query_tool.py`, which is why a grep
  for the names does not look wrong. They are reached only via
  `search`'s dispatch (`tools.py:2913-2919`). Confirmed by reading
  `get_all_tools`/`get_executable_tools` (`tools.py:5400-5414`): neither
  returns them.

---

### R-000: A literature-search backend that raises is recorded as a literature *hit*, so a failed search can be reported as published support for an active space
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `app/agent/active_space_lit.py`, both backends (`kb`,
  `scholar`) and both callers (`search_active_space_literature`,
  `explain_active_space`). Traced the marker list against the literal
  return strings in `app/rag/query_tool.py`, `app/agent/scholar_search.py`
  and `app/agent/web_search.py`; those match. It is the wrapper's own
  string that does not.
- repro: make the KB store raise (stop chromadb, or point it at a missing
  path) and ask for an active space. The narrowest tier "matches",
  `search()` short-circuits, and `as_notes()` reports a literature match
  whose evidence is the text `"knowledge base search failed (...)"`.
- observed: `app/agent/active_space_lit.py:259-267`:
  ```
  def _call(fn, source: str, query: str) -> str:
      try:
          return fn(query)
      except Exception as exc:
          return f"{source} search failed ({exc})."
  ```
  `_is_empty` (lines 53-58) does
  `any(text.lstrip().startswith(m) for m in _NO_RESULT_MARKERS)`, and
  `_NO_RESULT_MARKERS` (lines 43-51) is
  `("No matching passages found", "No matching papers found", "No web results found", "Academic literature search failed", "Academic literature search is rate-limited", "Web search failed")`.
  `"knowledge base search failed (…)"` and
  `"published literature search failed (…)"` start with none of them, so
  `_absorb` (lines 271-283) records the string as a hit and sets
  `findings.matched_at = label`. At the knowledge-base tier that then
  triggers `if findings.matched_at == tiers[0][0]: return findings`
  (line 240), skipping the network backends entirely.
- expected: a backend that threw is "nothing found", which `_call`'s own
  docstring says it intends: *"a search that found nothing because a
  backend threw is reported as 'nothing', which is honest."* The marker
  list already treats the two in-tool failure strings as empty, so the
  wrapper's own string was simply overlooked.
- evidence: `app/agent/active_space_lit.py:43-58`, `:242`, `:257-265`,
  `:268-283`.
- pointer: the markers were written against the three tools' return
  values, before `_call` was added to wrap them.
- note: this is S1 if the fabricated "hit" reaches a user as a literature
  claim, which `as_notes()`' found-branch (lines 100+) is written to do
  — it qualifies how narrowly the query matched and the report is
  reconciled against it. It also defeats the guardrail this module exists
  for (its docstring, lines 1-27, and the standing decision that the
  empty result IS the guardrail). Fix: return `""` from `_call`, or add
  `f"{source} search failed"` shapes to `_NO_RESULT_MARKERS`. Settled by
  a one-line unit drive: `active_space_lit.search("water", kb=lambda q: 1/0)`
  and check `.found`.

---

### R-000: `explain_active_space` reports the wrong configuration count for any odd-electron active space
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `explain_active_space` only (reached via the `active_space` tool
  when the user supplies `(ne, no)`). Did not check whether the same
  arithmetic is duplicated in `app/chemistry/cas/`.
- repro: ask "is (5e,4o) a reasonable active space for <molecule>". The
  reply says "holds at most 36 many-electron configurations". The correct
  determinant count for 5 electrons in 4 orbitals is
  C(4,3)·C(4,2) = 4·6 = 24.
- observed: `app/agent/tools.py:3672-3673`:
  ```
  n_alpha = n_beta = active_electrons // 2
  max_configs = math.comb(active_orbitals, n_alpha) * math.comb(active_orbitals, n_beta)
  ```
  Integer division discards the unpaired electron, so an odd count is
  treated as the even count below it and the product is computed from the
  wrong pair of occupations. It over-counts (36 vs 24 above), never
  under-counts.
- expected: `n_alpha = (active_electrons + 1) // 2`,
  `n_beta = active_electrons // 2` for the lowest-multiplicity case, or
  derive both from the molecule's actual multiplicity — which is
  available, since the tool already reads `state["molecule"]` at line
  3660.
- evidence: `app/agent/tools.py:3672-3673`, and the use of the number at
  lines 3683-3691, where it decides between *"enough for the N
  state-averaged root(s) asked about"* and *"fewer than the N root(s)
  asked about, so a state-averaged CASSCF of that size cannot be run in
  it."*
- pointer: the closed-shell case was written first and the `//` was never
  revisited for an odd electron count, which a radical or a cation makes
  ordinary.
- note: the direction matters — over-counting makes the "cannot be run in
  it" guard *too permissive*, so the tool can tell a user a space is
  large enough for their state average when it is not. That is a wrong
  scientific statement presented as correct, which is why this is not S3.
  Two seconds with `math.comb` settles the arithmetic; what needs a
  decision is whether the intended quantity is determinants or CSFs, and
  the docstring should say which.

---

### R-000: Any molecule-panel action or file attach silently destroys an open approval card
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: the `update_state` callers in `app/agent/graph.py` reachable
  from a route while a card is open: `clear_molecule` (:996),
  `remove_frame` (:1016), `add_built_frame` (:1061),
  `add_geometry_frames` (:1087), `append_attached_file` (:1225) and the
  plain `append_notice` (:1154). Deliberately NOT included:
  `set_active_frame` (only reached from `_run_turn`, and the composer is
  disabled while a card is open) and `remove_messages` (its call site is
  guarded by `pending is None`, `chat.py:590`).
- repro: get an approval card on screen, then click the molecule panel's
  reset button (`POST /api/threads/{id}/molecule/reset`), or delete a
  frame, or attach a `.xyz` from the Files panel. The card's underlying
  interrupt is discarded; the card stays on screen because the client
  never hears otherwise, and clicking Approve then 409s or no-ops.
- observed: each of those functions does a bare
  `get_graph().update_state(config, {...})` under the thread lock with no
  `pending_approval` check — e.g. `graph.py:1010-1011`:
  ```
  with _lock_for_thread(config):
      get_graph().update_state(config, {"molecule": CLEAR_MOLECULE, "molecule_frames": {"__replace__": []}})
  ```
  The routes that call them (`chat.py:110-260`) check thread ownership and
  nothing else.
- expected: `docs/ARCHITECTURE.md:648-716` and
  `append_notice_unless_card_pending`'s docstring (`graph.py:1197-1216`)
  state the rule: *"`update_state` discards a pending `interrupt()` —
  the approval card disappears, the submit_draft call is orphaned and the
  user's later Approve does nothing."* `append_notice` names this itself
  (`graph.py:1175-1182`) and hand-waves the remaining callers as
  *"user-initiated (attaching a file), where the user is looking at the
  app rather than at a card"* — which is exactly the case where a card IS
  on screen, since the composer is disabled and the panel is the only
  thing left to click.
- evidence: `app/agent/graph.py:1010-1011`, `:1027-1031`, `:1081-1082`,
  `:1112-1113`, `:1246-1248`, `:1185-1186`;
  `app/agent/graph.py:1175-1182` (`append_notice`'s own warning);
  `server/routes/chat.py:119`, `:132`, `:157`, `:228`, `:249-251`, `:258`,
  `:310`.
- pointer: the guard was built for the watcher's notice path
  (`append_notice_unless_card_pending`) and never generalised to the
  six other `update_state` callers, because the reasoning was framed as
  "background writes are dangerous" rather than "`update_state` is
  dangerous".
- note: confidence is `suspected` for a specific reason worth recording:
  the measured evidence (`tests/backend/draft_01_summary_defer.py`,
  per ARCHITECTURE.md:660-668) is for a `messages` update. That a
  `molecule`-only `update_state` destroys the interrupt the same way is
  inferred from LangGraph's task model, not measured. Settling it is one
  script: raise a card, call `clear_molecule(config)`, then read
  `get_state(config).interrupts` and `.next`. If it holds, the fix is a
  shared guard (return 409 while a card is pending) rather than six
  copies of the check.

---

### R-000: A submission in a mixed tool batch produces no confirmation at all — the app's node is skipped and the tool text forbids the model from saying anything
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: both branches of `_finish_submission` (success and rejection).
  Traced `_receipts_this_step` / `_after_tools` in `graph.py:536-597`.
- repro: get the model to emit `check_job_status` and `submit_draft` in
  one batch — `docs/ARCHITECTURE.md:432` says real conversations do this
  — and approve the card. The job starts and nothing on screen says so.
- observed: `_submissions_this_step` requires every trailing tool_call_id
  in the batch to carry a receipt (`graph.py:569-573`), so a mixed batch
  returns `[]`, `_after_tools` routes to `"agent"` (`graph.py:593-597`),
  and `_job_submitted_node` — the only writer of "Started X. Job id Y."
  — never runs. But the ToolMessage the model then reads ends with
  (`tools.py:2580-2582`):
  `"The user has already been shown a confirmation that this job is running -- do not announce it again."`
  which is false in this case. The rejection branch has the same shape at
  `tools.py:2362-2368`: *"The user has already been shown a message
  saying so and asking what they would like to change, so do not ask
  again and do not resubmit."*
- expected: `docs/ARCHITECTURE.md:428-433` says a mixed batch routes to
  the model *"because those are exactly the results that need relaying"*.
  The tool text should be conditional on whether the node will actually
  run, or the instruction should be softened to "if the app has not
  already confirmed this, say so".
- evidence: `app/agent/tools.py:2580-2582`; `app/agent/graph.py:569-573`
  and `:593-597`; `docs/ARCHITECTURE.md:428-433`.
- pointer: the receipt/`pending_submissions` mechanism knows about the
  mixed-batch case; the ToolMessage prose, written on the assumption that
  the node always runs, does not.
- note: worst case for the user is a job that started with no
  acknowledgement anywhere in the chat — which is the same silence the
  `job_submitted` node was introduced to remove. Settled by driving a
  turn that emits both calls (or by writing the state directly) and
  reading the transcript.

---

### R-000: The system prompt tells the model not to ask for a basis set before an active-space search, but the tool cannot be called without one
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `active_space` and the two functions it dispatches to. Every
  other tool name, argument and source string in `prompts.py` was checked
  against `STATIC_TOOLS` and against `registry2` and is correct.
- repro: ask "what active space should I use for benzene". The prompt
  says not to ask about a basis; the tool schema has `basis` as a
  required string; the model must either ask anyway or invent one.
- observed: `app/agent/prompts.py:116-119`:
  *"**Active spaces: the active_space tool, not the three above.** … Do
  not ask for a basis set first: the recommendation does not depend on
  one. Ask how many states they want, since that does change the answer."*
  `app/agent/tools.py:2923-2930`:
  `def active_space(basis: str, n_excited_states: int, active_electrons: Optional[int] = None, ...)`
  — `basis` is the first positional parameter with no default, so it is
  required in the bound schema. The tool's own docstring then says the
  opposite of the prompt (`tools.py:2944-2946`): *"Ask the user how many
  excited states and which basis they are targeting FIRST"*, as does
  `search_active_space_literature`'s (`tools.py:3534-3538`).
- expected: one answer. `active_space_lit.search` accepts
  `basis: Optional[str] = None` (`active_space_lit.py:180`) and the tier
  builder simply omits the basis tier when it is absent
  (`active_space_lit.py:152-174`), so the plumbing already supports the
  behaviour the prompt describes; only the tool signatures do not.
- evidence: `app/agent/prompts.py:116-119`; `app/agent/tools.py:2923`;
  `app/agent/tools.py:2944-2946`; `app/agent/active_space_lit.py:180`.
- pointer: the prompt was rewritten for the collapsed `active_space` tool
  and the tool's own required-argument list was not revisited.
- note: an invented basis is not inert here — it narrows the literature
  search's first tier to conditions nobody asked for, which is precisely
  what the tool docstring warns against two sentences later. Fix
  direction: make `basis: Optional[str] = None` on `active_space` and
  `search_active_space_literature`, and reconcile the two docstrings with
  `prompts.py`.

---

### R-000: An attached job's one-line pointer tells the model its results are "in this conversation above" even after they have been trimmed out of the window
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `_attached_job_messages` / `_already_attached_job_ids` in
  `server/routes/chat.py`, against `_trim_history` in `graph.py`.
- repro: attach a job's results, then have a long conversation (past
  `LLM_HISTORY_WINDOW`, default 40 messages, or past the token budget),
  keeping the attachment on. The frontend re-sends the job id, the
  pointer message is generated, and the full summary it points at is no
  longer in the prompt.
- observed: `_already_attached_job_ids` (`chat.py:321-327`) scans
  `state["messages"]` — the *entire* checkpointed history — while
  `_trim_history` (`graph.py:343-421`) is what decides what the model
  actually sees. When the id is found anywhere in history, the message
  becomes (`chat.py:356-359`):
  `"… Its full results are already in this conversation above; they are not repeated here. Refer to them there."`
- expected: either check against the trimmed window, or word the pointer
  so it is safe when the referent is gone — the pattern already exists
  one file over, in `_OMITTED_RESULT_NOTICE` (`graph.py:302-307`), which
  tells the model to re-fetch with `check_job_status` rather than answer
  from memory. `docs/ARCHITECTURE.md:508-539` ("A turn may not silently
  lose the results it just fetched") is the section this cuts against:
  the same fabrication risk, arriving by a different route.
- evidence: `server/routes/chat.py:321-327` and `:353-362`;
  `app/agent/graph.py:302-307`.
- pointer: the dedupe was built to fix a token-budget blowout
  (`docs/MODEL_CONTEXT_BUDGET.md`, "One job's results were attached three
  times") and correctly keyed on the durable history; nothing tied it to
  the window the model is actually shown.
- note: low-cost fix — append "if they are no longer visible, re-read
  them with check_job_status" to the pointer. Settled by replaying a long
  conversation with a persistent attachment and printing
  `build_prompt_messages(state)`.

---

### R-000: `_shed_pinned_results` can only shrink `ToolMessage`s, so several jobs attached to one message can hold the prompt over budget with nothing able to give
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `_trim_history` / `_shed_pinned_results` in `app/agent/graph.py`.
  Checked the interaction with `_current_turn_start`'s pinning of the
  leading human block.
- repro: attach four completed jobs to one message (each
  `job_context_summary` is ~20,000 characters, ~10,000 tokens per
  `docs/MODEL_CONTEXT_BUDGET.md`). Each arrives as its own synthetic
  `HumanMessage` (`chat.py:361`), all inside the pinned current turn.
- observed: `_current_turn_start` (`graph.py:281-299`) deliberately pins
  "the contiguous block of human messages that opened the turn … plus any
  job contexts the frontend attached ahead of it". Both drop loops
  (`graph.py:394-403`) stop at `pin_from`, and the only remaining lever,
  `_shed_pinned_results` (`graph.py:310-340`), skips anything that is not
  a `ToolMessage`:
  `if not isinstance(m, ToolMessage) or m.content == _OMITTED_RESULT_NOTICE: continue`.
  So a turn whose bulk is attached-job HumanMessages exits the function
  over budget with only a `logger.warning` (`graph.py:411-419`).
- expected: the same in-place blanking, applied to a synthetic attached-job
  HumanMessage. Those messages are app-authored, carry a machine-readable
  prefix (`_JOB_ATTACH_PREFIX`, `chat.py:318`) and name their own job id,
  so replacing one with "re-read job X with check_job_status" is exactly
  the self-correcting marker the ToolMessage path already uses. Blanking
  the user's own typed text would not be acceptable; blanking these is.
- evidence: `app/agent/graph.py:310-340`, `:391-419`;
  `server/routes/chat.py:318` and `:361`.
- pointer: `docs/MODEL_CONTEXT_BUDGET.md`'s fix addressed the
  *repeat*-attachment case (a job already in history becomes a pointer)
  but not the first attachment of several jobs at once, which is one
  click in the Job Manager.
- note: this is the answer to "can the budget be exceeded anyway by one
  huge tool result" — yes, but the route is attached HumanMessages, not
  tool results. Settled by constructing the state and calling
  `_trim_history` directly, then summing `_message_tokens`.

---

### R-000: `POST /messages` has no server-side guard against posting while an approval card is open, so anything but the browser destroys the card
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `post_message` in `server/routes/chat.py`. The browser IS
  guarded (`frontend/src/chat/ChatPane.tsx:125`,
  `const disabled = … || !!pendingApproval`), so this is only reachable
  from curl, a script, a stale tab, or a second client.
- repro: raise a card, then `POST /api/threads/{id}/messages` from curl.
  The turn invokes the graph with new input, which discards the pending
  task; the `submit_draft` call is orphaned and a later Approve is a
  silent no-op.
- observed: `server/routes/chat.py:631-651` calls `_require_thread`,
  resolves the owner, registers a cancel event and starts `_run_turn`.
  There is no `pending_approval(config)` check anywhere on the path.
  Contrast `approve_job` (`chat.py:806-808`), which does check and
  returns 409.
- expected: a 409 mirroring `approve_job`'s, since
  `docs/ARCHITECTURE.md:648-668` treats invoking over a pending interrupt
  as destruction rather than as bad timing, and the watcher path
  (`invoke_turn_if_idle`) already refuses for exactly this reason while
  holding the lock.
- evidence: `server/routes/chat.py:631-651`; `server/routes/chat.py:806-808`;
  `app/agent/graph.py:1357-1383`.
- pointer: the invariant is enforced in three places (the client, the
  watcher, the approval route) and not in the one route a third-party
  client would use.
- note: same family as the molecule-panel finding above and probably the
  same fix — one shared "is a card open" gate applied to every
  state-mutating entry point.

---

### R-000: A checkpoint-write failure after `submit()` can leave the interrupt live, so a re-approval submits the job twice
- surface: code:agent
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `_finish_submission` → `approve_job`. Reasoned about, not
  reproduced; I did not verify at what point LangGraph clears the
  interrupt relative to the node's checkpoint commit, and that is the
  crux.
- repro: inject a failure in the Postgres checkpointer's `put` (kill the
  DB, or exhaust the pool) during an approval resume, then reload the
  page and click Approve again.
- observed: in `_finish_submission` the real submission happens first —
  `job_id = get_job_manager().submit(approved_spec, owner_user_id=owner_user_id)`
  (`tools.py:2541`) and the scan/ensemble/batch equivalents above it —
  and only afterwards is the `Command(update=...)` returned for the graph
  to commit. If the commit raises, `_stream_resume` propagates, and
  `approve_job` (`chat.py:870-883`) logs and raises a 500 *before* line
  908's `pending_approval(config)` re-read and the `interrupt` SSE event.
  The job directory exists on disk regardless.
- expected: an approval is single-use. Either the interrupt is spent the
  moment the resume begins (in which case this is only a lost
  confirmation, S3) or it is not (in which case a second click runs the
  calculation twice, which on this host can be hours of compute).
- evidence: `app/agent/tools.py:2541`; `server/routes/chat.py:865-883`;
  `server/routes/chat.py:908-910`.
- pointer: the resume path has no idempotency key. `active_job_ids` would
  have caught a duplicate, but its write is in the same uncommitted
  update.
- note: file low-confidence and settle it before acting. The cheap
  observation that settles it: after a successful approval, does
  `get_state(config).interrupts` empty as of the *node* commit or as of
  the resume call? A `_retried_from`-style marker written into the job
  directory before the Command returns would make a duplicate detectable
  either way.

---

### R-000: The job watcher re-reads `status.json` for every job of every conversation every two seconds, forever, including jobs that reached terminal months ago
- surface: code:agent
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `JobWatcher._poll_once`. Did not measure; the cost is a
  filesystem read per (thread, job) pair per tick.
- repro: `strace`/`inotify` the api container for ten seconds with a few
  populated conversations and count opens of `data/jobs/*/status.json`.
- observed: `app/agent/job_watcher.py:471-481` loops over every id in
  `entry["active_job_ids"]` and calls `mgr.status(job_id)` unconditionally.
  `self._last_status` (`job_watcher.py:389`) dedups the *SSE event*, not
  the read. A terminal job is also already in `seen`
  (`job_watcher.py:480`), so nothing further will ever be done with it —
  yet it is re-read on every tick for the life of the process.
  `active_job_ids` only grows: its reducer is append-only
  (`app/agent/state.py:136-152`) and the registry mirror
  (`threads.py:118-120`) drops an id only when its directory is gone.
- expected: skip a job whose cached status is already terminal and whose
  id is in `seen` — a terminal status cannot change. That reduces the
  steady-state cost to one `_read_seen` per thread per tick plus reads
  for genuinely running jobs.
- evidence: `app/agent/job_watcher.py:471-481`;
  `app/agent/job_watcher.py:389`; `app/agent/state.py:136-152`.
- pointer: `_last_status` was added for event deduplication and the same
  cache was never used to skip the read.
- note: also worth folding in: `_agent_notice` calls `read_spec(jid)`
  twice per candidate id inside one comprehension
  (`job_watcher.py:261-265`), and `_poll_once` does a full `_read_seen`
  JSON read per thread per tick. Both are small next to the status reads.
  Nothing here is a correctness problem; the reason it is worth filing is
  that the cost grows monotonically with how much the deployment has been
  used, which is the shape that goes unnoticed until it doesn't.

---

### R-000: Quota enforcement runs on the watcher thread and can block on a conversation's graph lock, stalling every conversation's job notices for the length of a turn
- surface: code:agent
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: the `enforce_all_quotas` call inside `JobWatcher._loop`, and the
  one eviction branch that takes a graph lock. Postgres deployments only
  (`DATABASE_URL` gated).
- repro: fill a user past their combined jobs+chat cap so a thread is
  evicted, start a long turn on that thread, and watch whether
  `job_update` events stop arriving on *other* conversations for the
  duration.
- observed: `app/agent/job_watcher.py:449-458` calls
  `enforce_all_quotas()` inline on the watcher's own thread every 150
  ticks (~5 minutes). Its thread-eviction branch
  (`app/auth/storage_quota.py:555-558`) calls
  `delete_thread_checkpoints(key)`, and that function takes the per-thread
  graph lock (`app/agent/graph.py:1449`
  `with _lock_for_thread(config):`) — the same lock a running turn holds
  for its whole 53-77 s ReAct loop
  (`docs/ARCHITECTURE.md:686-696`). While the watcher is blocked there,
  `_poll_once` is not running for anybody.
- expected: the watcher's whole design premise is that job polling never
  shares a lock with a chat turn (`job_watcher.py:54-64`,
  `graph.py:1118-1146`). This is the one path that reintroduces exactly
  that coupling, one level down.
- evidence: `app/agent/job_watcher.py:449-458`;
  `app/auth/storage_quota.py:555-558`; `app/agent/graph.py:1434-1452`.
- pointer: the watcher loop was chosen as the trigger because
  chat-history growth has no per-message hook (`job_watcher.py:137-145`),
  which is sound; what was not considered is that one of the eviction
  branches blocks.
- note: fix direction is a separate daemon thread for quota enforcement,
  or a non-blocking `acquire(blocking=False)` in
  `delete_thread_checkpoints` that defers rather than waits. Also worth
  checking (outside my scope) whether evicting a thread whose turn is
  in flight leaves that turn writing to deleted rows.

---

### R-000: `_agent_notice`'s cas_reco branch tests the same condition twice where the comment says it tests the subtype
- surface: code:agent
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `JobWatcher._poll_once`'s bucketing. Currently inert, because
  `cas_reco` has no subtype that recommends nothing.
- repro: none today. It becomes live the first time `cas_reco` gains a
  non-recommending subtype.
- observed: `app/agent/job_watcher.py:518-519`:
  ```
  elif spec is not None and spec.get("task") == "cas_reco" \
          and spec.get("task") == "cas_reco":
  ```
  The comment immediately above (lines 511-514) explains the second
  clause as a *subtype* check: *"The subtype check is not redundant: it
  keeps this branch honest if cas_reco ever gains a subtype that
  recommends nothing, the way the since-removed cas_reco/explain did."*
- expected: the second clause should read `spec.get("subtype")` against
  whatever set of subtypes should get the recommendation notice — which
  is the check the comment describes and the code does not perform.
- evidence: `app/agent/job_watcher.py:511-520`.
- pointer: a copy-paste when `cas_reco/explain` was removed.
- note: filed at S4 because it is currently unreachable, but it is the
  kind of thing that is invisible until the subtype exists and then
  routes a non-recommending job into a notice that instructs the model to
  open a pre-filled CASSCF draft.

---

### R-000: ARCHITECTURE.md's "Automatic troubleshooting, with a code-enforced budget" describes a budget that no longer exists in the code
- surface: code:agent
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `docs/ARCHITECTURE.md:565-646`, checked against the whole
  repository by grep.
- repro: `grep -rn "count_failed_in_chain\|_retried_from" app/ server/ tests/`
  → the only hits in the entire tree are `docs/ARCHITECTURE.md:640-641`.
- observed: `docs/ARCHITECTURE.md:638-644`: *"The budget is **not** read
  from anything the model supplies. `count_failed_in_chain()` walks the
  retry chain backwards on disk via each job's `params["_retried_from"]`
  and counts current failures; `job_watcher` calls it directly to decide
  between a retry notice and a stop-and-explain notice."* No such
  function exists; `job_watcher` has no retry notice and no
  stop-and-explain notice; nothing writes `_retried_from`. The section
  title still promises a budget. The current design has none, and
  correctly so: troubleshooting is user-initiated
  (`server/routes/chat.py:654-703`) and starts no job of its own, so
  there is nothing to cap. The rest of that section (the mechanically-read
  25-line tail) is accurate.
- expected: the paragraph should be removed or rewritten to say that the
  budget went away with auto-retry, because the section as written tells
  a reader a guard is in place that is not. The brief's item 7 asks
  precisely whether that budget is code-enforced; the honest answer is
  that there is no budget.
- evidence: `docs/ARCHITECTURE.md:638-644`; empty grep across `app/`,
  `server/`, `tests/`.
- pointer: the auto-retry removal updated the surrounding prose and left
  the budget paragraph.
- note: a second, smaller instance in the same family:
  `docs/ARCHITECTURE.md:517` tells the model to *"re-fetch the specific
  fields with `job_data`"*, but the `job_data` tool was folded into
  `check_job_status`'s `fields` argument (`app/agent/tools.py:2800-2804`
  — *"Was its own `job_data` tool for about a day"*). The runtime string
  was updated correctly (`graph.py:302-307` names
  `check_job_status`); only the doc still says `job_data`. Also, the
  comment at `tools.py:3019` says "Eleven tools" where `STATIC_TOOLS` has
  thirteen.

---

### R-000: The troubleshooting message describes a failed job by its level of theory instead of by what it was
- surface: code:agent
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `compose_troubleshoot_message` only. The sibling notice,
  `_failure_notice_text` (`job_watcher.py:347-352`), gets this right.
- repro: fail a `freq` job at b3lyp and press Troubleshoot. The message
  the model is given opens: *"job <id>, a 'b3lyp' job on orca that
  FAILED"* — with nothing anywhere in it saying the job was a frequency
  calculation.
- observed: `app/agent/troubleshoot.py:100`
  `job_type = spec.get("method", "unknown")`, used at line 112 as
  `f"a '{job_type}' job on {engine} that FAILED"`. `CLAUDE.md` states the
  taxonomy directly: *"task/subtype say what the job IS; method says the
  level of theory."*
- expected: `f"{task}/{subtype}"` (with `method` alongside), the way
  `_failure_notice_text` builds it:
  `label = f"{task}/{subtype}" if task and subtype else task`
  (`job_watcher.py:350`).
- evidence: `app/agent/troubleshoot.py:100` and `:110-113`;
  `app/agent/job_watcher.py:347-352`; `CLAUDE.md`, "Testing conventions".
- pointer: a pre-v2 field name left behind by the registry v2 rewrite,
  in the one file that still reads `spec["method"]` as the job's kind.
- note: this matters more than a wording slip because the message is the
  entire evidence package for a diagnosis. An optimisation that failed to
  converge and a frequency run that hit a negative mode fail for
  different reasons, and the model is not told which it is looking at.
  Cheap fix; same two lines as `_failure_notice_text`.

---

### R-000: `update_job_draft` silently discards valid parameters when one key in the same call is a misrouted geometry
- surface: code:agent
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: the `misrouted` branch of `update_job_draft`. Its sibling
  branch (`unknown`/`inapplicable`) handles this correctly.
- repro: have the model call
  `update_job_draft({"molecule": "water", "basis": "cc-pvdz"})`. The
  reply names only `molecule`; `basis` is also not recorded, and nothing
  says so.
- observed: `app/agent/tools.py:3869-3876` returns a `Command` carrying
  only a `ToolMessage` — no `job_draft` key — so the locally-built
  `params`/`draft` (including `basis`) is thrown away. The message reads
  *"A structure is not a job parameter, so molecule was not recorded in
  the draft"*, which implies the rest was. The `unknown`/`inapplicable`
  branch a few lines earlier is explicit about the same behaviour
  (`_unknown_param_message`, `tools.py:3200-3206`): *"so nothing was
  recorded -- not even the keys in the same call, since a half-applied
  update is harder to reason about than none."*
- expected: the same sentence, or persist the valid keys. Either is fine;
  what is not fine is doing one and saying the other, because the model
  then believes `basis` is set and moves on.
- evidence: `app/agent/tools.py:3869-3876`; `app/agent/tools.py:3200-3206`.
- pointer: the all-or-nothing rule was articulated when the unknown-key
  refusal was added and not applied to the older misrouted-key refusal's
  wording.
- note: trivial fix. Settled by calling
  `update_job_draft.func(updates={"molecule":"water","basis":"cc-pvdz"}, ...)`
  against a draft and reading back `job_draft`.

---

### R-000: `search_academic_literature` parses the response body outside its try block
- surface: code:agent
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:agent
- scope: `app/agent/scholar_search.py`. `web_search.py` is clean —
  everything network-facing is inside its `try`.
- repro: have Semantic Scholar return a 200 with a non-JSON body (a
  proxy interstitial, an HTML error page). `resp.json()` raises
  `JSONDecodeError`.
- observed: `app/agent/scholar_search.py:74-85`: the `try/except` covers
  only `requests.get`, and status handling covers 429 and `not resp.ok`.
  Line 85 is `data = resp.json().get("data") or []`, outside any guard.
- expected: the same graceful degrade the rest of the function has — the
  tool's own docstring promises *"If this tool errors (including a
  rate-limit response), it tells you to use web_search instead"*.
- evidence: `app/agent/scholar_search.py:74-85`.
- pointer: the try was scoped to the connection, not the round trip.
- note: S4 because `ToolNode` catches a tool exception into a ToolMessage
  by default, so the model gets an error string rather than a crashed
  turn — but it gets a raw `JSONDecodeError` instead of the
  fall-back-to-web instruction the docstring promises. This also
  interacts with the `_call` finding above: an exception here becomes a
  false literature hit.

---

## Checked and clean

Stated positively, with what was checked, because a negative result is
useful here.

**Deadlock (brief item 2).** `app/agent/tools.py` imports nothing from
`app/agent/graph.py` — verified by grepping every `agent.graph` reference
in `app/` and `server/`; the only importers are `job_watcher.py`,
`server/routes/chat.py`, `server/routes/threads.py` and
`app/auth/storage_quota.py`. `invalidate_graph_cache()` has no caller at
all. No tool reaches a lock-taking graph function, transitively or
otherwise. Lock ordering is thread-lock then `_compiled_graph_lock` and
never the reverse (`get_graph()` at `graph.py:902-907` releases before the
caller's `.invoke()`). `read_state`, `pending_approval` and
`draft_hold_reason` are genuinely lock-free, which is what makes
`invoke_turn_if_idle` (`graph.py:1357-1383`) and
`append_notice_unless_card_pending` (`graph.py:1197-1222`) safe to call
them from *inside* the lock — I checked both for the self-deadlock a
non-reentrant `threading.Lock` would otherwise give. The architecture's
claim that "drafting outranks summarising, and the check has to be inside
the lock" is implemented as described: `invoke_turn_if_idle` re-evaluates
`draft_hold_reason` while holding the lock and declines, and the
watcher's pre-lock check at `job_watcher.py:493` is only a fast path.

**The approval gate's spec cannot be tampered with.** `approve_job`
builds the resume value from the *server-side* interrupt payload —
`server/routes/chat.py:861-864`,
`{"approved": True, "spec": pending["spec"], "input_text": body.input_text}`
— never from the request body. The only client-controlled field is
`input_text`, which is validated before the interrupt is spent
(`chat.py:837-856`), re-validated in `_finish_submission`
(`tools.py:2421-2431`), dropped for engines with no validator
(`tools.py:2412-2413`), and proven as a template for `interp_pes`
(`tools.py:2452-2459`). The confirmation text is written by
`_submission_text`/`_job_submitted_node` in the graph
(`graph.py:600-664`) from an app-built receipt, not by the model.

**State and reducers (brief item 3).** Every side-channel key in
`AgentState` is `NotRequired[Annotated[...]]`; every multi-write-capable
key has a reducer (`_last_molecule`, `_last_draft`, `_last_draft_status`,
`_append_job_ids`, `_append_submissions`, `_molecule_frames_reducer`), and
each sentinel (`CLEAR_MOLECULE`, `CLEAR_DRAFT_STATUS`) is distinguishable
from "no write this step". `_current_turn_start` pins the `AIMessage`
carrying the `tool_calls` along with its answers, so
`_drop_orphan_tool_messages` cannot be defeated by the budget loops; the
budget loops run before the orphan pass, in the order the docstring says
is required.

**Prompt-vs-reality (brief item 4).** Every tool name, argument name and
`search` source in `prompts.py` resolves against `STATIC_TOOLS`, and every
method/engine/capability claim in it is deferred to `lookup_capabilities`
rather than asserted — the prompt states no capability of its own except
"this app has no molecular-dynamics capability", which is true. Every
tool name in `job_watcher.py`'s `_agent_notice` (`plot(kind='ensemble')`,
`plot(kind='pes_scan')`, `start_job_draft`, `update_job_draft`) resolves.
The two failures found are in `troubleshoot.py` and the
`active_space`/basis contradiction, both filed above.

**Network tools (brief item 5).** `web_search` and
`search_academic_literature` both carry configured timeouts
(`WEB_SEARCH_TIMEOUT`, `SEMANTIC_SCHOLAR_TIMEOUT`), catch broadly, and
return an instruction rather than an exception; `search_academic_literature`
additionally special-cases 429 and tells the model not to retry, and
`active_space_lit` honours that across tiers (`active_space_lit.py:250-256`).
`resolve_basis_from_bse` is fully offline and wraps `bse.get_basis` in a
try. `_kb_context_for_job` returns `""` on any store failure. The one gap
is `resp.json()` (filed S4).

**Background announcements (brief item 6).** `turn_start` is emitted from
`invoke_turn_if_idle`'s `on_start`, i.e. after the lock is held and the
hold check passed, and `turn_complete` is paired from a `finally` guarded
on `started` (`job_watcher.py:705-769`) — so a deferred turn emits
neither and a failed one still emits both. A job finishing with no tab
open still writes a checkpointed message. Duplicate announcements are
guarded three ways: `_seen` on disk per thread, `_last_status` for
`job_update` events, and `reported_jobs` for jobs the agent already
summarised in its own turn. A cancellation-only tick writes `seen` in its
own block (`job_watcher.py:618-621`), which is the re-notify-forever trap
the comment describes. Thread ids are `uuid4().hex`
(`app/agent/threads.py:72`), so the `_seen/<thread_id>.json` filename
cannot be traversed.

**Prompt-cache stability (brief item 8).** The window start is quantised
to `LLM_HISTORY_STEP` and rounds down (`graph.py:377-379`), the
over-budget loop advances in the same block size, and the digest travels
as a trailing `HumanMessage` rather than being appended to the system
message (`graph.py:460-480`). The front of the prompt does not move on an
ordinary append. `_estimate_tokens` counts digits separately, as
`docs/MODEL_CONTEXT_BUDGET.md` requires.

**`model_warmer.py` (brief item 9).** Nothing wasteful found: the request
carries no `prompt`, so it is a load-only call that generates no tokens;
failures are logged once per outage rather than per tick; the loop is a
no-op when `MODEL_KEEPALIVE_INTERVAL <= 0`. `keep_alive: -1` arguably
makes the repeat pings redundant, but they are what recovers the model
after an Ollama restart, so they earn their place.
