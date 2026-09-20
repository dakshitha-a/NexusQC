# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

- **Rebuild the dev stack onto v1.1.1** (the quieter chat-box focus and
  hairline in-progress cue). The checkout is at the release, but the api
  image and `frontend/dist` are still built from `02e5424`. A dry run of
  `scripts/update.sh` on 2026-09-20 passed every gate with no destructive
  changes and no jobs running. Run the update from the app's deployment
  section or with `scripts/update.sh --yes`, then confirm with
  `grep -c hairline-clip frontend/dist/assets/*.css` (expect 1 for the main
  bundle).
