import 'dart:typed_data';
import 'receipt_pdf_types.dart';
import 'receipt_pdf_web.dart'
    if (dart.library.io) 'receipt_pdf_native.dart'
    as platform;
export 'receipt_pdf_types.dart';

Future<ReceiptPdfDocument> openPrivateReceiptPdf(
  Uint8List bytes, {
  required bool Function() isCurrent,
}) => platform.openReceiptPdf(bytes, isCurrent: isCurrent);
