import 'dart:js_interop';

@JS('receiptPdfReady')
external JSPromise<JSAny?>? get _ready;
Future<void> ensureReceiptPdfReady() async {
  final ready = _ready;
  if (ready == null) throw StateError('Receipt preview unavailable.');
  await ready.toDart;
}
