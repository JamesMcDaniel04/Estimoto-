// PDF.js 4.6.82, vendored with pdfx's compatible API. No CDN or PDF URL access.
import * as renderer from './build/pdf.min.mjs';
renderer.GlobalWorkerOptions.workerSrc = new URL('./build/pdf.worker.min.mjs', import.meta.url).href;
const localOptions = {
  cMapUrl: new URL('./cmaps/', import.meta.url).href,
  cMapPacked: true,
  standardFontDataUrl: new URL('./standard_fonts/', import.meta.url).href,
  isEvalSupported: false,
  enableScripting: false,
};
globalThis.pdfRenderOptions = localOptions;
globalThis.pdfjsLib = {
  ...renderer,
  getDocument(options) {
    if (!options || !(options.data instanceof ArrayBuffer || ArrayBuffer.isView(options.data))) {
      throw new Error('Receipts must be opened from private in-memory bytes.');
    }
    return renderer.getDocument({ ...options, ...localOptions, url: undefined });
  },
};
