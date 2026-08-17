// One place that turns something into a file on the user's disk.
//
// Four features download things, and without this they each grow their own copy
// of the same six lines -- including the same two mistakes the original inlined
// version in api.downloadPlotPng had:
//
//   - the <a> was never appended to the document. A detached anchor's .click()
//     works in Chrome and has historically been ignored in Firefox and Safari.
//   - URL.revokeObjectURL fired synchronously on the line after .click(), which
//     races the browser's own read of the blob.
//
// Both are fixed here once.

// Revoking on a later task rather than immediately: the click starts a download
// that reads the object URL asynchronously, so tearing it down in the same tick
// is a race. A timeout is the ordinary way to do this -- there is no event that
// fires when the browser is finished with the URL.
function cleanup(url: string, anchor: HTMLAnchorElement): void {
  setTimeout(() => {
    URL.revokeObjectURL(url);
    anchor.remove();
  }, 10_000);
}

// `href` may be any URL the browser can fetch under the page's own origin --
// an API route, a blob:, or a data: URI from a canvas capture.
export function triggerDownload(href: string, filename: string): void {
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.rel = "noopener";
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  // Nothing to revoke for a plain URL, but the anchor still has to go.
  setTimeout(() => a.remove(), 10_000);
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  cleanup(url, a);
}

// Text the app already holds -- a raw output log, an .xyz block -- without a
// round trip to fetch it again.
export function downloadText(text: string, filename: string, mime = "text/plain;charset=utf-8"): void {
  downloadBlob(new Blob([text], { type: mime }), filename);
}

// A data: URI, as returned by 3Dmol's pngURI()/apngURI(). Routed through a blob
// rather than handed to <a download> directly: Chrome caps data: URLs used this
// way at a couple of MB, and a 40-frame APNG of a vibration goes well past that.
export function downloadDataUri(dataUri: string, filename: string): void {
  const comma = dataUri.indexOf(",");
  const meta = dataUri.slice(5, comma); // strip "data:"
  const isBase64 = meta.endsWith(";base64");
  const mime = isBase64 ? meta.slice(0, -";base64".length) : meta;
  const payload = dataUri.slice(comma + 1);

  let blob: Blob;
  if (isBase64) {
    const binary = atob(payload);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    blob = new Blob([bytes], { type: mime || "application/octet-stream" });
  } else {
    blob = new Blob([decodeURIComponent(payload)], { type: mime || "text/plain" });
  }
  downloadBlob(blob, filename);
}
