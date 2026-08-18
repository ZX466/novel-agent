# F4 Knowledge-Base Upload Security Specification

This specification is required before implementing any knowledge-base upload
endpoint. Uploads must be authenticated with the shared `X-API-Key` dependency
and scoped to the document owner (`owner_key_hash`). A filename, MIME type, or
form field is never a security boundary by itself.

## Required controls

- Accept only an explicit allowlist of formats required by the product (initial
  recommendation: UTF-8 plain text and PDF; reject archives, executables,
  office macro formats, HTML/SVG, and unknown extensions). Validate both the
  normalized extension and detected content type/magic bytes; reject conflicts.
- Enforce a hard request/upload limit before buffering. Recommended default is
  10 MiB per file and 20 MiB per request, configurable only downward in local
  deployments. Stream to a bounded temporary file and abort when the limit is
  exceeded; never call `read()` on an unbounded upload.
- Normalize the supplied filename with `Path(name).name`, Unicode-normalize it,
  remove control characters and trailing dots/spaces, and replace anything
  outside `[A-Za-z0-9._-]`. Generate a server-side UUID storage name. Never use
  the client filename as a path or as an object key.
- Store files outside the static/frontend tree with permissions restricted to
  the backend service. Persist only the owner hash, generated name, validated
  media type, byte size, and a content SHA-256; do not persist API keys.
- Resolve the parent document using `get_document(..., owner_key_hash=...)`
  before accepting or exposing an upload. Return 404 for missing, deleted, or
  foreign documents so IDs cannot be used as an ownership oracle.
- Parse and sanitize extracted content before indexing. HTML output must pass
  the existing `nh3` allowlist; remove scripts, event attributes, embeds,
  styles, external references, and unsafe URL schemes. Treat PDF text as
  untrusted plain text and bound extracted text (recommended 1 MiB).
- Do not fetch URLs, images, fonts, redirects, or embedded resources found in
  an upload. The upload path must make no outbound network requests (no SSRF).
- Reject decompression/archive bombs and encrypted/password-protected files.
  Do not invoke shell commands or format converters with user-controlled
  arguments; if conversion is later required, use a sandboxed worker with a
  timeout and resource limits.
- Rate-limit uploads per API-key owner and enforce a total per-owner storage
  quota. Delete temporary files in `finally` on success, rejection, timeout,
  and client disconnect.
- Return generic errors to clients. Log only owner hash, generated ID, size,
  detected type, and rejection category; never log file contents, filenames
  containing secrets, or API keys.

## Acceptance tests

Test missing/invalid API key, foreign/deleted parent, oversized body, extension
and magic-byte mismatch, traversal/control-character filenames, script/event
HTML, `javascript:` URLs, PDF with external references, archive bombs, quota
exhaustion, and cleanup after parser failure. Assert no outbound network call
and no file is written outside the upload root.

## Review gate

The implementation is not mergeable until every control above has a regression
test. In particular, owner scoping and bounded streaming must be tested at the
API boundary, not only in helper functions.
