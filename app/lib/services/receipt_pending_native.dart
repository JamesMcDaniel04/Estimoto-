import 'dart:async';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'receipt_pending_types.dart';

ReceiptPendingStore createStore() => NativeReceiptPendingStore();

/// Atomic, flushed app-support files. Owner hashes are filenames; no tokens or
/// raw account IDs are placed in paths. Native callers use the main app isolate.
class NativeReceiptPendingStore implements ReceiptPendingStore {
  NativeReceiptPendingStore({Future<Directory> Function()? supportDirectory})
    : _supportDirectory = supportDirectory ?? getApplicationSupportDirectory;
  final Future<Directory> Function() _supportDirectory;
  // File locks coordinate processes. This queue also coordinates multiple
  // instances in the main isolate, where OS locks may be process-scoped.
  static final _tails = <String, Future<void>>{};

  Future<T> _locked<T>(
    String ownerId,
    Future<T> Function(File, File) action,
  ) async {
    final key = receiptStorageKey(ownerId);
    try {
      final support = await _supportDirectory();
      final directory = Directory('${support.path}/receipt_pending_v1');
      await directory.create(recursive: true);
      final file = File('${directory.path}/$key.json');
      final staging = File('${file.path}.tmp');
      final previous = _tails[file.path] ?? Future<void>.value();
      final release = Completer<void>();
      _tails[file.path] = release.future;
      await previous;
      try {
        final lock = await File(
          '${file.path}.lock',
        ).open(mode: FileMode.append);
        try {
          await lock.lock(FileLock.blockingExclusive);
          return await action(file, staging);
        } finally {
          await lock.close();
        }
      } finally {
        release.complete();
        if (identical(_tails[file.path], release.future)) {
          _tails.remove(file.path);
        }
      }
    } on ReceiptPendingException {
      rethrow;
    } catch (_) {
      throw const ReceiptPendingException(ReceiptPendingFailure.storage);
    }
  }

  Future<ReceiptPending?> _decode(File file, String ownerId) async {
    if (!await file.exists()) return null;
    if (await file.length() > maxReceiptSerializedBytes) {
      throw const ReceiptPendingException(ReceiptPendingFailure.corrupt);
    }
    try {
      return ReceiptPendingCodec.decode(
        await file.readAsString(),
        ownerId: ownerId,
      );
    } on FormatException {
      throw const ReceiptPendingException(ReceiptPendingFailure.corrupt);
    }
  }

  Future<ReceiptPending?> _current(
    File file,
    File staging,
    String ownerId,
  ) async {
    final stored = await _decode(file, ownerId);
    final staged = await _decode(staging, ownerId);
    if (staged != null) {
      if (stored != null && !stored.samePayload(staged)) {
        throw const ReceiptPendingException(ReceiptPendingFailure.corrupt);
      }
      if (stored == null) {
        // The process ended after flush but before rename/return. Preserve its
        // immutable operation for explicit recovery, never automatic upload.
        await staging.rename(file.path);
        return staged;
      }
      await staging.delete();
    }
    return stored;
  }

  @override
  Future<ReceiptPending?> read(String ownerId) =>
      _locked(ownerId, (file, staging) => _current(file, staging, ownerId));

  @override
  Future<void> write(ReceiptPending record) =>
      _locked(record.ownerId, (file, staging) async {
        final current = await _current(file, staging, record.ownerId);
        if (current != null) {
          if (!current.samePayload(record)) {
            throw const ReceiptPendingException(ReceiptPendingFailure.conflict);
          }
          return;
        }
        // Do not remove either object after an uncertain write/rename. Recovery
        // validates its complete digest before admitting another operation.
        await staging.writeAsString(
          ReceiptPendingCodec.encode(record),
          flush: true,
        );
        await staging.rename(file.path);
      });

  @override
  Future<bool> clear(String ownerId, String operationId) {
    validateReceiptOperation(operationId);
    return _locked(ownerId, (file, staging) async {
      final current = await _current(file, staging, ownerId);
      if (current == null || current.operationId != operationId) return false;
      await file.delete();
      return true;
    });
  }

  @override
  Future<bool> discardCorrupt(String ownerId) => _locked(ownerId, (
    file,
    staging,
  ) async {
    try {
      await _current(file, staging, ownerId);
    } on ReceiptPendingException catch (e) {
      if (e.failure != ReceiptPendingFailure.corrupt) rethrow;
      // Never discard a valid canonical record, even if a staging artifact is
      // corrupt. The host can still recover this situation through support.
      try {
        if (await _decode(file, ownerId) != null) return false;
      } on ReceiptPendingException catch (error) {
        if (error.failure != ReceiptPendingFailure.corrupt) rethrow;
      }
      if (await file.exists()) await file.delete();
      if (await staging.exists()) await staging.delete();
      return true;
    }
    return false;
  });
}
