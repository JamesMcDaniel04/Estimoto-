import 'dart:async';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'guided_capture_pending_types.dart';

GuidedCapturePendingStore createStore() => NativeGuidedCapturePendingStore();

/// Atomic, flushed app-support files. Owner hashes are filenames; no tokens or
/// raw account IDs are placed in paths. Native callers use the main app isolate.
class NativeGuidedCapturePendingStore implements GuidedCapturePendingStore {
  NativeGuidedCapturePendingStore({
    Future<Directory> Function()? supportDirectory,
  }) : _supportDirectory = supportDirectory ?? getApplicationSupportDirectory;
  final Future<Directory> Function() _supportDirectory;
  // File locks coordinate processes. This queue also coordinates multiple
  // instances in the main isolate, where OS locks may be process-scoped.
  static final _tails = <String, Future<void>>{};

  Future<T> _locked<T>(
    String ownerId,
    Future<T> Function(File, File) action,
  ) async {
    final key = guidedCaptureStorageKey(ownerId);
    try {
      final support = await _supportDirectory();
      final directory = Directory('${support.path}/guided_capture_pending_v1');
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
    } on GuidedCapturePendingException {
      rethrow;
    } catch (_) {
      throw const GuidedCapturePendingException(
        GuidedCapturePendingFailure.storage,
      );
    }
  }

  Future<GuidedCapturePending?> _decode(File file, String ownerId) async {
    if (!await file.exists()) return null;
    if (await file.length() > maxGuidedCaptureSerializedBytes) {
      throw const GuidedCapturePendingException(
        GuidedCapturePendingFailure.corrupt,
      );
    }
    try {
      return GuidedCapturePendingCodec.decode(
        await file.readAsString(),
        ownerId: ownerId,
      );
    } on FormatException {
      throw const GuidedCapturePendingException(
        GuidedCapturePendingFailure.corrupt,
      );
    }
  }

  Future<GuidedCapturePending?> _current(
    File file,
    File staging,
    String ownerId,
  ) async {
    final stored = await _decode(file, ownerId);
    final staged = await _decode(staging, ownerId);
    if (staged != null) {
      if (stored != null && !stored.samePayload(staged)) {
        throw const GuidedCapturePendingException(
          GuidedCapturePendingFailure.corrupt,
        );
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
  Future<GuidedCapturePending?> read(String ownerId) =>
      _locked(ownerId, (file, staging) => _current(file, staging, ownerId));

  @override
  Future<void> write(GuidedCapturePending record) =>
      _locked(record.ownerId, (file, staging) async {
        final current = await _current(file, staging, record.ownerId);
        if (current != null) {
          if (!current.samePayload(record)) {
            throw const GuidedCapturePendingException(
              GuidedCapturePendingFailure.conflict,
            );
          }
          return;
        }
        // Do not remove either object after an uncertain write/rename. Recovery
        // validates its complete digest before admitting another operation.
        await staging.writeAsString(
          GuidedCapturePendingCodec.encode(record),
          flush: true,
        );
        await staging.rename(file.path);
      });

  @override
  Future<bool> clear(String ownerId, String operationId) {
    validateGuidedCaptureOperation(operationId);
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
    } on GuidedCapturePendingException catch (e) {
      if (e.failure != GuidedCapturePendingFailure.corrupt) rethrow;
      // Never discard a valid canonical record, even if a staging artifact is
      // corrupt. The host can still recover this situation through support.
      try {
        if (await _decode(file, ownerId) != null) return false;
      } on GuidedCapturePendingException catch (error) {
        if (error.failure != GuidedCapturePendingFailure.corrupt) rethrow;
      }
      if (await file.exists()) await file.delete();
      if (await staging.exists()) await staging.delete();
      return true;
    }
    return false;
  });
}
