"""P9.6: attaching an uploaded blind-input (.inp/.input/.json) file to
chat -- extends FilesSection.tsx's per-.xyz "Attach to conversation"
action to the other upload types, whose effect is a chat-context
injection (the file's raw text as a synthetic HumanMessage, see
app/agent/graph.py's append_attached_file) rather than a geometry/frame
state change, since a blind-input file has no geometry for
add_geometry_frames to act on.

G1 checks the mechanism directly via the real HTTP route: no LLM turn is
involved in attach_upload itself (same "bypasses the chat/LLM turn
machinery entirely" property the .xyz path already has), so this is fast
and deterministic.

G2 is the actual point of the feature, and needs a live agent turn: once
attached, can the model use the file's own content -- without the user
re-pasting it -- to fill a `blind` job draft's raw_input_text field when
asked to run it? A model failure here is a real, reportable gap in this
feature (not model-judgement noise the way P9.3's G4 was), since
raw_input_text is now sitting in the model's own context in full.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import AgentSession, record  # noqa: E402

# A minimal, real ORCA input -- small enough to read back verbatim in an
# assertion, but a real keyword line an input-sniffer/model would
# recognize as ORCA syntax.
ORCA_INPUT_TEXT = (
    "! HF STO-3G\n"
    "* xyz 0 1\n"
    "O   0.000000   0.000000   0.000000\n"
    "H   0.758602   0.000000   0.504284\n"
    "H   0.758602   0.000000  -0.504284\n"
    "*\n"
)


def main() -> None:
    admin = admin_client()

    r_up = admin.post("/api/uploads", files={"file": ("dz96_p96.inp", ORCA_INPUT_TEXT.encode(), "text/plain")})
    check("a .inp file can be uploaded", r_up.status_code == 201, f"{r_up.status_code} {r_up.text[:200]}")
    if r_up.status_code != 201:
        summary(exit_on_failure=False)
        return
    upload_id = r_up.json()["id"]

    # ------------------------------------------------------------ G1: the route itself
    s1 = AgentSession.new(admin, label="e2e attach blind input direct")
    r_attach = admin.post(f"/api/threads/{s1.thread_id}/attach_upload", json={"upload_id": upload_id})
    check("attach_upload accepts a .inp upload (no longer refused)", r_attach.status_code == 200,
          f"{r_attach.status_code} {r_attach.text[:300]}")
    body = r_attach.json() if r_attach.status_code == 200 else {}
    ok1 = (
        body.get("kind") == "raw_file"
        and isinstance(body.get("message"), dict)
        and "dz96_p96.inp" in (body["message"].get("content") or "")
        and "HF STO-3G" in (body["message"].get("content") or "")
    )
    check("the response carries kind='raw_file' and a message containing the file's own name and content",
          ok1, f"body={body}")
    record("G1-attach-route", "PASS" if ok1 else "FAIL", upload_id=upload_id)

    state1 = s1.state()
    msgs = state1.get("messages") or []
    in_state = any("HF STO-3G" in (m.get("content") or "") for m in msgs)
    check("the attached file's content is present in the thread's own checkpointed state "
          "(not just the one-off HTTP response)", in_state, f"n_messages={len(msgs)}")
    record("G1b-state-persisted", "PASS" if in_state else "FAIL", n_messages=len(msgs))
    s1.close()

    # ------------------------------------------------------------ G2: the model uses it
    s2 = AgentSession.new(admin, label="e2e attach blind input live use")
    r_attach2 = admin.post(f"/api/threads/{s2.thread_id}/attach_upload", json={"upload_id": upload_id})
    check("second attach (fresh thread) also succeeds", r_attach2.status_code == 200, str(r_attach2.status_code))

    turn = s2.say(
        "I just attached an ORCA input file above. Set up a blind job draft to run it verbatim, "
        "using ORCA. Use the file's content exactly as attached -- do not retype or paraphrase it. "
        "Do not submit, just build the draft.",
        timeout=240,
    )
    updates = [args.get("updates") or {} for name, args in turn.tools_requested() if name == "update_job_draft"]
    raw_texts = [u.get("raw_input_text") for u in updates if u.get("raw_input_text")]
    used_real_content = any(
        "HF STO-3G" in t and "0.758602" in t for t in raw_texts if isinstance(t, str)
    )
    print(f"[INFO] G2 update_job_draft calls: {updates}")
    check("the model fills raw_input_text from the attached file's own content (not retyped/paraphrased, "
          "not fabricated) when asked to run it as a blind job", used_real_content,
          f"raw_texts={[t[:120] if isinstance(t, str) else t for t in raw_texts]}")
    record("G2-model-uses-attached-content", "PASS" if used_real_content else "FAIL", updates=updates)
    s2.close()

    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
