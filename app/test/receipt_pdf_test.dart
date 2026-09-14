import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:pdfx/pdfx.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/services/receipt_pdf_native.dart';

class _Document implements PdfDocument {
  int closes = 0;
  @override
  Future<void> close() async {
    closes++;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  test(
    'private PDF closes handle and deletes only its own viewer file',
    () async {
      final root = await Directory.systemTemp.createTemp('receipt-pdf-test');
      addTearDown(() => root.delete(recursive: true));
      final unrelated = File('${root.path}/keep.pdf');
      await unrelated.writeAsString('unrelated');
      final doc = _Document();
      String? path;
      final opened = await openReceiptPdf(
        Uint8List.fromList('%PDF-1.4'.codeUnits),
        isCurrent: () => true,
        temporaryDirectory: () async => root,
        openDocument: (file) async {
          path = file;
          expect(await File(file).readAsString(), '%PDF-1.4');
          return doc;
        },
      );
      expect(await File(path!).exists(), isTrue);
      await opened.close();
      await opened.close();
      expect(doc.closes, 1);
      expect(await File(path!).exists(), isFalse);
      expect(await unrelated.exists(), isTrue);
    },
  );
  test(
    'account invalidation during native PDF open closes late handle and file',
    () async {
      final root = await Directory.systemTemp.createTemp('receipt-pdf-test');
      addTearDown(() => root.delete(recursive: true));
      var current = true;
      final doc = _Document(), done = Completer<PdfDocument>();
      final started = Completer<void>();
      String? path;
      final opening = openReceiptPdf(
        Uint8List.fromList('%PDF-1.4'.codeUnits),
        isCurrent: () => current,
        temporaryDirectory: () async => root,
        openDocument: (file) {
          path = file;
          started.complete();
          return done.future;
        },
      );
      await started.future;
      current = false;
      done.complete(doc);
      await expectLater(opening, throwsA(isA<PlusApiException>()));
      expect(doc.closes, 1);
      expect(await File(path!).exists(), isFalse);
    },
  );
}
