import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;

const maxReceiptBytes = 10 * 1024 * 1024;
const maxReceiptSerializedBytes = 15 * 1024 * 1024;

enum ReceiptPendingFailure { invalid, conflict, corrupt, storage }

/// Messages deliberately omit stored identities, filenames and platform errors.
class ReceiptPendingException implements Exception {
  const ReceiptPendingException(this.failure);
  final ReceiptPendingFailure failure;
  @override
  String toString() => switch (failure) {
    ReceiptPendingFailure.conflict =>
      'Finish or explicitly discard the pending receipt before saving another.',
    ReceiptPendingFailure.invalid =>
      'This receipt could not be saved for retry. Review the receipt and try again.',
    ReceiptPendingFailure.corrupt =>
      'The pending receipt could not be recovered. Review recovery options before continuing.',
    ReceiptPendingFailure.storage =>
      'The receipt could not be saved on this device. Free some space and try again.',
  };
}

void validateReceiptOwner(String ownerId) {
  if (!RegExp(r'^[A-Za-z0-9][A-Za-z0-9:_-]{0,99}$').hasMatch(ownerId)) {
    throw const ReceiptPendingException(ReceiptPendingFailure.invalid);
  }
}

void validateReceiptOperation(String operationId) {
  if (!RegExp(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
  ).hasMatch(operationId)) {
    throw const ReceiptPendingException(ReceiptPendingFailure.invalid);
  }
}

String receiptStorageKey(String ownerId) {
  validateReceiptOwner(ownerId);
  return crypto.sha256.convert(utf8.encode(ownerId)).toString();
}

/// A detached immutable upload. No credentials or endpoint are
/// stored; the bytes remain exactly those the customer selected.
class ReceiptPending {
  factory ReceiptPending({
    required String ownerId,
    required String recordId,
    required String operationId,
    required String filename,
    required String mimeType,
    required Uint8List bytes,
  }) {
    validateReceiptOwner(ownerId);
    validateReceiptOperation(operationId);
    if (!RegExp(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,35}$').hasMatch(recordId) ||
        filename.isEmpty ||
        filename.length > 200 ||
        RegExp(r'[\x00-\x1f\x7f/\\]').hasMatch(filename) ||
        !const {
          'image/jpeg',
          'image/png',
          'image/webp',
          'application/pdf',
        }.contains(mimeType) ||
        bytes.isEmpty ||
        bytes.length > maxReceiptBytes) {
      throw const ReceiptPendingException(ReceiptPendingFailure.invalid);
    }
    final copy = Uint8List.fromList(bytes).asUnmodifiableView();
    return ReceiptPending._(
      ownerId,
      recordId,
      operationId,
      filename,
      mimeType,
      copy,
      crypto.sha256.convert(copy).toString(),
    );
  }
  const ReceiptPending._(
    this.ownerId,
    this.recordId,
    this.operationId,
    this.filename,
    this.mimeType,
    this.bytes,
    this.sha256,
  );
  final String ownerId, recordId, operationId, filename, mimeType, sha256;
  final Uint8List bytes;
  bool samePayload(ReceiptPending other) =>
      ownerId == other.ownerId &&
      recordId == other.recordId &&
      operationId == other.operationId &&
      filename == other.filename &&
      mimeType == other.mimeType &&
      sha256 == other.sha256 &&
      bytes.length == other.bytes.length;
}

class ReceiptPendingCodec {
  static String encode(ReceiptPending value) => jsonEncode({
    'version': 1,
    'owner_id': value.ownerId,
    'record_id': value.recordId,
    'operation_id': value.operationId,
    'filename': value.filename,
    'mime_type': value.mimeType,
    'byte_size': value.bytes.length,
    'sha256': value.sha256,
    'bytes_base64': base64Encode(value.bytes),
  });
  static ReceiptPending decode(String raw, {required String ownerId}) {
    validateReceiptOwner(ownerId);
    try {
      if (raw.length > maxReceiptSerializedBytes ||
          utf8.encode(raw).length > maxReceiptSerializedBytes) {
        throw const FormatException();
      }
      final value = jsonDecode(raw);
      const fields = {
        'version',
        'owner_id',
        'record_id',
        'operation_id',
        'filename',
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
          value['byte_size'] > maxReceiptBytes ||
          value['bytes_base64'] is! String ||
          (value['bytes_base64'] as String).length !=
              ((value['byte_size'] as int) + 2) ~/ 3 * 4) {
        throw const FormatException();
      }
      final data = base64Decode(value['bytes_base64'] as String);
      final record = ReceiptPending(
        ownerId: ownerId,
        recordId: value['record_id'] as String,
        operationId: value['operation_id'] as String,
        filename: value['filename'] as String,
        mimeType: value['mime_type'] as String,
        bytes: data,
      );
      if (data.length != value['byte_size'] ||
          record.sha256 != value['sha256']) {
        throw const FormatException();
      }
      return record;
    } catch (_) {
      throw const ReceiptPendingException(ReceiptPendingFailure.corrupt);
    }
  }
}

abstract class ReceiptPendingStore {
  Future<ReceiptPending?> read(String ownerId);
  Future<void> write(ReceiptPending record);

  /// Call only after acknowledging this exact upload, or an explicit discard.
  Future<bool> clear(String ownerId, String operationId);

  /// The host must first obtain explicit consent to discard unrecoverable data.
  /// Never removes a valid record. Only the supplied owner's key is considered.
  Future<bool> discardCorrupt(String ownerId);
}

class MemoryReceiptPendingStore implements ReceiptPendingStore {
  MemoryReceiptPendingStore({Map<String, String>? backing})
    : _values = backing ?? {};
  final Map<String, String> _values;
  @override
  Future<ReceiptPending?> read(String ownerId) async {
    validateReceiptOwner(ownerId);
    final raw = _values[ownerId];
    return raw == null
        ? null
        : ReceiptPendingCodec.decode(raw, ownerId: ownerId);
  }

  @override
  Future<void> write(ReceiptPending record) async {
    final raw = _values[record.ownerId];
    if (raw != null) {
      final previous = ReceiptPendingCodec.decode(raw, ownerId: record.ownerId);
      if (!previous.samePayload(record)) {
        throw const ReceiptPendingException(ReceiptPendingFailure.conflict);
      }
      return;
    }
    _values[record.ownerId] = ReceiptPendingCodec.encode(record);
  }

  @override
  Future<bool> clear(String ownerId, String operationId) async {
    validateReceiptOwner(ownerId);
    validateReceiptOperation(operationId);
    final raw = _values[ownerId];
    if (raw == null ||
        ReceiptPendingCodec.decode(raw, ownerId: ownerId).operationId !=
            operationId) {
      return false;
    }
    _values.remove(ownerId);
    return true;
  }

  @override
  Future<bool> discardCorrupt(String ownerId) async {
    validateReceiptOwner(ownerId);
    final raw = _values[ownerId];
    if (raw == null) return false;
    try {
      ReceiptPendingCodec.decode(raw, ownerId: ownerId);
    } on ReceiptPendingException catch (e) {
      if (e.failure != ReceiptPendingFailure.corrupt) rethrow;
      _values.remove(ownerId);
      return true;
    }
    return false;
  }
}
