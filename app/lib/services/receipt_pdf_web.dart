import 'dart:typed_data';
import 'package:pdfx/pdfx.dart';
import '../data/repository.dart';
import 'receipt_pdf_ready.dart';
import 'receipt_pdf_types.dart';

Future<ReceiptPdfDocument> openReceiptPdf(
  Uint8List bytes, {
  required bool Function() isCurrent,
}) async {
  await ensureReceiptPdfReady();
  if (!isCurrent()) {
    throw const PlusApiException('Sign in again to view your receipt.', 401);
  }
  final doc = await PdfDocument.openData(Uint8List.fromList(bytes));
  final result = ReceiptPdfDocument(doc);
  if (!isCurrent()) {
    await result.close();
    throw const PlusApiException('Sign in again to view your receipt.', 401);
  }
  return result;
}
