import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb;
import 'package:flutter/services.dart' show PlatformException;
import 'package:image_picker/image_picker.dart';

import '../data/repository.dart';
import '../domain/models.dart';

class PendingEstimateCapture {
  const PendingEstimateCapture({
    required this.id,
    required this.customerId,
    required this.estimateId,
    required this.captureKey,
    this.targetKind = 'estimate',
    this.localPath,
  });

  factory PendingEstimateCapture.fromJson(Json data) => PendingEstimateCapture(
    id: data['id'] as String,
    customerId: data['customer_id'] as String,
    estimateId: data['estimate_id'] as String,
    captureKey: data['capture_key'] as String,
    targetKind: switch (data['target_kind']) {
      null || 'estimate' => 'estimate',
      'vehicle' => 'vehicle',
      _ => throw const FormatException('Unknown photo destination'),
    },
    localPath: data['local_path'] as String?,
  );

  final String id, customerId, estimateId, captureKey, targetKind;
  final String? localPath;
  PendingEstimateCapture withFile(XFile file) => PendingEstimateCapture(
    id: id,
    customerId: customerId,
    estimateId: estimateId,
    captureKey: captureKey,
    targetKind: targetKind,
    localPath: file.path,
  );
  Json toJson() => {
    'id': id,
    'customer_id': customerId,
    'estimate_id': estimateId,
    'capture_key': captureKey,
    if (targetKind != 'estimate') 'target_kind': targetKind,
    if (localPath != null) 'local_path': localPath,
  };
}

abstract class EstimateCaptureStore {
  Future<PendingEstimateCapture?> read();
  Future<void> write(PendingEstimateCapture pending);
  Future<void> clear(String captureId);
}

class MemoryEstimateCaptureStore implements EstimateCaptureStore {
  PendingEstimateCapture? value;
  @override
  Future<PendingEstimateCapture?> read() async => value;
  @override
  Future<void> write(PendingEstimateCapture pending) async => value = pending;
  @override
  Future<void> clear(String captureId) async {
    if (value?.id == captureId) value = null;
  }
}

class SecureEstimateCaptureStore implements EstimateCaptureStore {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  static const _key = 'estimoto_plus_pending_photo_v1';
  @override
  Future<PendingEstimateCapture?> read() async {
    final value = await _storage.read(key: _key);
    return value == null
        ? null
        : PendingEstimateCapture.fromJson(jsonDecode(value) as Json);
  }

  @override
  Future<void> write(PendingEstimateCapture pending) =>
      _storage.write(key: _key, value: jsonEncode(pending.toJson()));

  @override
  Future<void> clear(String captureId) async {
    if ((await read())?.id == captureId) await _storage.delete(key: _key);
  }
}

Future<PendingEstimateCapture?> pendingEstimateCaptureFor(
  String customerId,
) async {
  final pending = await SecureEstimateCaptureStore().read();
  return pending?.customerId == customerId ? pending : null;
}

abstract class EstimatePhotoPicker {
  Future<XFile?> pick(ImageSource source);
  Future<XFile?> recover();
}

class NativeEstimatePhotoPicker implements EstimatePhotoPicker {
  final _picker = ImagePicker();
  @override
  Future<XFile?> pick(ImageSource source) async {
    try {
      return await _picker.pickImage(
        source: source,
        maxWidth: 2560,
        maxHeight: 2560,
        imageQuality: 90,
        requestFullMetadata: false,
      );
    } on PlatformException catch (error) {
      if (error.code.contains('access_denied') ||
          error.code.contains('access_restricted')) {
        throw PlusApiException(
          source == ImageSource.camera
              ? 'Allow camera access in your phone settings, or choose an existing photo.'
              : 'Allow photo-library access in your phone settings, or take a photo with the camera.',
        );
      }
      rethrow;
    }
  }

  @override
  Future<XFile?> recover() async {
    // Only Android can recreate the app while its external picker is open.
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return null;
    final response = await _picker.retrieveLostData();
    if (response.exception != null) throw response.exception!;
    final files = response.files ?? [];
    if (files.length > 1) {
      throw const PlusApiException(
        'The camera returned more than one photo. Retake this view to keep it with the correct estimate.',
      );
    }
    return files.firstOrNull;
  }
}

typedef UploadEstimatePhoto =
    Future<Json> Function(
      String estimateId,
      Uint8List bytes,
      String filename,
      String captureKey,
    );

/// Native picker recovery has one device-wide slot. Persist its exact owner,
/// estimate and view BEFORE leaving Flutter; never infer them after restart.
class EstimateCaptureService {
  EstimateCaptureService({
    EstimateCaptureStore? store,
    EstimatePhotoPicker? picker,
    Future<Uint8List> Function(String path)? readBytes,
  }) : store = store ?? SecureEstimateCaptureStore(),
       picker = picker ?? NativeEstimatePhotoPicker(),
       readBytes = readBytes ?? ((path) => XFile(path).readAsBytes());
  final EstimateCaptureStore store;
  final EstimatePhotoPicker picker;
  final Future<Uint8List> Function(String path) readBytes;
  static bool _active = false;

  Future<T> _exclusive<T>(Future<T> Function() work) async {
    if (_active) {
      throw const PlusApiException(
        'Finish the current photo before starting another.',
      );
    }
    _active = true;
    try {
      return await work();
    } finally {
      _active = false;
    }
  }

  void _requireCurrent(bool Function() isCurrent) {
    if (!isCurrent()) {
      throw const PlusApiException(
        'Your sign-in changed. Reopen this estimate to continue.',
      );
    }
  }

  Future<Json?> capture({
    required String customerId,
    required String estimateId,
    required String captureKey,
    required ImageSource source,
    required bool Function() isCurrent,
    required UploadEstimatePhoto upload,
    String targetKind = 'estimate',
  }) => _exclusive(() async {
    _requireCurrent(isCurrent);
    if (await store.read() != null) {
      throw const PlusApiException(
        'Finish or retake the saved photo before starting another.',
      );
    }
    _requireCurrent(isCurrent);
    final pending = PendingEstimateCapture(
      id: DateTime.now().microsecondsSinceEpoch.toString(),
      customerId: customerId,
      estimateId: estimateId,
      captureKey: captureKey,
      targetKind: targetKind,
    );
    await store.write(pending);
    _requireCurrent(isCurrent);
    final file = await picker.pick(source);
    if (file == null) {
      await store.clear(pending.id);
      return null;
    }
    final ready = pending.withFile(file);
    await store.write(ready);
    return _upload(ready, isCurrent, upload);
  });

  /// Recovery only makes the original photo available for an explicit retry.
  /// A different account/estimate must not consume Android's lost-data slot.
  Future<PendingEstimateCapture?> recover({
    required String customerId,
    required String estimateId,
    required bool Function() isCurrent,
    String targetKind = 'estimate',
  }) => _exclusive(() async {
    _requireCurrent(isCurrent);
    final pending = await store.read();
    if (pending == null ||
        pending.customerId != customerId ||
        pending.estimateId != estimateId ||
        pending.targetKind != targetKind) {
      return null;
    }
    _requireCurrent(isCurrent);
    if (pending.localPath != null) return pending;
    final file = await picker.recover();
    if (file == null) {
      await store.clear(pending.id);
      return null;
    }
    final ready = pending.withFile(file);
    await store.write(ready);
    _requireCurrent(isCurrent);
    return ready;
  });

  Future<Json> retry({
    required PendingEstimateCapture pending,
    required bool Function() isCurrent,
    String targetKind = 'estimate',
    required UploadEstimatePhoto upload,
  }) => _exclusive(() async {
    _requireCurrent(isCurrent);
    final saved = await store.read();
    if (saved?.id != pending.id ||
        saved?.localPath == null ||
        saved?.targetKind != targetKind ||
        pending.targetKind != targetKind) {
      throw const PlusApiException(
        'This photo is no longer available. Retake this view.',
      );
    }
    return _upload(saved!, isCurrent, upload);
  });

  Future<Json> _upload(
    PendingEstimateCapture pending,
    bool Function() isCurrent,
    UploadEstimatePhoto upload,
  ) async {
    _requireCurrent(isCurrent);
    final file = XFile(pending.localPath!);
    final bytes = await readBytes(file.path);
    _requireCurrent(isCurrent);
    final result = await upload(
      pending.estimateId,
      bytes,
      file.name,
      pending.captureKey,
    );
    await store.clear(pending.id);
    _requireCurrent(isCurrent);
    return result;
  }

  Future<void> discard(
    PendingEstimateCapture pending,
    bool Function() isCurrent,
  ) => _exclusive(() async {
    _requireCurrent(isCurrent);
    await store.clear(pending.id);
  });

  /// Explicitly abandon an unfinished device operation without exposing its
  /// previous account, estimate, view or bytes. Drain the old native result
  /// before allowing a new operation to claim Android's single recovery slot.
  Future<void> discardOther({
    required String customerId,
    required String estimateId,
    required bool Function() isCurrent,
    String targetKind = 'estimate',
  }) => _exclusive(() async {
    _requireCurrent(isCurrent);
    final saved = await store.read();
    if (saved == null) return;
    if (saved.customerId == customerId &&
        saved.estimateId == estimateId &&
        saved.targetKind == targetKind) {
      throw const PlusApiException(
        'Finish or retake the saved photo for this estimate.',
      );
    }
    _requireCurrent(isCurrent);
    if (saved.localPath == null) await picker.recover();
    _requireCurrent(isCurrent);
    await store.clear(saved.id);
  });
}
