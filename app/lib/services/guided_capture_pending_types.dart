import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;

const maxGuidedCaptureBytes = 8 * 1024 * 1024;
const maxGuidedCaptureSerializedBytes = 12 * 1024 * 1024;

enum GuidedCapturePendingFailure { invalid, conflict, corrupt, storage }

/// Messages deliberately omit stored identities, filenames and platform errors.
class GuidedCapturePendingException implements Exception {
  const GuidedCapturePendingException(this.failure);
  final GuidedCapturePendingFailure failure;
  @override
  String toString() => switch (failure) {
    GuidedCapturePendingFailure.conflict =>
      'Finish or explicitly discard the pending photo before saving another.',
    GuidedCapturePendingFailure.invalid =>
      'This photo could not be saved for retry. Review the photo and try again.',
    GuidedCapturePendingFailure.corrupt =>
      'The pending photo could not be recovered. Review recovery options before continuing.',
    GuidedCapturePendingFailure.storage =>
      'The photo could not be saved on this device. Free some space and try again.',
  };
}

void validateGuidedCaptureOwner(String ownerId) {
  if (!RegExp(r'^[A-Za-z0-9][A-Za-z0-9:_-]{0,99}$').hasMatch(ownerId)) {
    throw const GuidedCapturePendingException(
      GuidedCapturePendingFailure.invalid,
    );
  }
}

void validateGuidedCaptureOperation(String operationId) {
  if (!RegExp(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
  ).hasMatch(operationId)) {
    throw const GuidedCapturePendingException(
      GuidedCapturePendingFailure.invalid,
    );
  }
}

String guidedCaptureStorageKey(String ownerId) {
  validateGuidedCaptureOwner(ownerId);
  return crypto.sha256.convert(utf8.encode(ownerId)).toString();
}

const _documentation = {
  'vin',
  'odometer',
  'engine_bay',
  'interior',
  'tire_tread',
  'front',
  'driver',
  'rear',
  'passenger',
  'corner_fl',
  'corner_fr',
  'corner_rl',
  'corner_rr',
  'roof',
};
const _panels = {
  'hood',
  'fender_left',
  'front_door_left',
  'rear_door_left',
  'quarter_left',
  'trunk',
  'quarter_right',
  'rear_door_right',
  'front_door_right',
  'fender_right',
  'roof',
  'front_bumper',
  'grille',
  'headlamps',
  'mirrors',
  'rear_bumper',
  'tail_lamps',
  'windshield',
};
const _hailPanels = {
  'hood',
  'fender_left',
  'front_door_left',
  'rear_door_left',
  'quarter_left',
  'trunk',
  'quarter_right',
  'rear_door_right',
  'front_door_right',
  'fender_right',
  'roof',
};

bool _knownKey(String key) =>
    _documentation.contains(key) ||
    (key.startsWith('panel_') && _panels.contains(key.substring(6))) ||
    (key.startsWith('hail_close_') &&
        _hailPanels.contains(key.substring(11))) ||
    (key.startsWith('hail_raking_') && _hailPanels.contains(key.substring(12)));

/// A detached immutable upload. No credentials, endpoint or recognized VIN are
/// stored; the bytes remain exactly those the customer selected.
class GuidedCapturePending {
  factory GuidedCapturePending({
    required String ownerId,
    required String estimateId,
    required String operationId,
    required String captureKey,
    required String bodyStyle,
    required String mimeType,
    required Uint8List bytes,
  }) {
    validateGuidedCaptureOwner(ownerId);
    validateGuidedCaptureOperation(operationId);
    if (!RegExp(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,35}$').hasMatch(estimateId) ||
        !_knownKey(captureKey) ||
        !const {
          'sedan',
          'coupe',
          'hatchback',
          'wagon',
          'suv',
          'pickup',
          'van',
          'convertible',
        }.contains(bodyStyle) ||
        !const {'image/jpeg', 'image/png', 'image/webp'}.contains(mimeType) ||
        bytes.isEmpty ||
        bytes.length > maxGuidedCaptureBytes) {
      throw const GuidedCapturePendingException(
        GuidedCapturePendingFailure.invalid,
      );
    }
    final copy = Uint8List.fromList(bytes).asUnmodifiableView();
    return GuidedCapturePending._(
      ownerId,
      estimateId,
      operationId,
      captureKey,
      bodyStyle,
      mimeType,
      copy,
      crypto.sha256.convert(copy).toString(),
    );
  }
  const GuidedCapturePending._(
    this.ownerId,
    this.estimateId,
    this.operationId,
    this.captureKey,
    this.bodyStyle,
    this.mimeType,
    this.bytes,
    this.sha256,
  );
  final String ownerId,
      estimateId,
      operationId,
      captureKey,
      bodyStyle,
      mimeType,
      sha256;
  final Uint8List bytes;
  bool samePayload(GuidedCapturePending other) =>
      ownerId == other.ownerId &&
      estimateId == other.estimateId &&
      operationId == other.operationId &&
      captureKey == other.captureKey &&
      bodyStyle == other.bodyStyle &&
      mimeType == other.mimeType &&
      sha256 == other.sha256 &&
      bytes.length == other.bytes.length;
}

class GuidedCapturePendingCodec {
  static String encode(GuidedCapturePending value) => jsonEncode({
    'version': 1,
    'owner_id': value.ownerId,
    'estimate_id': value.estimateId,
    'operation_id': value.operationId,
    'capture_key': value.captureKey,
    'body_style': value.bodyStyle,
    'mime_type': value.mimeType,
    'byte_size': value.bytes.length,
    'sha256': value.sha256,
    'bytes_base64': base64Encode(value.bytes),
  });
  static GuidedCapturePending decode(String raw, {required String ownerId}) {
    validateGuidedCaptureOwner(ownerId);
    try {
      if (raw.length > maxGuidedCaptureSerializedBytes ||
          utf8.encode(raw).length > maxGuidedCaptureSerializedBytes) {
        throw const FormatException();
      }
      final value = jsonDecode(raw);
      const fields = {
        'version',
        'owner_id',
        'estimate_id',
        'operation_id',
        'capture_key',
        'body_style',
        'mime_type',
        'byte_size',
        'sha256',
        'bytes_base64',
      };
      if (value is! Map<String, dynamic> ||
          value.length != fields.length ||
          !value.keys.every(fields.contains) ||
          value['version'] is! int ||
          value['version'] != 1 ||
          value['owner_id'] != ownerId ||
          value['byte_size'] is! int ||
          value['byte_size'] < 1 ||
          value['byte_size'] > maxGuidedCaptureBytes ||
          value['bytes_base64'] is! String ||
          (value['bytes_base64'] as String).length !=
              ((value['byte_size'] as int) + 2) ~/ 3 * 4) {
        throw const FormatException();
      }
      final data = base64Decode(value['bytes_base64'] as String);
      final record = GuidedCapturePending(
        ownerId: ownerId,
        estimateId: value['estimate_id'] as String,
        operationId: value['operation_id'] as String,
        captureKey: value['capture_key'] as String,
        bodyStyle: value['body_style'] as String,
        mimeType: value['mime_type'] as String,
        bytes: data,
      );
      if (data.length != value['byte_size'] ||
          record.sha256 != value['sha256']) {
        throw const FormatException();
      }
      return record;
    } catch (_) {
      throw const GuidedCapturePendingException(
        GuidedCapturePendingFailure.corrupt,
      );
    }
  }
}

abstract class GuidedCapturePendingStore {
  Future<GuidedCapturePending?> read(String ownerId);
  Future<void> write(GuidedCapturePending record);

  /// Call only after acknowledging this exact upload, or an explicit discard.
  Future<bool> clear(String ownerId, String operationId);

  /// The host must first obtain explicit consent to discard unrecoverable data.
  /// Never removes a valid record. Only the supplied owner's key is considered.
  Future<bool> discardCorrupt(String ownerId);
}

class MemoryGuidedCapturePendingStore implements GuidedCapturePendingStore {
  MemoryGuidedCapturePendingStore({Map<String, String>? backing})
    : _values = backing ?? {};
  final Map<String, String> _values;
  @override
  Future<GuidedCapturePending?> read(String ownerId) async {
    validateGuidedCaptureOwner(ownerId);
    final raw = _values[ownerId];
    return raw == null
        ? null
        : GuidedCapturePendingCodec.decode(raw, ownerId: ownerId);
  }

  @override
  Future<void> write(GuidedCapturePending record) async {
    final raw = _values[record.ownerId];
    if (raw != null) {
      final previous = GuidedCapturePendingCodec.decode(
        raw,
        ownerId: record.ownerId,
      );
      if (!previous.samePayload(record)) {
        throw const GuidedCapturePendingException(
          GuidedCapturePendingFailure.conflict,
        );
      }
      return;
    }
    _values[record.ownerId] = GuidedCapturePendingCodec.encode(record);
  }

  @override
  Future<bool> clear(String ownerId, String operationId) async {
    validateGuidedCaptureOwner(ownerId);
    validateGuidedCaptureOperation(operationId);
    final raw = _values[ownerId];
    if (raw == null ||
        GuidedCapturePendingCodec.decode(raw, ownerId: ownerId).operationId !=
            operationId) {
      return false;
    }
    _values.remove(ownerId);
    return true;
  }

  @override
  Future<bool> discardCorrupt(String ownerId) async {
    validateGuidedCaptureOwner(ownerId);
    final raw = _values[ownerId];
    if (raw == null) return false;
    try {
      GuidedCapturePendingCodec.decode(raw, ownerId: ownerId);
    } on GuidedCapturePendingException catch (e) {
      if (e.failure != GuidedCapturePendingFailure.corrupt) rethrow;
      _values.remove(ownerId);
      return true;
    }
    return false;
  }
}
