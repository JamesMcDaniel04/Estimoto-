import 'package:pdfx/pdfx.dart';

class ReceiptPdfDocument {
  ReceiptPdfDocument(this.document, {this.cleanup});
  final PdfDocument document;
  final Future<void> Function()? cleanup;
  Future<void>? _closed;
  Future<void> close() => _closed ??= _close();
  Future<void> _close() async {
    try {
      await document.close();
    } finally {
      await cleanup?.call();
    }
  }
}
