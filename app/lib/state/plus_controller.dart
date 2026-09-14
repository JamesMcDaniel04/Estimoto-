import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import '../data/repository.dart';
import '../data/pending_request_store.dart';
import '../domain/models.dart';

class ChatEntry {
  ChatEntry.user(this.text) : answer = null;
  ChatEntry.assistant(this.answer) : text = answer!.reply;
  final String text;
  final AssistantAnswer? answer;
  bool get isUser => answer == null;
}

class PlusController extends ChangeNotifier {
  PlusController(this.repository, {PendingRequestStore? pendingStore})
    : pendingStore = pendingStore ?? MemoryPendingRequestStore();
  final PendingRequestStore pendingStore;
  PendingRequest? pendingRequest;
  final _pendingEstimates = <String, PendingRequest>{};
  final _sendingEstimates = <String>{};
  PendingRequest? pendingEstimate(String id) => _pendingEstimates[id];
  bool isCurrentCustomer(String id) =>
      !_disposed && _sessionActive && snapshot?.profile.id == id;
  String _estimateStorageKey(String customerId, String id) =>
      'estimate:$customerId:$id';
  int _refreshGeneration = 0;
  bool _sendingRequest = false;
  final PlusRepository repository;
  PlusSnapshot? snapshot;
  bool loading = false;
  bool asking = false;
  String? error;
  String? selectedVehicleId;
  int tab = 0;
  String discipline = 'pdr';
  final List<ChatEntry> messages = [];
  bool _disposed = false;
  bool _sessionActive = true;
  Vehicle? get selectedVehicle =>
      snapshot?.vehicle(selectedVehicleId ?? '') ??
      snapshot?.vehicles.firstOrNull;
  bool get isDemo => repository.isDemo || snapshot?.capabilities.demo == true;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  void selectTab(int value) {
    tab = value;
    _notify();
  }

  void selectVehicle(String value) {
    selectedVehicleId = value;
    _notify();
  }

  void selectDiscipline(String value) {
    discipline = value;
    _notify();
  }

  Future<void> refresh({bool quiet = false}) async {
    final generation = ++_refreshGeneration;
    loading = !quiet;
    error = null;
    _notify();
    try {
      final next = await repository.bootstrap();
      final pending = await pendingStore.read(next.profile.id);
      final estimates = <String, PendingRequest>{};
      for (final estimate in next.estimates) {
        final saved = await pendingStore.read(
          _estimateStorageKey(next.profile.id, estimate.id),
        );
        if (saved != null) estimates[estimate.id] = saved;
      }
      if (_disposed || generation != _refreshGeneration) return;
      snapshot = next;
      pendingRequest = pending;
      _pendingEstimates
        ..clear()
        ..addAll(estimates);
      if (!snapshot!.vehicles.any((v) => v.id == selectedVehicleId)) {
        selectedVehicleId = snapshot!.vehicles.firstOrNull?.id;
      }
    } catch (e) {
      if (!_disposed && generation == _refreshGeneration) {
        error = readableError(e);
      }
    } finally {
      if (!_disposed && generation == _refreshGeneration) {
        loading = false;
        _notify();
      }
    }
  }

  /// Revoke callback authority immediately, before Flutter disposes the old tree.
  void invalidateSession() {
    _sessionActive = false;
    ++_refreshGeneration;
    _notify();
  }

  void reportSessionError() {
    error =
        'Your sign-in could not refresh. Check your connection or sign in again.';
    _notify();
  }

  Future<Json> sendRequest(
    Json body,
    ProviderProfile provider, {
    String? reviewTimeZone,
  }) async {
    final customerId = snapshot?.profile.id;
    if (customerId == null || !isCurrentCustomer(customerId)) {
      throw const PlusApiException('Please sign in again to continue.', 401);
    }
    void requireOwner() {
      if (!isCurrentCustomer(customerId)) {
        throw const PlusApiException(
          'Your account changed. Please sign in again.',
          401,
        );
      }
    }

    if (_sendingRequest) {
      throw const PlusApiException('Your request is already being sent.');
    }
    final frozenBody = freezeJson(body);
    _sendingRequest = true;
    ++_refreshGeneration;
    loading = false;
    try {
      final saved = pendingRequest ?? await pendingStore.read(customerId);
      requireOwner();
      if (saved != null &&
          canonicalJson(saved.body) != canonicalJson(frozenBody)) {
        pendingRequest = saved;
        throw const PlusApiException(
          'Confirm the outcome of your previous request before changing its details.',
        );
      }
      final attempt =
          saved ??
          PendingRequest(
            body: frozenBody,
            key: requestKey(),
            provider: provider,
            reviewTimeZone: reviewTimeZone,
          );
      await pendingStore.write(customerId, attempt);
      requireOwner();
      pendingRequest = attempt;
      _notify();
      final result = await repository.createRequest(attempt.body, attempt.key);
      requireOwner();
      await pendingStore.clear(customerId);
      requireOwner();
      pendingRequest = null;
      return result;
    } on PlusApiException catch (error) {
      // Definitive rejection permits new choices; ambiguous outcomes retain exact replay.
      if (isCurrentCustomer(customerId) &&
          ([400, 403, 404, 422].contains(error.statusCode) ||
              (error.statusCode == 409 &&
                  error.code == 'request_not_created'))) {
        await pendingStore.clear(customerId);
        requireOwner();
        pendingRequest = null;
      }
      rethrow;
    } finally {
      _sendingRequest = false;
      if (isCurrentCustomer(customerId)) _notify();
    }
  }

  Future<Json> saveVehicle(Json body, {String? id}) async {
    final result = await repository.saveVehicle(body, id: id);
    selectedVehicleId = result['id'] as String;
    await refresh();
    return result;
  }

  Future<Json> submitEstimate(
    String id,
    Json body,
    ProviderProfile provider,
  ) async {
    final customerId = snapshot?.profile.id;
    if (customerId == null || !isCurrentCustomer(customerId)) {
      throw const PlusApiException('Please sign in again to continue.', 401);
    }
    if (!_sendingEstimates.add(id)) {
      throw const PlusApiException('This estimate is already being submitted.');
    }
    final storageKey = _estimateStorageKey(customerId, id);
    ++_refreshGeneration;
    loading = false;
    try {
      final saved =
          _pendingEstimates[id] ?? await pendingStore.read(storageKey);
      if (saved != null && !mapEquals(saved.body, body)) {
        _pendingEstimates[id] = saved;
        throw const PlusApiException(
          'Confirm your previous submission before choosing another shop.',
        );
      }
      final attempt =
          saved ??
          PendingRequest(
            body: Map<String, dynamic>.from(body),
            key: 'estimate:$id',
            provider: provider,
          );
      if (attempt.body['share_contact'] != true ||
          attempt.body['provider_id'] != provider.id) {
        throw const PlusApiException(
          'Review your shop and sharing choice before submitting.',
          422,
        );
      }
      await pendingStore.write(storageKey, attempt);
      _pendingEstimates[id] = attempt;
      _notify();
      if (!isCurrentCustomer(customerId)) {
        throw const PlusApiException(
          'Your account changed. Please sign in again.',
          401,
        );
      }
      final result = await repository.submitEstimate(
        id,
        attempt.body,
        attempt.key,
      );
      await pendingStore.clear(storageKey);
      _pendingEstimates.remove(id);
      return result;
    } on PlusApiException catch (error) {
      if ([400, 403, 404, 422].contains(error.statusCode)) {
        await pendingStore.clear(storageKey);
        _pendingEstimates.remove(id);
      }
      rethrow;
    } finally {
      _sendingEstimates.remove(id);
      _notify();
    }
  }

  Future<void> ask(String message) async {
    if (asking || message.trim().isEmpty) return;
    messages.add(ChatEntry.user(message.trim()));
    asking = true;
    _notify();
    try {
      final answer = await repository.askAssistant({
        'message': message.trim(),
        'vehicle_id': selectedVehicle?.id,
        'postal_code': snapshot?.profile.postalCode ?? '',
        'mobile_only': false,
      });
      messages.add(ChatEntry.assistant(answer));
    } catch (e) {
      messages.add(
        ChatEntry.assistant(
          AssistantAnswer.fromJson({
            'reply': readableError(e),
            'intent': 'advice',
          }),
        ),
      );
    } finally {
      asking = false;
      _notify();
    }
  }

  static String requestKey() => base64UrlEncode(
    List<int>.generate(24, (_) => Random.secure().nextInt(256)),
  );
  static String readableError(Object e) => e is PlusApiException
      ? e.message
      : 'We could not complete that action. Please try again.';
  @override
  void dispose() {
    _disposed = true;
    repository.close();
    super.dispose();
  }
}
