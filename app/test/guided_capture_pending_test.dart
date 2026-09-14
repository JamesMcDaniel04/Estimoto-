import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/services/guided_capture_pending.dart';
import 'package:estimoto_plus/services/guided_capture_pending_native.dart';

const operation = 'e28dca35-139d-4bf3-99b1-527bb1669001';
const nextOperation = 'e28dca35-139d-4bf3-99b1-527bb1669002';
GuidedCapturePending record({
  String owner = 'alice',
  String op = operation,
  List<int> bytes = const [1, 2, 3],
}) => GuidedCapturePending(
  ownerId: owner,
  estimateId: 'estimate-1',
  operationId: op,
  captureKey: 'vin',
  bodyStyle: 'sedan',
  mimeType: 'image/jpeg',
  bytes: Uint8List.fromList(bytes),
);

void main() {
  test('bytes are copied and exposed only as immutable data', () {
    final bytes = Uint8List.fromList([1, 2, 3]);
    final saved = GuidedCapturePending(
      ownerId: 'alice',
      estimateId: 'estimate-1',
      operationId: operation,
      captureKey: 'vin',
      bodyStyle: 'sedan',
      mimeType: 'image/jpeg',
      bytes: bytes,
    );
    bytes[0] = 9;
    expect(saved.bytes, [1, 2, 3]);
    expect(() => saved.bytes[0] = 9, throwsUnsupportedError);
    expect(saved.sha256, hasLength(64));
  });
  test(
    'identical replay is stable; changed payload and another operation cannot overwrite',
    () async {
      final store = MemoryGuidedCapturePendingStore();
      await store.write(record());
      await store.write(record());
      await expectLater(
        store.write(record(bytes: [3, 2, 1])),
        throwsA(isA<GuidedCapturePendingException>()),
      );
      await expectLater(
        store.write(record(op: nextOperation)),
        throwsA(isA<GuidedCapturePendingException>()),
      );
      expect((await store.read('alice'))!.bytes, [1, 2, 3]);
    },
  );
  test(
    'same operation freezes every upload field, not only image bytes',
    () async {
      final store = MemoryGuidedCapturePendingStore();
      await store.write(record());
      for (final changed in [
        GuidedCapturePending(
          ownerId: 'alice',
          estimateId: 'estimate-2',
          operationId: operation,
          captureKey: 'vin',
          bodyStyle: 'sedan',
          mimeType: 'image/jpeg',
          bytes: Uint8List.fromList([1, 2, 3]),
        ),
        GuidedCapturePending(
          ownerId: 'alice',
          estimateId: 'estimate-1',
          operationId: operation,
          captureKey: 'front',
          bodyStyle: 'sedan',
          mimeType: 'image/jpeg',
          bytes: Uint8List.fromList([1, 2, 3]),
        ),
        GuidedCapturePending(
          ownerId: 'alice',
          estimateId: 'estimate-1',
          operationId: operation,
          captureKey: 'vin',
          bodyStyle: 'suv',
          mimeType: 'image/jpeg',
          bytes: Uint8List.fromList([1, 2, 3]),
        ),
        GuidedCapturePending(
          ownerId: 'alice',
          estimateId: 'estimate-1',
          operationId: operation,
          captureKey: 'vin',
          bodyStyle: 'sedan',
          mimeType: 'image/png',
          bytes: Uint8List.fromList([1, 2, 3]),
        ),
      ]) {
        await expectLater(
          store.write(changed),
          throwsA(isA<GuidedCapturePendingException>()),
        );
      }
      expect((await store.read('alice'))!.samePayload(record()), isTrue);
    },
  );
  test(
    'different owners have isolated unresolved records and stale clears cannot erase',
    () async {
      final store = MemoryGuidedCapturePendingStore();
      await store.write(record());
      expect(await store.read('bob'), isNull);
      expect(await store.clear('bob', operation), isFalse);
      await store.write(record(owner: 'bob', op: nextOperation));
      expect(await store.clear('alice', nextOperation), isFalse);
      expect((await store.read('alice'))!.operationId, operation);
      expect(await store.clear('alice', operation), isTrue);
      expect((await store.read('bob'))!.operationId, nextOperation);
    },
  );
  test('metadata and body size fail closed before persistence', () {
    expect(
      () => record(bytes: []),
      throwsA(isA<GuidedCapturePendingException>()),
    );
    expect(
      () => record(bytes: Uint8List(maxGuidedCaptureBytes + 1)),
      throwsA(isA<GuidedCapturePendingException>()),
    );
    expect(
      () => record(owner: '../another-owner'),
      throwsA(isA<GuidedCapturePendingException>()),
    );
    expect(
      () => record(op: 'not-an-operation'),
      throwsA(isA<GuidedCapturePendingException>()),
    );
  });
  test(
    'version, unknown fields, digest, ownership and excessive encoded data fail closed',
    () {
      final value =
          jsonDecode(GuidedCapturePendingCodec.encode(record()))
              as Map<String, dynamic>;
      for (final invalid in [
        {...value, 'version': 2},
        {...value, 'version': 1.0},
        {...value, 'token': 'forbidden'},
        {...value, 'sha256': '0' * 64},
        {...value, 'owner_id': 'bob'},
        {...value, 'byte_size': maxGuidedCaptureBytes + 1},
      ]) {
        expect(
          () => GuidedCapturePendingCodec.decode(
            jsonEncode(invalid),
            ownerId: 'alice',
          ),
          throwsA(isA<GuidedCapturePendingException>()),
        );
      }
      expect(
        () => GuidedCapturePendingCodec.decode(
          'x' * (maxGuidedCaptureSerializedBytes + 1),
          ownerId: 'alice',
        ),
        throwsA(isA<GuidedCapturePendingException>()),
      );
    },
  );
  test(
    'corruption cannot be overwritten; explicit corrupt discard is scoped and preserves valid records',
    () async {
      final backing = <String, String>{'alice': 'corrupt'};
      final store = MemoryGuidedCapturePendingStore(backing: backing);
      await expectLater(
        store.read('alice'),
        throwsA(isA<GuidedCapturePendingException>()),
      );
      await expectLater(
        store.write(record()),
        throwsA(isA<GuidedCapturePendingException>()),
      );
      expect(await store.discardCorrupt('bob'), isFalse);
      expect(await store.discardCorrupt('alice'), isTrue);
      await store.write(record());
      expect(await store.discardCorrupt('alice'), isFalse);
      expect(await store.read('alice'), isNotNull);
    },
  );
  test(
    'native atomic store survives new instances and serializes competing writes',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'guided-pending-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final first = NativeGuidedCapturePendingStore(
        supportDirectory: () async => directory,
      );
      final restarted = NativeGuidedCapturePendingStore(
        supportDirectory: () async => directory,
      );
      await first.write(record());
      expect((await restarted.read('alice'))!.sha256, record().sha256);
      expect(await restarted.clear('alice', nextOperation), isFalse);
      expect(await restarted.clear('alice', operation), isTrue);
      final outcomes = await Future.wait([
        first.write(record()).then((_) => true).catchError((_) => false),
        restarted
            .write(record(op: nextOperation))
            .then((_) => true)
            .catchError((_) => false),
      ]);
      expect(outcomes.where((v) => v), hasLength(1));
      expect(await restarted.read('bob'), isNull);
    },
  );
  test(
    'native missing target recovers synced staging bytes without an upload',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'guided-pending-stage-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final store = NativeGuidedCapturePendingStore(
        supportDirectory: () async => directory,
      );
      await store.write(record());
      final saved =
          (await directory
                      .list(recursive: true)
                      .where((f) => f.path.endsWith('.json'))
                      .toList())
                  .single
              as File;
      await saved.rename('${saved.path}.tmp');
      final restarted = NativeGuidedCapturePendingStore(
        supportDirectory: () async => directory,
      );
      expect((await restarted.read('alice'))!.operationId, operation);
      expect(await saved.exists(), isTrue);
    },
  );
  test(
    'native corruption and filesystem failure surface generic recoverable errors',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'guided-pending-corrupt-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final store = NativeGuidedCapturePendingStore(
        supportDirectory: () async => directory,
      );
      await store.write(record());
      final saved =
          (await directory
                      .list(recursive: true)
                      .where((f) => f.path.endsWith('.json'))
                      .toList())
                  .single
              as File;
      await saved.writeAsString('corrupt', flush: true);
      await expectLater(
        store.read('alice'),
        throwsA(isA<GuidedCapturePendingException>()),
      );
      await expectLater(
        store.write(record(op: nextOperation)),
        throwsA(isA<GuidedCapturePendingException>()),
      );
      expect(await store.discardCorrupt('alice'), isTrue);
      final broken = NativeGuidedCapturePendingStore(
        supportDirectory: () async =>
            throw const FileSystemException('private path or system message'),
      );
      try {
        await broken.write(record());
        fail('must fail');
      } on GuidedCapturePendingException catch (e) {
        expect(e.toString(), isNot(contains('private path')));
      }
    },
  );
}
