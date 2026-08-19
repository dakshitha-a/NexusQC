"""Phase 3 (P3.1 + P3.3): the uploaded-file manager's lifecycle
(server/routes/uploads.py: upload/list/quota/delete/clear-all,
ownership-scoped) and attach semantics (server/routes/chat.py's
attach_upload: 1/2 geometries become molecule_frames, 3+ become a
completed `geometry_set` job with no engine/worker).

Run against the real docker-compose dev stack (needs QC_AGENT_DATABASE_URL
for the ownership checks this script exists to prove -- see CLAUDE.md's
testing conventions).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

WATER_XYZ = (
    "3\nwater\n"
    "O  0.000000  0.000000  0.117300\n"
    "H  0.000000  0.757200 -0.469200\n"
    "H  0.000000 -0.757200 -0.469200\n"
)

TWO_FRAME_XYZ = WATER_XYZ + (
    "3\nwater stretched\n"
    "O  0.000000  0.000000  0.200000\n"
    "H  0.000000  0.800000 -0.500000\n"
    "H  0.000000 -0.800000 -0.500000\n"
)

THREE_FRAME_XYZ = TWO_FRAME_XYZ + (
    "3\nwater bent\n"
    "O  0.000000  0.000000  0.300000\n"
    "H  0.000000  0.850000 -0.550000\n"
    "H  0.000000 -0.850000 -0.550000\n"
)

MALFORMED_XYZ = "3\nbroken\nO 0 0 0\nH 0 1 0\n"  # declares 3 atoms, only 2 follow


def _upload(client, filename: str, content: bytes):
    return client.post("/api/uploads", files={"file": (filename, content, "application/octet-stream")})


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    token_b = mint_invite(admin)
    client_a, user_a = register(token_a)
    client_b, user_b = register(token_b)

    # --- P3.1: lifecycle, quota, ownership -----------------------------

    r_single = _upload(client_a, "water.xyz", WATER_XYZ.encode())
    check("single-geometry upload succeeds (201)", r_single.status_code == 201, f"{r_single.status_code} {r_single.text[:200]}")
    single = r_single.json()
    check("single-geometry sniff is n=1/kind=single", single.get("sniff") == {"n_geometries": 1, "kind": "single"}, str(single))

    r_pair = _upload(client_a, "pair.xyz", TWO_FRAME_XYZ.encode())
    pair = r_pair.json()
    check("2-geometry sniff is n=2/kind=pair", pair.get("sniff") == {"n_geometries": 2, "kind": "pair"}, str(pair))

    r_set = _upload(client_a, "set.xyz", THREE_FRAME_XYZ.encode())
    geomset = r_set.json()
    check("3-geometry sniff is n=3/kind=set", geomset.get("sniff") == {"n_geometries": 3, "kind": "set"}, str(geomset))

    r_blind = _upload(client_a, "job.inp", b"! HF STO-3G\n* xyz 0 1\nH 0 0 0\nH 0 0 0.74\n*\n")
    blind = r_blind.json()
    check("blind .inp upload has no sniff", blind.get("sniff") is None, str(blind))

    r_bad_ext = _upload(client_a, "evil.exe", b"binary")
    check("disallowed extension is refused (400)", r_bad_ext.status_code == 400, f"{r_bad_ext.status_code} {r_bad_ext.text[:200]}")

    r_malformed = _upload(client_a, "broken.xyz", MALFORMED_XYZ.encode())
    check(
        "malformed xyz content is refused at upload time (400), not stored",
        r_malformed.status_code == 400,
        f"{r_malformed.status_code} {r_malformed.text[:200]}",
    )

    r_list_a = client_a.get("/api/uploads")
    ids_a = {r["id"] for r in r_list_a.json()}
    check(
        "A's list contains exactly the 4 valid uploads, not the rejected ones",
        ids_a == {single["id"], pair["id"], geomset["id"], blind["id"]},
        str(sorted(ids_a)),
    )

    r_list_b = client_b.get("/api/uploads")
    check("B sees none of A's uploads", r_list_b.json() == [], str(r_list_b.json()))

    # Force a fresh usage_report() before checking: app/auth/storage_quota.py
    # caches it for ADMIN_STORAGE_CACHE_TTL_SECONDS (20s, shared by GET
    # /api/kb/quota's identical pattern), and an earlier script in a full
    # run_backend.sh pass may have populated that cache before user A
    # existed -- confirmed real by reproducing it standalone. A no-op admin
    # config PATCH is the documented way to force an early refresh
    # (server/routes/admin.py's own invalidate_usage_report_cache() call).
    admin.patch("/api/admin/config", json={"key": "per_user_uploads_quota_bytes", "value": 500_000_000})
    r_quota_a = client_a.get("/api/uploads/quota")
    quota = r_quota_a.json()
    check(
        "A's quota reports the per-user category with real usage",
        quota.get("category") == "per_user_uploads" and quota.get("used_bytes", 0) > 0
        and quota.get("quota_bytes") == 500_000_000,
        str(quota),
    )

    r_cross_delete = client_b.delete(f"/api/uploads/{single['id']}")
    check(
        "B cannot delete A's upload (404, ownership-scoped)",
        r_cross_delete.status_code == 404,
        f"{r_cross_delete.status_code} {r_cross_delete.text[:200]}",
    )
    r_cross_content = client_b.get(f"/api/uploads/{single['id']}/content")
    check(
        "B cannot read A's upload content (404)",
        r_cross_content.status_code == 404,
        f"{r_cross_content.status_code} {r_cross_content.text[:200]}",
    )

    r_own_content = client_a.get(f"/api/uploads/{single['id']}/content")
    check(
        "A can read their own upload content back verbatim",
        r_own_content.status_code == 200 and r_own_content.text == WATER_XYZ,
        f"{r_own_content.status_code} {r_own_content.text[:200]!r}",
    )

    r_delete_single = client_a.delete(f"/api/uploads/{single['id']}")
    check("A can delete their own upload", r_delete_single.status_code == 200, f"{r_delete_single.status_code}")
    r_get_after_delete = client_a.get(f"/api/uploads/{single['id']}/content")
    check("deleted upload's content is gone (404)", r_get_after_delete.status_code == 404)

    # --- P3.3: attach semantics -----------------------------------------

    r_thread = client_a.post("/api/threads", json={"label": "up_01 attach test"})
    thread_id = r_thread.json()["thread_id"]

    r_attach_pair = client_a.post(f"/api/threads/{thread_id}/attach_upload", json={"upload_id": pair["id"]})
    check(
        "attaching a 2-geometry upload returns kind=frames with 2 frame ids",
        r_attach_pair.status_code == 200 and r_attach_pair.json().get("kind") == "frames"
        and len(r_attach_pair.json().get("frame_ids", [])) == 2,
        f"{r_attach_pair.status_code} {r_attach_pair.text[:300]}",
    )
    attach_state = r_attach_pair.json().get("state", {})
    check(
        "the first attached frame becomes the active molecule",
        bool((attach_state.get("molecule") or {}).get("symbols")),
        str(attach_state.get("molecule")),
    )

    r_state_after_pair = client_a.get(f"/api/threads/{thread_id}/state")
    frames_after_pair = r_state_after_pair.json().get("molecule_frames", [])
    check("thread state now carries 2 molecule_frames from the pair attach", len(frames_after_pair) == 2, str(len(frames_after_pair)))

    r_attach_set = client_a.post(f"/api/threads/{thread_id}/attach_upload", json={"upload_id": geomset["id"]})
    check(
        "attaching a 3-geometry upload returns kind=geometry_set with a job_id",
        r_attach_set.status_code == 200 and r_attach_set.json().get("kind") == "geometry_set"
        and r_attach_set.json().get("job_id"),
        f"{r_attach_set.status_code} {r_attach_set.text[:300]}",
    )
    geomset_job_id = r_attach_set.json().get("job_id")

    r_state_after_set = client_a.get(f"/api/threads/{thread_id}/state")
    state_after_set = r_state_after_set.json()
    check(
        "molecule_frames is UNCHANGED by a geometry_set attach (still 2, not 3)",
        len(state_after_set.get("molecule_frames", [])) == 2,
        str(len(state_after_set.get("molecule_frames", []))),
    )
    # serialize_message (app/agent/serialize.py) flattens additional_kwargs
    # ["nexus_notice"] to a top-level "notice" key -- see its own docstring.
    notice_messages = [
        m for m in state_after_set.get("messages", [])
        if (m.get("notice") or {}).get("kind") == "geometry_set_attached"
    ]
    check(
        "a checkpointed notice message announces the geometry_set job",
        len(notice_messages) == 1 and notice_messages[0]["notice"]["job_id"] == geomset_job_id,
        str(notice_messages),
    )

    r_job = client_a.get(f"/api/jobs/{geomset_job_id}")
    job = r_job.json()
    check(
        "the geometry_set job is immediately completed with the right task/summary",
        job.get("status") == "completed" and job.get("task") == "geometry_set"
        and (job.get("summary") or {}).get("n_geometries") == 3,
        str(job),
    )

    r_job_cross = client_b.get(f"/api/jobs/{geomset_job_id}")
    check("B cannot see A's geometry_set job (404)", r_job_cross.status_code == 404, f"{r_job_cross.status_code}")

    # --- P3.3: tagging one frame of a geometry_set into a draft -----------
    # "tag frame 2 into a draft" (docs/OVERHAUL_PLAN.md's P3.3 accept line):
    # pulling geometry #2 (1-based) out of the geometry_set job and
    # attaching it as the active molecule frame, the same slot the normal
    # draft path reads set_geometry from.
    r_tag = client_a.post(f"/api/threads/{thread_id}/tag_job_frame", json={"job_id": geomset_job_id, "frame_index": 2})
    check(
        "tagging frame 2 of the geometry_set succeeds and returns a frame_id",
        r_tag.status_code == 200 and r_tag.json().get("frame_id"),
        f"{r_tag.status_code} {r_tag.text[:300]}",
    )
    tagged_molecule = (r_tag.json().get("state") or {}).get("molecule") or {}
    check(
        "the tagged frame is now the active molecule, and it's frame 2 (water stretched)",
        tagged_molecule.get("name") == "water stretched",
        str(tagged_molecule),
    )

    r_tag_oob = client_a.post(
        f"/api/threads/{thread_id}/tag_job_frame", json={"job_id": geomset_job_id, "frame_index": 99},
    )
    check(
        "tagging an out-of-range frame_index is refused (400), not silently clamped",
        r_tag_oob.status_code == 400,
        f"{r_tag_oob.status_code} {r_tag_oob.text[:200]}",
    )

    r_tag_cross = client_b.post(
        f"/api/threads/{thread_id}/tag_job_frame", json={"job_id": geomset_job_id, "frame_index": 1},
    )
    check(
        "B cannot tag a frame from A's geometry_set job into A's thread (404)",
        r_tag_cross.status_code == 404,
        f"{r_tag_cross.status_code} {r_tag_cross.text[:200]}",
    )

    r_attach_blind = client_a.post(f"/api/threads/{thread_id}/attach_upload", json={"upload_id": blind["id"]})
    check(
        "attaching a non-.xyz upload (blind .inp) is refused (400)",
        r_attach_blind.status_code == 400,
        f"{r_attach_blind.status_code} {r_attach_blind.text[:200]}",
    )

    r_attach_cross = client_b.post(f"/api/threads/{thread_id}/attach_upload", json={"upload_id": pair["id"]})
    check(
        "B attaching A's upload id into A's thread is refused (owner scope, 404, then thread-ownership 404 either way)",
        r_attach_cross.status_code == 404,
        f"{r_attach_cross.status_code} {r_attach_cross.text[:200]}",
    )

    # --- clear-all --------------------------------------------------------

    r_clear = client_a.delete("/api/uploads")
    deleted = r_clear.json().get("deleted", [])
    check(
        "clear-all removes A's remaining uploads (pair, set, blind -- single already deleted individually)",
        set(deleted) == {pair["id"], geomset["id"], blind["id"]},
        str(sorted(deleted)),
    )
    r_list_after_clear = client_a.get("/api/uploads")
    check("A's upload list is empty after clear-all", r_list_after_clear.json() == [], str(r_list_after_clear.json()))

    cleanup_user(admin, user_a["id"])
    cleanup_user(admin, user_b["id"])
    summary()


if __name__ == "__main__":
    main()
