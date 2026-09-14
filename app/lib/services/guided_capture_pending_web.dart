import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

import 'guided_capture_pending_types.dart';

GuidedCapturePendingStore createStore() => IndexedDbGuidedCapturePendingStore();

/// Transactional IndexedDB in the app origin, never the capture page's storage.
/// A read/compare/write transaction also protects against another app tab.
class IndexedDbGuidedCapturePendingStore implements GuidedCapturePendingStore {
  Future<web.IDBDatabase>? _database;
  Future<web.IDBDatabase> _open() async {
    if (_database != null) return _database!;
    final completion = Completer<web.IDBDatabase>();
    _database = completion.future;
    try {
      final request = web.window.indexedDB.open(
        'estimoto_plus_guided_capture_v1',
        1,
      );
      request.onupgradeneeded = ((web.Event _) {
        final db = request.result as web.IDBDatabase;
        if (!db.objectStoreNames.contains('captures')) {
          db.createObjectStore('captures');
        }
      }).toJS;
      request.onsuccess = ((web.Event _) {
        final db = request.result as web.IDBDatabase;
        if (completion.isCompleted) {
          db.close();
          return;
        }
        db.onversionchange = ((web.Event _) {
          db.close();
          _database = null;
        }).toJS;
        completion.complete(db);
      }).toJS;
      void fail(web.Event _) {
        if (!completion.isCompleted) {
          completion.completeError(
            const GuidedCapturePendingException(
              GuidedCapturePendingFailure.storage,
            ),
          );
        }
      }

      request.onerror = fail.toJS;
      request.onblocked = fail.toJS;
      return await completion.future;
    } catch (_) {
      _database = null;
      throw const GuidedCapturePendingException(
        GuidedCapturePendingFailure.storage,
      );
    }
  }

  Future<T> _transaction<T>(
    String ownerId,
    String mode,
    T Function(web.IDBObjectStore, String?, String) action, {
    bool discardWrongType = false,
  }) async {
    final key = guidedCaptureStorageKey(ownerId);
    try {
      final db = await _open();
      final done = Completer<T>();
      final transaction = db.transaction(
        'captures'.toJS,
        mode,
        web.IDBTransactionOptions(durability: 'strict'),
      );
      final store = transaction.objectStore('captures');
      T? result;
      Object? failure;
      var completedRead = false;
      transaction.oncomplete = ((web.Event _) {
        if (!done.isCompleted) {
          if (completedRead) {
            done.complete(result as T);
          } else {
            done.completeError(
              const GuidedCapturePendingException(
                GuidedCapturePendingFailure.storage,
              ),
            );
          }
        }
      }).toJS;
      void failed(web.Event _) {
        if (!done.isCompleted) {
          done.completeError(
            failure ??
                const GuidedCapturePendingException(
                  GuidedCapturePendingFailure.storage,
                ),
          );
        }
      }

      transaction.onabort = failed.toJS;
      transaction.onerror = failed.toJS;
      void abort(Object error) {
        failure = error is GuidedCapturePendingException
            ? error
            : const GuidedCapturePendingException(
                GuidedCapturePendingFailure.storage,
              );
        transaction.abort();
      }

      void accept(JSAny? value, {required bool present}) {
        try {
          if (present && (value == null || !value.isA<JSString>())) {
            if (!discardWrongType) {
              throw const GuidedCapturePendingException(
                GuidedCapturePendingFailure.corrupt,
              );
            }
            // Only explicit current-owner recovery may remove this malformed
            // value. Normal reads, writes and compare-clear still reject it.
            store.delete(key.toJS);
            result = true as T;
          } else {
            result = action(
              store,
              present ? (value as JSString).toDart : null,
              key,
            );
          }
          completedRead = true;
        } catch (error) {
          abort(error);
        }
      }

      final request = store.get(key.toJS);
      request.onsuccess = ((web.Event _) {
        try {
          final value = request.result;
          if (value == null) {
            // IndexedDB returns undefined both for a missing key and for a
            // stored undefined/null value. Check key existence within this
            // same transaction so corrupt nulls cannot masquerade as absence.
            final existence = store.getKey(key.toJS);
            existence.onsuccess = ((web.Event _) {
              accept(value, present: existence.result != null);
            }).toJS;
          } else {
            accept(value, present: true);
          }
        } catch (error) {
          abort(error);
        }
      }).toJS;
      // Success is reported only by transaction completion, never request.put.
      return await done.future;
    } on GuidedCapturePendingException {
      rethrow;
    } catch (_) {
      _database = null;
      throw const GuidedCapturePendingException(
        GuidedCapturePendingFailure.storage,
      );
    }
  }

  @override
  Future<GuidedCapturePending?> read(String ownerId) => _transaction(
    ownerId,
    'readonly',
    (_, raw, _) => raw == null
        ? null
        : GuidedCapturePendingCodec.decode(raw, ownerId: ownerId),
  );

  @override
  Future<void> write(GuidedCapturePending record) async {
    await _transaction<bool>(record.ownerId, 'readwrite', (store, raw, key) {
      if (raw != null) {
        if (!GuidedCapturePendingCodec.decode(
          raw,
          ownerId: record.ownerId,
        ).samePayload(record)) {
          throw const GuidedCapturePendingException(
            GuidedCapturePendingFailure.conflict,
          );
        }
      } else {
        store.add(GuidedCapturePendingCodec.encode(record).toJS, key.toJS);
      }
      return true;
    });
  }

  @override
  Future<bool> clear(String ownerId, String operationId) {
    validateGuidedCaptureOperation(operationId);
    return _transaction(ownerId, 'readwrite', (store, raw, key) {
      if (raw == null ||
          GuidedCapturePendingCodec.decode(raw, ownerId: ownerId).operationId !=
              operationId) {
        return false;
      }
      store.delete(key.toJS);
      return true;
    });
  }

  @override
  Future<bool> discardCorrupt(String ownerId) =>
      _transaction(ownerId, 'readwrite', (store, raw, key) {
        if (raw == null) return false;
        try {
          GuidedCapturePendingCodec.decode(raw, ownerId: ownerId);
        } on GuidedCapturePendingException catch (e) {
          if (e.failure != GuidedCapturePendingFailure.corrupt) rethrow;
          store.delete(key.toJS);
          return true;
        }
        return false;
      }, discardWrongType: true);
}
