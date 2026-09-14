// Start loading the first-party renderer without delaying Flutter startup.
// A receipt view awaits this promise before opening any document.
globalThis.receiptPdfReady = import('./init.mjs');
globalThis.receiptPdfReady.catch(() => {});
