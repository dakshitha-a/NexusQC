// ketcher-standalone's package.json "exports" map declares a "types"
// condition for its default entry ("ketcher-standalone") but not for the
// "./dist/binaryWasm" subpath MoleculeBuilderModal.tsx imports instead (see
// that file's comment for why: the default entry inlines its ~21MB wasm
// binary as base64 inside the JS bundle, and binaryWasm ships it as a real
// separate .wasm asset). TypeScript's "bundler" moduleResolution follows the
// exports map strictly and won't fall back to the matching index.d.ts that
// ships right next to that subpath's JS, so without this shim the import is
// typed `any` (TS7016).
//
// Both entries' index.d.ts are identical generated output -- `export * from
// './infrastructure/services'` -- so re-exporting from the root package's
// already-resolvable types is exact, and more stable across a version bump
// than pointing at a relative path into the package's internals.
declare module "ketcher-standalone/dist/binaryWasm" {
  export * from "ketcher-standalone";
}
