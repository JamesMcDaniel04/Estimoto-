import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/services/receipt_pending.dart';
import 'package:estimoto_plus/services/receipt_pending_native.dart';
import 'package:estimoto_plus/services/receipt_upload.dart';
import 'package:estimoto_plus/services/receipt_picker.dart';
import 'package:estimoto_plus/data/repository.dart';

const receiptOperation = 'e28dca35-139d-4bf3-99b1-527bb1669001';
ReceiptPending record({
  String owner = 'alice',
  String id = 'record-1',
  String name = 'receipt.pdf',
}) => ReceiptPending(
  ownerId: owner,
  recordId: id,
  operationId: receiptOperation,
  filename: name,
  mimeType: 'application/pdf',
  bytes: Uint8List.fromList('%PDF-1.4 receipt'.codeUnits),
);

void main() {
  test('receipt types and 10 MB bound fail closed before persistence', () {
    expect(receiptMime(Uint8List.fromList([255, 216, 255])), 'image/jpeg');
    expect(
      receiptMime(Uint8List.fromList([137, 80, 78, 71, 13, 10, 26, 10])),
      'image/png',
    );
    expect(
      receiptMime(Uint8List.fromList('%PDF-1.4'.codeUnits)),
      'application/pdf',
    );
    expect(
      receiptMime(
        Uint8List.fromList([82, 73, 70, 70, 0, 0, 0, 0, 87, 69, 66, 80]),
      ),
      'image/webp',
    );
    expect(
      () => receiptMime(Uint8List.fromList('<html>'.codeUnits)),
      throwsA(isA<PlusApiException>()),
    );
    expect(
      () => ReceiptPending(
        ownerId: 'alice',
        recordId: 'record-1',
        operationId: receiptOperation,
        filename: 'x.pdf',
        mimeType: 'application/pdf',
        bytes: Uint8List(maxReceiptBytes + 1),
      ),
      throwsA(isA<ReceiptPendingException>()),
    );
    expect(
      receiptFilename('a' * 200 + '.pdf', 'application/pdf').length,
      lessThanOrEqualTo(180),
    );
  });

  test('receipt retry freezes owner, record, name and bytes', () async {
    final store = MemoryReceiptPendingStore();
    final original = record();
    await store.write(original);
    await store.write(record());
    expect(() => original.bytes[0] = 0, throwsUnsupportedError);
    for (final changed in [
      record(id: 'record-2'),
      record(name: 'changed.pdf'),
    ]) {
      await expectLater(
        store.write(changed),
        throwsA(isA<ReceiptPendingException>()),
      );
    }
    expect(await store.read('bob'), isNull);
    expect(await store.clear('bob', receiptOperation), isFalse);
    expect((await store.read('alice'))!.samePayload(original), isTrue);
  });
  test(
    'native store survives restart and exact clear preserves another owner',
    () async {
      final dir = await Directory.systemTemp.createTemp('receipt-store-test');
      addTearDown(() => dir.delete(recursive: true));
      final first = NativeReceiptPendingStore(
        supportDirectory: () async => dir,
      );
      await first.write(record());
      await first.write(record(owner: 'bob'));
      final restarted = NativeReceiptPendingStore(
        supportDirectory: () async => dir,
      );
      expect((await restarted.read('alice'))!.samePayload(record()), isTrue);
      await restarted.clear('alice', receiptOperation);
      expect(await restarted.read('alice'), isNull);
      expect(await restarted.read('bob'), isNotNull);
    },
  );
  test(
    'uncertain upload preserves exact operation; explicit retry clears after receipt',
    () async {
      final store = MemoryReceiptPendingStore();
      final calls = <ReceiptPending>[];
      final session = ReceiptUpload(
        ownerId: 'alice',
        recordId: 'record-1',
        store: store,
        isCurrent: () => true,
        send: (value) async {
          calls.add(value);
          if (calls.length == 1) throw const PlusApiException('Timed out', 408);
          return <String, dynamic>{'id': 'receipt-1'};
        },
      );
      await session.stage(record());
      await expectLater(session.retry(), throwsA(isA<PlusApiException>()));
      expect(await store.read('alice'), isNotNull);
      final restarted = ReceiptUpload(
        ownerId: 'alice',
        recordId: 'record-1',
        store: store,
        isCurrent: () => true,
        send: session.send,
      );
      expect(await restarted.restore(), isNotNull);
      expect(calls.length, 1, reason: 'Recovery never automatically uploads');
      await restarted.retry();
      expect(calls.length, 2);
      expect(calls.last.samePayload(calls.first), isTrue);
      expect(await store.read('alice'), isNull);
    },
  );
  test('account change during device write prevents upload', () async {
    var current = true;
    final store = _DelayedStore(() => current = false);
    var calls = 0;
    final session = ReceiptUpload(
      ownerId: 'alice',
      recordId: 'record-1',
      store: store,
      isCurrent: () => current,
      send: (_) async {
        calls++;
        return <String, dynamic>{'id': 'saved'};
      },
    );
    await expectLater(
      session.stage(record()),
      throwsA(isA<PlusApiException>()),
    );
    expect(calls, 0);
    expect(await store.read('alice'), isNotNull);
  });
  test('recovery cannot attach a saved file to a different record', () async {
    final store = MemoryReceiptPendingStore();
    await store.write(record());
    var calls = 0;
    final session = ReceiptUpload(
      ownerId: 'alice',
      recordId: 'other-record',
      store: store,
      isCurrent: () => true,
      send: (_) async {
        calls++;
        return <String, dynamic>{};
      },
    );
    await expectLater(session.retry(), throwsA(isA<PlusApiException>()));
    expect(calls, 0);
    expect(await store.read('alice'), isNotNull);
  });
  test(
    'USD parsing uses exact cents and rejects extra decimals or negative totals',
    () {
      expect(parseReceiptCost('1234.56'), 123456);
      expect(parseReceiptCost('0.01'), 1);
      expect(parseReceiptCost('12'), 1200);
      expect(parseReceiptCost(''), isNull);
      expect(parseReceiptCost('1000000'), 100000000);
      expect(receiptCost(123456789), '\$1,234,567.89');
      expect(receiptCost(-125), '-\$1.25');
      for (final bad in ['1.001', '-1', 'NaN', '1e3', '1,000']) {
        expect(() => parseReceiptCost(bad), throwsFormatException);
      }
    },
  );
}

class _DelayedStore extends MemoryReceiptPendingStore {
  _DelayedStore(this.after);
  final void Function() after;
  @override
  Future<void> write(ReceiptPending value) async {
    await super.write(value);
    after();
  }
}
