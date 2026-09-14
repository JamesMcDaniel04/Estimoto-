import 'dart:io';
import 'dart:typed_data';
import 'package:path_provider/path_provider.dart';
import 'package:pdfx/pdfx.dart';
import '../data/repository.dart';
import 'receipt_pdf_types.dart';
import 'receipt_upload.dart';

final _activeFiles = <String>{};
Future<ReceiptPdfDocument> openReceiptPdf(
  Uint8List bytes, {
  required bool Function() isCurrent,
  Future<Directory> Function()? temporaryDirectory,
  Future<PdfDocument> Function(String)? openDocument,
}) async {
  void check() {
    if (!isCurrent()) {
      throw const PlusApiException('Sign in again to view your receipt.', 401);
    }
  }

  check();
  final root = await (temporaryDirectory ?? getTemporaryDirectory)();
  check();
  final folder = Directory('${root.path}/estimoto_receipt_previews_v1');
  await folder.create(recursive: true);
  check();
  final file = File('${folder.path}/${newReceiptOperation()}.pdf');
  _activeFiles.add(file.path);
  PdfDocument? document;
  Future<void> clean() async {
    try {
      if (await file.exists()) await file.delete();
    } finally {
      _activeFiles.remove(file.path);
    }
  }

  try {
    // Only stale files created by this preview feature are removed, after a crash.
    // Concurrent live views remain registered and are never deleted here.
    await for (final old in folder.list(followLinks: false)) {
      if (old is File &&
          !_activeFiles.contains(old.path) &&
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$',
          ).hasMatch(old.uri.pathSegments.last)) {
        await old.delete();
      }
    }
    check();
    await file.writeAsBytes(bytes, flush: true);
    check();
    document = await (openDocument ?? PdfDocument.openFile)(file.path);
    final result = ReceiptPdfDocument(document, cleanup: clean);
    if (!isCurrent()) {
      document = null;
      await result.close();
      throw const PlusApiException('Sign in again to view your receipt.', 401);
    }
    return result;
  } catch (_) {
    try {
      await document?.close();
    } finally {
      await clean();
    }
    rethrow;
  }
}
