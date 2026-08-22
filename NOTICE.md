# Third-party software and attribution

NexusQC itself is released under the MIT License (see `LICENSE`). It depends
on, bundles, or drives a number of third-party components whose own licences
and citation expectations are recorded here.

## Quantum chemistry engines

NexusQC is an orchestration layer. It does not implement quantum chemistry.
It prepares inputs for, runs, and parses the output of established programs.
None of them is redistributed with this project.

| Engine | Licence | How NexusQC uses it |
|---|---|---|
| **PySCF** | Apache-2.0 | Installed via `requirements.txt` and imported directly. The default engine for most job types. |
| **ORCA** | Proprietary, free for academic use | **Never bundled or redistributed.** ORCA's licence explicitly forbids redistribution, so it is always bind-mounted read-only from the host and is never copied into a container image. Users must obtain their own licensed copy. |
| **BAGEL** | GPL-3.0 | **Never bundled or redistributed.** Executed as a separate process via its own binary, bind-mounted read-only from the host. NexusQC does not link against BAGEL, so its GPL does not extend to this project; users must install it themselves. |

If you publish results produced with any of these engines, cite the engine
itself. NexusQC ran it; it did not compute anything.

## Copyleft dependencies

Two Python dependencies are copyleft. Both are ordinary pip-installed
libraries imported at runtime, not modified and not statically linked, so MIT
licensing of NexusQC's own source is compatible, but they are named here
explicitly rather than buried in a lockfile.

| Package | Licence | Where it is used |
|---|---|---|
| **ASE** (Atomic Simulation Environment) | LGPL-2.1-or-later | `app/chemistry/jobs/interpolate.py`, IDPP path interpolation and NEB support. |
| **psycopg** | LGPL-3.0-only | `app/auth/db.py`, `app/auth/models.py`, `app/agent/graph.py`, PostgreSQL access for the multi-user deployment. |

## Bundled frontend assets

These ship inside the built frontend and are redistributed with it.

| Component | Licence | Notes |
|---|---|---|
| **Ketcher** (`ketcher-react`, `ketcher-core`, `ketcher-standalone`), EPAM Systems | Apache-2.0 | 2D structure editor. Apache-2.0 requires that its attribution and NOTICE be preserved; this file serves that purpose. |
| **3Dmol.js** | BSD-3-Clause | All 3D molecular and orbital rendering. The authors ask that academic work using it cite: Rego, N. & Koes, D. *3Dmol.js: molecular visualization with WebGL.* Bioinformatics 31(8), 1322–1324 (2015). |
| **Miew**. EPAM Systems | MIT | Molecular viewer, pulled in with Ketcher. |
| **IBM Plex Sans / IBM Plex Mono** | SIL Open Font License 1.1 | Font files are embedded in the build and therefore redistributed. The OFL permits this; the fonts must remain under the OFL and must not be sold on their own. |
| React, React DOM, TanStack Query, Zustand, Radix UI, Tailwind CSS, Vite, react-markdown | MIT | |
| lucide-react | ISC | |
| TypeScript, Playwright | Apache-2.0 | Development and test tooling; not shipped to users. |

## Python dependencies

Beyond the two copyleft packages above, the Python stack is permissively
licensed: LangGraph and the LangChain family (MIT), RDKit (BSD-3-Clause),
ChromaDB (Apache-2.0), FastAPI, pubchempy, ddgs, argon2-cffi, PyJWT, redis,
python-docx and BeautifulSoup (MIT), uvicorn, pypdf, psutil, httpx, NumPy,
SciPy and geomeTRIC (BSD-family), and Matplotlib (PSF-derived).

See `requirements.txt` for exact pins.

## External data sources

NexusQC queries these services at runtime. No API key is required for any of
them except where noted, and none receives user credentials.

- **PubChem** (via `pubchempy`), resolves molecule names to structures.
- **Semantic Scholar Graph API**, academic literature search. Optional API
  key via `QC_AGENT_SEMANTIC_SCHOLAR_API_KEY`; degrades gracefully without one.
- **DuckDuckGo** (via `ddgs`), web search when troubleshooting a failed job.
  This is the only component that sends query text to a third party; see the
  README's note on that trust boundary.
- **ORCA and BAGEL manuals**. Crawled by `scripts/seed_knowledge_base.py` to
  build the local knowledge base, respecting each site's `robots.txt`.
  PySCF's documentation is deliberately **not** crawled: pyscf.org's
  `robots.txt` disallows it, so PySCF reference material is generated from the
  installed package's own docstrings instead.
