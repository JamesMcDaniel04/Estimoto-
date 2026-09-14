import 'dart:convert';
import 'dart:math';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../data/repository.dart';
import '../data/pending_request_store.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';

class PendingWorkspaceWrite {
  PendingWorkspaceWrite({
    required Json body,
    required this.key,
    this.reviewTimeZone,
  }) : body = freezeJson(body);
  final Json body;
  final String key;
  final String? reviewTimeZone;
  Json toJson() => {
    'body': body,
    'key': key,
    if (reviewTimeZone != null) 'review_time_zone': reviewTimeZone,
  };
  factory PendingWorkspaceWrite.fromJson(Json json) => PendingWorkspaceWrite(
    body: Map<String, dynamic>.from(json['body'] as Map),
    key: json['key'] as String,
    reviewTimeZone: json['review_time_zone'] as String?,
  );
}

abstract class WorkspaceWriteStore {
  Future<PendingWorkspaceWrite?> read(String scope);
  Future<void> write(String scope, PendingWorkspaceWrite value);
  Future<void> clear(String scope);
}

class MemoryWorkspaceWriteStore implements WorkspaceWriteStore {
  final _values = <String, String>{};
  @override
  Future<PendingWorkspaceWrite?> read(String scope) async =>
      _values[scope] == null
      ? null
      : PendingWorkspaceWrite.fromJson(jsonDecode(_values[scope]!) as Json);
  @override
  Future<void> write(String scope, PendingWorkspaceWrite value) async {
    _values[scope] = jsonEncode(value.toJson());
  }

  @override
  Future<void> clear(String scope) async {
    _values.remove(scope);
  }
}

class SecureWorkspaceWriteStore implements WorkspaceWriteStore {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  String _key(String scope) =>
      'plus_workspace_${base64Url.encode(utf8.encode(scope))}';
  @override
  Future<PendingWorkspaceWrite?> read(String scope) async {
    final value = await _storage.read(key: _key(scope));
    return value == null
        ? null
        : PendingWorkspaceWrite.fromJson(jsonDecode(value) as Json);
  }

  @override
  Future<void> write(String scope, PendingWorkspaceWrite value) =>
      _storage.write(key: _key(scope), value: jsonEncode(value.toJson()));
  @override
  Future<void> clear(String scope) => _storage.delete(key: _key(scope));
}

/// A retry uses the original account, body and UUID, including after app restart.
/// An unreadable/failed secure write stops the operation before any network write.
class CustomerWorkspace {
  CustomerWorkspace(this.controller, {WorkspaceWriteStore? store})
    : store =
          store ??
          (controller.isDemo
              ? MemoryWorkspaceWriteStore()
              : SecureWorkspaceWriteStore()),
      customerId = controller.snapshot!.profile.id;
  static final _instances = Expando<CustomerWorkspace>();
  static final _sending = <String>{};
  static CustomerWorkspace forController(PlusController controller) =>
      _instances[controller] ??= CustomerWorkspace(controller);
  final PlusController controller;
  final WorkspaceWriteStore store;
  final String customerId;
  bool get current => controller.isCurrentCustomer(customerId);
  void check() {
    if (!current) {
      throw const PlusApiException('Please sign in to continue.', 401);
    }
  }

  String _scope(String operation) => '$customerId/$operation';
  String scopeFor(String operation) => _scope(operation);

  /// Drops an interrupted write so a fresh request can be prepared.
  Future<void> discardPending(String operation) async {
    check();
    await store.clear(_scope(operation));
  }

  Future<PendingWorkspaceWrite?> pending(String operation) async {
    check();
    final result = await store.read(_scope(operation));
    check();
    return result;
  }

  Future<Json> write(
    String operation,
    Json body,
    Future<Json> Function(Json, String) send, {
    String? reviewTimeZone,
  }) async {
    check();
    final frozenBody = freezeJson(body);
    final scope = _scope(operation);
    if (!_sending.add(scope)) {
      throw const PlusApiException('This request is already being saved.');
    }
    try {
      var saved = await store.read(scope);
      check();
      if (saved != null && _canonical(saved.body) != _canonical(frozenBody)) {
        throw const PlusApiException(
          'Finish retrying the saved request before changing its details.',
          409,
        );
      }
      saved ??= PendingWorkspaceWrite(
        body: frozenBody,
        key: _uuid(),
        reviewTimeZone: reviewTimeZone,
      );
      await store.write(scope, saved);
      check();
      Json result;
      try {
        result = await send(
          jsonDecode(jsonEncode(saved.body)) as Json,
          saved.key,
        );
      } on PlusApiException catch (error) {
        // These are definite rejections. An uncertain outcome keeps replay identity.
        if ([400, 403, 404, 422].contains(error.statusCode)) {
          await store.clear(scope);
        }
        rethrow;
      }
      await store.clear(scope);
      check();
      return result;
    } finally {
      _sending.remove(scope);
    }
  }

  Future<Json> createDraft(Json body, {String? reviewTimeZone}) => write(
    'outreach-draft',
    body,
    controller.repository.createShopOutreach,
    reviewTimeZone: reviewTimeZone,
  );
  Future<Json> authorize(Json draft) => write(
    'outreach-authorize/${draft['id']}',
    {'share_contact': true, 'review_hash': draft['review_hash']},
    (body, key) => controller.repository.authorizeShopOutreach(
      draft['id'] as String,
      body,
      key,
    ),
  );
  Future<Json> addHistory(Json body) =>
      write('history-record', body, controller.repository.addKnowledgeRecord);

  /// Edits are naturally idempotent, so they bypass the pending-write store.
  Future<Json> updateHistory(String id, Json body) async {
    check();
    final result = await controller.repository.updateKnowledgeRecord(id, body);
    check();
    return result;
  }
}

Object? _ordered(Object? value) {
  if (value is Map) {
    return {
      for (final key in value.keys.cast<String>().toList()..sort())
        key: _ordered(value[key]),
    };
  }
  if (value is List) return value.map(_ordered).toList();
  return value;
}

String _canonical(Json body) => jsonEncode(_ordered(body));
String _uuid() {
  final random = Random.secure();
  final bytes = List.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}

String offsetTimestamp(DateTime value) {
  final offset = value.timeZoneOffset;
  final minutes = offset.inMinutes.abs();
  final zone =
      '${offset.isNegative ? '-' : '+'}${(minutes ~/ 60).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}';
  return '${value.toIso8601String().replaceFirst(RegExp(r'Z$'), '')}$zone';
}

String localSlotLabel(String timestamp) {
  final parsed = DateTime.tryParse(timestamp);
  if (parsed == null) return timestamp;
  final local = parsed.toLocal();
  final qualified = offsetTimestamp(local);
  final hour = local.hour % 12 == 0 ? 12 : local.hour % 12;
  return '${local.month}/${local.day}/${local.year} at $hour:${local.minute.toString().padLeft(2, '0')} ${local.hour >= 12 ? 'PM' : 'AM'} (${local.timeZoneName}, UTC${qualified.substring(qualified.length - 6)})';
}
