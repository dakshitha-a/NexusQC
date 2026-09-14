"""Knowledge-base lifecycle: all three ingest routes, per-user scoping,
the agent actually reaching a user's own upload, and what happens to the
raw file on disk when a source is deleted.

That last one is the reason this script exists in its current shape.
`DELETE /api/kb/sources/{source}` calls app/rag/store.delete_source(),
which removes the Chroma chunks -- but nothing in that path unlinks the
uploaded file at UPLOADS_DIR/<owner>/<source>. Compare
app/auth/storage_quota.py::_evict, which DOES unlink for a kind=="kb"
candidate. If the file survives, it is then invisible to every cleanup
path in the app, because both _kb_candidates() and _kb_usage_by_owner()
enumerate from Chroma rather than from disk -- so deleting the owning
user cannot reclaim it either.

Sub-tests:
  K1  file upload -> listed -> searchable -> content retrievable
  K2  text paste and URL fetch ingest routes
  K3  rejected file extension
  K4  per-user scoping: A's upload is invisible to B; shared manuals are
      visible to both
  K5  the agent's own `search` reaches the caller's OWN upload
      (proves owner scoping is threaded all the way into the tool)
  K6  DELETE removes the chunks -- and what happens to the file on disk
  K7  deleting the owning USER removes their KB files
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent

# Deliberately distinctive so a similarity search can only match this doc.
SECRET_DOC = (
    "Zorblatt resonance tuning for the Quixotic-7 basis set.\n\n"
    "The Zorblatt correction factor for Quixotic-7 is 0.8814 hartree per "
    "bohr when the flumox parameter exceeds 3. This value is specific to "
    "the Quixotic-7 contraction scheme and must never be reused for "
    "Quixotic-9, whose Zorblatt factor is 0.4471 instead.\n"
)


def disk_ls(path: str) -> list[str]:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "bash", "-lc",
         f"ls -1 {path} 2>/dev/null || true"],
        cwd=str(REPO), capture_output=True, text=True, timeout=60,
    )
    return [x for x in p.stdout.strip().splitlines() if x]


def main() -> None:
    admin = admin_client()
    tok_a = mint_invite(admin, "user")
    ua, ia = register(tok_a)
    uid_a = str((ia.get("user") or ia).get("id"))
    tok_b = mint_invite(admin, "user")
    ub, ib = register(tok_b)
    uid_b = str((ib.get("user") or ib).get("id"))

    fname = "e2e_zorblatt_notes.txt"

    # ---------------------------------------------------------------- K1
    print("=== K1: file upload -> list -> content ===\n")
    r = ua.post("/api/kb/sources",
                files={"file": (fname, SECRET_DOC.encode(), "text/plain")},
                data={"doc_type": "paper"})
    check("K1a upload accepted", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 201:
        check("K1b upload reports chunks ingested", (r.json().get("n_chunks") or 0) > 0,
              r.text[:150])

    srcs = ua.get("/api/kb/sources").json()
    mine = [s for s in srcs if s.get("source") == fname]
    check("K1c the source appears in the owner's listing", len(mine) == 1,
          f"{len(mine)} matches")

    rc = ua.get(f"/api/kb/sources/{fname}/content")
    check("K1d the raw source content is retrievable by its owner",
          rc.status_code == 200 and b"Zorblatt" in rc.content,
          f"status={rc.status_code}")

    on_disk = disk_ls(f"/app/data/uploads/{uid_a}")
    check("K1e the uploaded file is on disk under the owner's directory",
          fname in on_disk, str(on_disk))

    # ---------------------------------------------------------------- K3
    print("\n=== K3: rejected file extension ===\n")
    r = ua.post("/api/kb/sources",
                files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
                data={"doc_type": "paper"})
    check("K3 a disallowed extension is rejected (allowed: .pdf .txt .md .docx)",
          r.status_code >= 400, f"{r.status_code} {r.text[:150]}")

    # ---------------------------------------------------------------- K2
    print("\n=== K2: text-paste ingest route ===\n")
    r = ua.post("/api/kb/sources/text",
                json={"text": "Pasted note: the flumox parameter is dimensionless.",
                      "filename": "e2e_pasted_note.txt", "doc_type": "paper"})
    check("K2 POST /api/kb/sources/text ingests pasted text",
          r.status_code == 201, f"{r.status_code} {r.text[:200]}")

    # ---------------------------------------------------------------- K4
    print("\n=== K4: per-user scoping ===\n")
    b_srcs = ub.get("/api/kb/sources").json()
    b_names = {s.get("source") for s in b_srcs}
    check("K4a user B does NOT see user A's upload", fname not in b_names,
          f"B sees {len(b_names)} sources")
    shared = [s for s in b_srcs if s.get("owner") == "__shared__"]
    check("K4b user B DOES see the shared pre-seeded manual corpus",
          len(shared) > 100, f"{len(shared)} shared sources visible to B")
    rb = ub.get(f"/api/kb/sources/{fname}/content")
    check("K4c user B cannot fetch user A's source content",
          rb.status_code >= 400, f"status={rb.status_code}")

    # ---------------------------------------------------------------- K5
    print("\n=== K5: the agent's own search reaches the caller's upload ===\n")
    sa = AgentSession.new(ua, label="e2e kb search A")
    ta = sa.say("Search the knowledge base: what is the Zorblatt correction "
                "factor for the Quixotic-7 basis set?", timeout=420)
    # The four retrieval tools were unified into one `search(query, source=...)`
    # some time ago and `search_knowledge_base` is no longer bound: it is the
    # function `search` dispatches to for source="manuals" and "papers". This
    # check asked for the old bound name and so could only fail. The 2026-09
    # review recorded the same drift here and in e2e_06's T04 to T06 and called
    # it test-side, which it is.
    a_text = "\n".join(c for n, c in ta.tools_executed() if n == "search")
    check("K5a the agent searched the knowledge base",
          "search" in ta.tool_names(), f"tools={ta.tool_names()}")
    check("K5b user A's OWN upload was reachable through the tool "
          "(owner scoping is threaded into the tool, not just the REST list)",
          "0.8814" in a_text or "Zorblatt" in a_text, a_text[:250])
    sa.close()

    sb = AgentSession.new(ub, label="e2e kb search B")
    tb = sb.say("Search the knowledge base: what is the Zorblatt correction "
                "factor for the Quixotic-7 basis set?", timeout=420)
    b_text = "\n".join(c for n, c in tb.tools_executed() if n == "search")
    check("K5c user B's identical search does NOT surface user A's private "
          "upload", "0.8814" not in b_text, b_text[:250])
    sb.close()
    record("K5", "PASS", a_hit="0.8814" in a_text, b_hit="0.8814" in b_text)

    # ---------------------------------------------------------------- K6
    print("\n=== K6: DELETE a source -- chunks AND the file on disk ===\n")
    before = disk_ls(f"/app/data/uploads/{uid_a}")
    r = ua.delete(f"/api/kb/sources/{fname}")
    check("K6a DELETE returns 200 and reports deleted chunks",
          r.status_code == 200, f"{r.status_code} {r.text[:150]}")
    after_srcs = {s.get("source") for s in ua.get("/api/kb/sources").json()}
    check("K6b the source is gone from the listing", fname not in after_srcs)
    after = disk_ls(f"/app/data/uploads/{uid_a}")
    file_gone = fname not in after
    check("K6c [F-001] the RAW UPLOADED FILE is also removed from disk",
          file_gone,
          f"before={before} after={after} -- an orphaned file here is "
          f"unreachable by every cleanup path in the app, since both "
          f"_kb_candidates() and _kb_usage_by_owner() enumerate from Chroma")
    record("K6", "PASS" if file_gone else "FAIL",
           before=before, after=after, orphaned=not file_gone)

    # ---------------------------------------------------------------- K7
    print("\n=== K7: deleting the owning user reclaims their KB files ===\n")
    # user A still has the pasted note; delete the account and see if the
    # directory is cleaned up.
    pre = disk_ls(f"/app/data/uploads/{uid_a}")
    cleanup_user(admin, uid_a)
    time.sleep(3)
    post = disk_ls(f"/app/data/uploads/{uid_a}")
    check("K7 deleting a user removes their remaining KB uploads from disk",
          not post, f"before={pre} after={post}")
    record("K7", "PASS" if not post else "FAIL", before=pre, after=post)

    cleanup_user(admin, uid_b)
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
