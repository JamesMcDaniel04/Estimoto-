import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../domain/models.dart';

class PendingRequest {
  PendingRequest({
    required this.body,
    required this.key,
    required this.provider,
  });
  factory PendingRequest.fromJson(Json value) => PendingRequest(
    body: Map<String, dynamic>.from(value['body'] as Map),
    key: value['key'] as String,
    provider: ProviderProfile.fromJson(
      Map<String, dynamic>.from(value['provider'] as Map),
    ),
  );
  final Json body;
  final String key;
  final ProviderProfile provider;
  Json toJson() => {'body': body, 'key': key, 'provider': provider.json};
}

abstract class PendingRequestStore {
  Future<PendingRequest?> read(String customerId);
  Future<void> write(String customerId, PendingRequest request);
  Future<void> clear(String customerId);
}

class MemoryPendingRequestStore extends PendingRequestStore {
  final _values = <String, String>{};
  @override
  Future<PendingRequest?> read(String customerId) async {
    final raw = _values[customerId];
    return raw == null
        ? null
        : PendingRequest.fromJson(jsonDecode(raw) as Json);
  }

  @override
  Future<void> write(String customerId, PendingRequest request) async {
    _values[customerId] = jsonEncode(request.toJson());
  }

  @override
  Future<void> clear(String customerId) async => _values.remove(customerId);
}

/// The unresolved operation is retained per account until its receipt is known.
/// Storage must succeed before sending; failures cannot silently lose replay identity.
class SecurePendingRequestStore extends PendingRequestStore {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  String _key(String id) =>
      'estimoto_plus_pending_${base64Url.encode(utf8.encode(id))}';
  @override
  Future<PendingRequest?> read(String customerId) async {
    final raw = await _storage.read(key: _key(customerId));
    return raw == null
        ? null
        : PendingRequest.fromJson(jsonDecode(raw) as Json);
  }

  @override
  Future<void> write(String customerId, PendingRequest request) => _storage
      .write(key: _key(customerId), value: jsonEncode(request.toJson()));
  @override
  Future<void> clear(String customerId) =>
      _storage.delete(key: _key(customerId));
}
