import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import '../domain/models.dart';
import 'repository.dart';

class ApiPlusRepository extends PlusRepository {
  ApiPlusRepository({
    required String baseUrl,
    required this.token,
    http.Client? client,
  }) : baseUri = Uri.parse(
         baseUrl.endsWith('/')
             ? baseUrl.substring(0, baseUrl.length - 1)
             : baseUrl,
       ),
       _client = client ?? http.Client() {
    if (!baseUri.hasAuthority ||
        (baseUri.scheme != 'https' &&
            !(baseUri.scheme == 'http' &&
                const [
                  'localhost',
                  '127.0.0.1',
                  '10.0.2.2',
                  '::1',
                ].contains(baseUri.host)))) {
      throw const PlusApiException(
        'A secure Estimoto + connection is required.',
      );
    }
    if (baseUri.userInfo.isNotEmpty ||
        baseUri.hasQuery ||
        baseUri.hasFragment ||
        (baseUri.path.isNotEmpty && baseUri.path != '/')) {
      throw const PlusApiException(
        'The Estimoto + address must be a server origin.',
      );
    }
  }
  final Uri baseUri;
  final Future<String?> Function() token;
  final http.Client _client;
  @override
  bool get isDemo => false;

  Future<Map<String, String>> _headers() async {
    final accessToken = await token();
    if (accessToken == null || accessToken.isEmpty) {
      throw const PlusApiException('Please sign in to continue.', 401);
    }
    return {
      'Authorization': 'Bearer $accessToken',
      'Accept': 'application/json',
    };
  }

  Future<Json> _send(
    String method,
    String path, {
    Json? body,
    String? idempotencyKey,
    bool collection = false,
  }) async {
    final request = http.Request(method, baseUri.resolve(path));
    request.headers.addAll(await _headers());
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    if (idempotencyKey != null) {
      request.headers['Idempotency-Key'] = idempotencyKey;
    }
    request.followRedirects = false;
    try {
      final response = await http.Response.fromStream(
        await _client.send(request).timeout(const Duration(seconds: 20)),
      ).timeout(const Duration(seconds: 20));
      return _decode(response, collection: collection);
    } on TimeoutException {
      throw const PlusApiException(
        'The connection timed out. Refresh to check whether your changes were saved before trying again.',
      );
    } on http.ClientException {
      throw const PlusApiException(
        'Could not connect. Check your connection and try again.',
      );
    }
  }

  Json _decode(http.Response response, {bool collection = false}) {
    if (response.statusCode == 401) {
      throw const PlusApiException(
        'Your session has ended. Please sign in again.',
        401,
      );
    }
    if (response.statusCode >= 300) {
      String? code;
      if (response.statusCode == 409) {
        try {
          final error = jsonDecode(response.body);
          if (error is Map && error['code'] == 'request_not_created') {
            code = 'request_not_created';
          }
        } on FormatException {
          // An unrecognized conflict remains unresolved; never guess it was rejected.
        }
      }
      const errors = {
        403: 'This action is not available for your account.',
        404: 'This item is no longer available.',
        409: 'This item has changed. Refresh and try again.',
        413: 'Choose a photo smaller than 10 MB.',
        415: 'Choose a JPEG, PNG or WebP photo.',
        422: 'Check the details and try again.',
        429: 'Please wait a moment before trying again.',
        503:
            'This service is not connected yet. Your saved drafts are still available.',
      };
      throw PlusApiException(
        code == 'request_not_created'
            ? 'That provider is no longer available for this request. Choose another provider.'
            : errors[response.statusCode] ??
                  'We could not complete that action. Please try again.',
        response.statusCode,
        code,
      );
    }
    if (response.body.isEmpty) return {};
    try {
      final decoded = jsonDecode(response.body);
      // Collection routes return bare arrays; keep object routes unchanged.
      if (collection && decoded is List) return {'items': decoded};
      return Map<String, dynamic>.from(decoded as Map);
    } on FormatException {
      throw const PlusApiException(
        'We received an unreadable response. Please try again.',
      );
    } on TypeError {
      throw const PlusApiException(
        'We received an unexpected response. Please try again.',
      );
    }
  }

  @override
  Future<PlusSnapshot> bootstrap() async =>
      PlusSnapshot.fromJson(await _send('GET', '/v1/bootstrap'));
  @override
  Future<Json> saveProfile(Json body) =>
      _send('PUT', '/v1/profile', body: body);
  @override
  Future<Json> saveVehicle(Json body, {String? id}) => _send(
    id == null ? 'POST' : 'PUT',
    id == null ? '/v1/vehicles' : '/v1/vehicles/${Uri.encodeComponent(id)}',
    body: body,
  );
  @override
  Future<void> deleteVehicle(String id) async {
    await _send('DELETE', '/v1/vehicles/${Uri.encodeComponent(id)}');
  }

  @override
  Future<Json> createEstimate(Json body) =>
      _send('POST', '/v1/estimates', body: body);
  @override
  Future<Json> submitEstimate(String id, Json body, String idempotencyKey) =>
      _send(
        'POST',
        '/v1/estimates/${Uri.encodeComponent(id)}/submit',
        body: body,
        idempotencyKey: idempotencyKey,
      );

  @override
  Future<Uint8List> getPhoto(String estimateId, String photoId) async {
    final request = http.Request(
      'GET',
      baseUri.resolve(
        '/v1/estimates/${Uri.encodeComponent(estimateId)}/photos/${Uri.encodeComponent(photoId)}',
      ),
    );
    request.headers.addAll(await _headers());
    request.followRedirects = false;
    try {
      final response = await _client
          .send(request)
          .timeout(const Duration(seconds: 20));
      if (response.statusCode != 200) {
        final body = await http.ByteStream(
          response.stream.take(1),
        ).toBytes().timeout(const Duration(seconds: 5));
        _decode(http.Response.bytes(body, response.statusCode));
        throw const PlusApiException('This photo could not be loaded.');
      }
      final result = BytesBuilder(copy: false);
      await for (final bytes in response.stream.timeout(
        const Duration(seconds: 20),
      )) {
        if (result.length + bytes.length > 10 * 1024 * 1024) {
          throw const PlusApiException('This photo is too large to display.');
        }
        result.add(bytes);
      }
      return result.takeBytes();
    } on TimeoutException {
      throw const PlusApiException('Photo loading timed out. Try again.');
    } on http.ClientException {
      throw const PlusApiException(
        'Could not load the photo. Check your connection.',
      );
    }
  }

  @override
  Future<Json> createRequest(Json body, String idempotencyKey) =>
      _send('POST', '/v1/requests', body: body, idempotencyKey: idempotencyKey);
  @override
  Future<Json> cancelRequest(String id) =>
      _send('POST', '/v1/requests/${Uri.encodeComponent(id)}/cancel');
  @override
  Future<Json> addReminder(Json body) =>
      _send('POST', '/v1/reminders', body: body);
  @override
  Future<Json> completeReminder(String id) =>
      _send('POST', '/v1/reminders/${Uri.encodeComponent(id)}/complete');
  @override
  Future<AssistantAnswer> askAssistant(Json body) async =>
      AssistantAnswer.fromJson(
        await _send('POST', '/v1/assistant', body: body),
      );

  @override
  Future<Json> uploadPhoto(
    String estimateId,
    Uint8List bytes,
    String filename,
    String label,
  ) async {
    final extension = filename.split('.').last.toLowerCase();
    final mime = switch (extension) {
      'jpg' || 'jpeg' => 'jpeg',
      'png' => 'png',
      'webp' => 'webp',
      _ => null,
    };
    if (mime == null) {
      throw const PlusApiException('Choose a JPEG, PNG or WebP photo.');
    }
    if (bytes.length > 10 * 1024 * 1024) {
      throw const PlusApiException('Choose a photo smaller than 10 MB.');
    }
    final request = http.MultipartRequest(
      'POST',
      baseUri.resolve(
        '/v1/estimates/${Uri.encodeComponent(estimateId)}/photos',
      ),
    );
    request.followRedirects = false;
    request.headers.addAll(await _headers());
    request.fields['label'] = label;
    request.files.add(
      http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: filename,
        contentType: MediaType('image', mime),
      ),
    );
    try {
      return _decode(
        await http.Response.fromStream(
          await _client.send(request).timeout(const Duration(seconds: 45)),
        ).timeout(const Duration(seconds: 45)),
      );
    } on TimeoutException {
      throw const PlusApiException(
        'Photo upload timed out. Refresh your draft before retrying.',
      );
    } on http.ClientException {
      throw const PlusApiException(
        'Photo upload failed. Check your connection and try again.',
      );
    }
  }

  @override
  Future<List<Json>> listMyShops() async =>
      rowsOf(await _send('GET', '/v1/my-shops', collection: true), 'items');
  @override
  Future<Json> saveMyShop(Json body, {String? id}) => _send(
    id == null ? 'POST' : 'PUT',
    id == null ? '/v1/my-shops' : '/v1/my-shops/${Uri.encodeComponent(id)}',
    body: body,
  );
  @override
  Future<void> deleteMyShop(String id) async {
    await _send('DELETE', '/v1/my-shops/${Uri.encodeComponent(id)}');
  }

  @override
  Future<List<Json>> listShopOutreach() async => rowsOf(
    await _send('GET', '/v1/shop-outreach', collection: true),
    'items',
  );
  @override
  Future<Json> getShopOutreach(String id) =>
      _send('GET', '/v1/shop-outreach/${Uri.encodeComponent(id)}');
  @override
  Future<Json> createShopOutreach(Json body, String idempotencyKey) => _send(
    'POST',
    '/v1/shop-outreach',
    body: body,
    idempotencyKey: idempotencyKey,
  );
  @override
  Future<Json> authorizeShopOutreach(
    String id,
    Json body,
    String idempotencyKey,
  ) => _send(
    'POST',
    '/v1/shop-outreach/${Uri.encodeComponent(id)}/authorize',
    body: body,
    idempotencyKey: idempotencyKey,
  );
  @override
  Future<Json> getKnowledge() => _send('GET', '/v1/knowledge');
  @override
  Future<Json> addKnowledgeRecord(Json body, String idempotencyKey) => _send(
    'POST',
    '/v1/knowledge/records',
    body: body,
    idempotencyKey: idempotencyKey,
  );
  @override
  Future<void> deleteKnowledgeRecord(String id) async {
    await _send('DELETE', '/v1/knowledge/records/${Uri.encodeComponent(id)}');
  }

  @override
  Future<Json> saveKnowledgePreferences(Json body) =>
      _send('PUT', '/v1/knowledge/preferences', body: body);

  @override
  void close() => _client.close();
}
