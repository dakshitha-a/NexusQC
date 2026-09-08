// Injected by vite.config.ts's `define` at build time, from the GIT_COMMIT
// build arg the image build passes in. A host `npm run build` with nothing set
// leaves it 'unknown', which every reader treats as "cannot tell" rather than
// as a mismatch -- so this is never a reason to tell somebody to reload.
declare const __BUILD_SHA__: string
