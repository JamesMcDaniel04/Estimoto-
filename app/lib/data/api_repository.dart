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
      return _decode(response);
    } on TimeoutException {
      throw const PlusApiException(
        'The connection timed out. Try again; your request will not be duplicated.',
      );
    } on http.ClientException {
      throw const PlusApiException(
        'Could not connect. Check your connection and try again.',
      );
    }
  }

  Json _decode(http.Response response) {
    if (response.statusCode == 401) {
      throw const PlusApiException(
        'Your session has ended. Please sign in again.',
        401,
      );
    }
    if (response.statusCode >= 300) {
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
        errors[response.statusCode] ??
            'We could not complete that action. Please try again.',
        response.statusCode,
      );
    }
    if (response.body.isEmpty) return {};
    try {
      return Map<String, dynamic>.from(jsonDecode(response.body) as Map);
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
  Future<Json> submitEstimate(String id) =>
      _send('POST', '/v1/estimates/${Uri.encodeComponent(id)}/submit');
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
  void close() => _client.close();
}
