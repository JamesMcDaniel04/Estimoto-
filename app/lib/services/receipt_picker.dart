import 'dart:typed_data';
import 'package:file_selector/file_selector.dart';
import '../data/repository.dart';
import 'receipt_pending.dart';

Future<XFile?> chooseReceiptPdf() => openFile(
  acceptedTypeGroups: const [
    XTypeGroup(
      label: 'PDF receipts',
      extensions: ['pdf'],
      mimeTypes: ['application/pdf'],
      uniformTypeIdentifiers: ['com.adobe.pdf'],
    ),
  ],
);
Future<Uint8List> readReceiptFile(XFile file) async {
  if (await file.length() > maxReceiptBytes) {
    throw const PlusApiException('Choose a receipt no larger than 10 MB.', 413);
  }
  final bytes = await file.readAsBytes();
  if (bytes.isEmpty || bytes.length > maxReceiptBytes) {
    throw const PlusApiException('Choose a receipt no larger than 10 MB.', 413);
  }
  return bytes;
}

String receiptMime(Uint8List bytes) {
  bool begins(List<int> signature) =>
      bytes.length >= signature.length &&
      List.generate(
        signature.length,
        (i) => bytes[i] == signature[i],
      ).every((v) => v);
  if (begins([0xff, 0xd8, 0xff])) return 'image/jpeg';
  if (begins([137, 80, 78, 71, 13, 10, 26, 10])) return 'image/png';
  if (begins([37, 80, 68, 70, 45])) return 'application/pdf';
  if (begins([82, 73, 70, 70]) &&
      bytes.length >= 12 &&
      String.fromCharCodes(bytes.sublist(8, 12)) == 'WEBP') {
    return 'image/webp';
  }
  throw const PlusApiException(
    'Choose a readable JPEG, PNG, WebP or PDF receipt.',
    415,
  );
}

String receiptFilename(String name, String mime) {
  final clean = name
      .split(RegExp(r'[/\\]'))
      .last
      .replaceAll(RegExp(r'[\x00-\x1f\x7f]'), '')
      .trim();
  final stem = (clean.isEmpty ? 'receipt' : clean).replaceFirst(
    RegExp(r'\.[^.]*$'),
    '',
  );
  final ext = switch (mime) {
    'application/pdf' => 'pdf',
    'image/png' => 'png',
    'image/webp' => 'webp',
    _ => 'jpg',
  };
  return '${stem.length > 170 ? stem.substring(0, 170) : stem}.$ext';
}
