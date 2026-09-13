import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/services/estimate_capture.dart';

class _Picker implements EstimatePhotoPicker {
  Future<XFile?> Function()? onPick;
  XFile? lost;
  int picks = 0, recoveries = 0;
  @override
  Future<XFile?> pick(ImageSource source) async {
    picks++;
    return onPick?.call();
  }

  @override
  Future<XFile?> recover() async {
    recoveries++;
    return lost;
  }
}

class _FailingStore extends MemoryEstimateCaptureStore {
  @override
  Future<void> write(PendingEstimateCapture pending) async =>
      throw StateError('storage unavailable');
}

const _pending = PendingEstimateCapture(
  id: 'capture-1',
  customerId: 'customer-1',
  estimateId: 'estimate-1',
  captureKey: 'engine_bay',
);
void main() {
  test(
    'ownership and exact view are persisted before opening the camera',
    () async {
      final store = MemoryEstimateCaptureStore();
      final picker = _Picker()
        ..onPick = () async {
          expect(store.value?.customerId, 'customer-1');
          expect(store.value?.estimateId, 'estimate-1');
          expect(store.value?.captureKey, 'odometer');
          return XFile('/private/camera/photo.jpg');
        };
      final service = EstimateCaptureService(
        store: store,
        picker: picker,
        readBytes: (_) async => Uint8List.fromList([1, 2, 3]),
      );
      final uploads = <List<Object>>[];
      await service.capture(
        customerId: 'customer-1',
        estimateId: 'estimate-1',
        captureKey: 'odometer',
        source: ImageSource.camera,
        isCurrent: () => true,
        upload: (id, bytes, filename, key) async {
          uploads.add([id, bytes, filename, key]);
          return {'id': 'photo-1'};
        },
      );
      expect(uploads.single.first, 'estimate-1');
      expect(uploads.single.last, 'odometer');
      expect(store.value, isNull);
    },
  );
  test('storage failure prevents native capture and upload', () async {
    final picker = _Picker();
    final service = EstimateCaptureService(
      store: _FailingStore(),
      picker: picker,
    );
    await expectLater(
      service.capture(
        customerId: 'c',
        estimateId: 'e',
        captureKey: 'front',
        source: ImageSource.camera,
        isCurrent: () => true,
        upload: (_, _, _, _) async => throw StateError('must not upload'),
      ),
      throwsStateError,
    );
    expect(picker.picks, 0);
  });
  test(
    'cancelling the picker clears its pending view without uploading',
    () async {
      final store = MemoryEstimateCaptureStore();
      final service = EstimateCaptureService(store: store, picker: _Picker());
      final result = await service.capture(
        customerId: 'c',
        estimateId: 'e',
        captureKey: 'front',
        source: ImageSource.gallery,
        isCurrent: () => true,
        upload: (_, _, _, _) async => throw StateError('must not upload'),
      );
      expect(result, isNull);
      expect(store.value, isNull);
    },
  );
  test(
    'Android recovery cannot consume a different customer or estimate photo',
    () async {
      final store = MemoryEstimateCaptureStore()..value = _pending;
      final picker = _Picker()..lost = XFile('/private/recovered.jpg');
      final service = EstimateCaptureService(
        store: store,
        picker: picker,
        readBytes: (_) async => Uint8List.fromList([7]),
      );
      expect(
        await service.recover(
          customerId: 'customer-2',
          estimateId: 'estimate-1',
          isCurrent: () => true,
        ),
        isNull,
      );
      expect(
        await service.recover(
          customerId: 'customer-1',
          estimateId: 'estimate-2',
          isCurrent: () => true,
        ),
        isNull,
      );
      expect(picker.recoveries, 0);
      final recovered = await service.recover(
        customerId: 'customer-1',
        estimateId: 'estimate-1',
        isCurrent: () => true,
      );
      expect(picker.recoveries, 1);
      expect(recovered?.captureKey, 'engine_bay');
      expect(store.value?.localPath, '/private/recovered.jpg');
      await service.retry(
        pending: recovered!,
        isCurrent: () => true,
        upload: (id, _, _, key) async {
          expect(id, 'estimate-1');
          expect(key, 'engine_bay');
          return {'id': 'photo-2'};
        },
      );
      expect(store.value, isNull);
    },
  );
  test(
    'account change while camera is open preserves the original scope without uploading',
    () async {
      final camera = Completer<XFile?>();
      final picker = _Picker()..onPick = () => camera.future;
      final store = MemoryEstimateCaptureStore();
      bool current = true;
      final service = EstimateCaptureService(store: store, picker: picker);
      final work = service.capture(
        customerId: 'customer-1',
        estimateId: 'estimate-1',
        captureKey: 'front',
        source: ImageSource.camera,
        isCurrent: () => current,
        upload: (_, _, _, _) async => throw StateError('must not upload'),
      );
      await Future<void>.delayed(Duration.zero);
      current = false;
      final check = expectLater(work, throwsA(isA<PlusApiException>()));
      camera.complete(XFile('/private/original-owner.jpg'));
      await check;
      expect(store.value?.customerId, 'customer-1');
      expect(store.value?.captureKey, 'front');
      expect(store.value?.localPath, '/private/original-owner.jpg');
    },
  );
  test(
    'account change while reading bytes prevents upload with a new session',
    () async {
      final reading = Completer<void>();
      final bytes = Completer<Uint8List>();
      bool current = true;
      final service = EstimateCaptureService(
        store: MemoryEstimateCaptureStore(),
        picker: _Picker()..onPick = () async => XFile('/private/photo.jpg'),
        readBytes: (_) {
          reading.complete();
          return bytes.future;
        },
      );
      final work = service.capture(
        customerId: 'c1',
        estimateId: 'e1',
        captureKey: 'rear',
        source: ImageSource.gallery,
        isCurrent: () => current,
        upload: (_, _, _, _) async => throw StateError('must not upload'),
      );
      await reading.future;
      current = false;
      final check = expectLater(work, throwsA(isA<PlusApiException>()));
      bytes.complete(Uint8List.fromList([1]));
      await check;
    },
  );
  test(
    'uncertain upload retains the original file and capture key for retry',
    () async {
      final store = MemoryEstimateCaptureStore();
      final service = EstimateCaptureService(
        store: store,
        picker: _Picker()..onPick = () async => XFile('/private/panel.jpg'),
        readBytes: (_) async => Uint8List.fromList([1]),
      );
      final captures = <String>[];
      Future<Json> upload(
        String id,
        Uint8List bytes,
        String name,
        String key,
      ) async {
        captures.add('$id/$key');
        if (captures.length == 1) {
          throw const PlusApiException('Connection lost');
        }
        return {'id': 'p'};
      }

      await expectLater(
        service.capture(
          customerId: 'c',
          estimateId: 'e',
          captureKey: 'panel_hood',
          source: ImageSource.camera,
          isCurrent: () => true,
          upload: upload,
        ),
        throwsA(isA<PlusApiException>()),
      );
      expect(store.value?.localPath, '/private/panel.jpg');
      await service.retry(
        pending: store.value!,
        isCurrent: () => true,
        upload: upload,
      );
      expect(captures, ['e/panel_hood', 'e/panel_hood']);
      expect(store.value, isNull);
    },
  );
  test(
    'explicit discard drains another owner native result before a new scoped capture',
    () async {
      final store = MemoryEstimateCaptureStore()..value = _pending;
      final picker = _Picker()
        ..lost = XFile('/private/customer-1.jpg')
        ..onPick = () async => XFile('/private/customer-2.jpg');
      final service = EstimateCaptureService(
        store: store,
        picker: picker,
        readBytes: (path) async {
          expect(path, '/private/customer-2.jpg');
          return Uint8List.fromList([2]);
        },
      );
      await service.discardOther(
        customerId: 'customer-2',
        estimateId: 'estimate-2',
        isCurrent: () => true,
      );
      expect(picker.recoveries, 1);
      expect(store.value, isNull);
      await service.capture(
        customerId: 'customer-2',
        estimateId: 'estimate-2',
        captureKey: 'odometer',
        source: ImageSource.camera,
        isCurrent: () => true,
        upload: (id, bytes, filename, key) async {
          expect(id, 'estimate-2');
          expect(key, 'odometer');
          expect(bytes, [2]);
          return {'id': 'new-photo'};
        },
      );
    },
  );
}
