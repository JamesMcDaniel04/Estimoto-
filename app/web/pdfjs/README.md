# Receipt PDF renderer

The Flutter `pdfx` 2.11.0 adapter documents PDF.js 4.6.82. Its compatible browser runtime, worker, character maps, standard fonts and licenses are vendored here from the npm package; `UPSTREAM.json` records the package integrity and exact hashes. No CDN is contacted at runtime.

`bootstrap.js` exposes an awaited startup promise. `init.mjs` admits only in-memory document data, forces local font/character-map assets, disables evaluation and document scripting, and rejects document URLs. The UI renders page canvases only, with no form, annotation or script layer. Native apps use the operating system renderer via an owned temporary file and explicitly close/unlink it on exit or account invalidation.

The two published Mozilla advisories were reviewed: CVE-2024-4367 is fixed from 4.2.67; CVE-2026-16633 affects the newer 5.6.83+ scripting implementation, not this 4.6.82 runtime. Any future renderer upgrade should recheck the adapter API and security advisories together.

Sources:
- https://pub.dev/packages/pdfx/versions/2.11.0
- https://github.com/mozilla/pdf.js/security/advisories/GHSA-wgrm-67xf-hhpq
- https://github.com/mozilla/pdf.js/security/advisories/GHSA-hq66-cqwq-w95j
