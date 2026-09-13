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

  Future<void> refresh() async {
    final generation = ++_refreshGeneration;
    loading = true;
    error = null;
    _notify();
    try {
      final next = await repository.bootstrap();
      final pending = await pendingStore.read(next.profile.id);
      if (_disposed || generation != _refreshGeneration) return;
      snapshot = next;
      pendingRequest = pending;
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

  void reportSessionError() {
    error =
        'Your sign-in could not refresh. Check your connection or sign in again.';
    _notify();
  }

  Future<Json> sendRequest(Json body, ProviderProfile provider) async {
    if (_sendingRequest) {
      throw const PlusApiException('Your request is already being sent.');
    }
    final customerId = snapshot!.profile.id;
    _sendingRequest = true;
    ++_refreshGeneration;
    loading = false;
    try {
      final saved = pendingRequest ?? await pendingStore.read(customerId);
      if (saved != null && jsonEncode(saved.body) != jsonEncode(body)) {
        pendingRequest = saved;
        throw const PlusApiException(
          'Confirm the outcome of your previous request before changing its details.',
        );
      }
      final attempt =
          saved ??
          PendingRequest(
            body: Map<String, dynamic>.from(body),
            key: requestKey(),
            provider: provider,
          );
      await pendingStore.write(customerId, attempt);
      pendingRequest = attempt;
      _notify();
      final result = await repository.createRequest(attempt.body, attempt.key);
      await pendingStore.clear(customerId);
      pendingRequest = null;
      return result;
    } on PlusApiException catch (error) {
      // These responses definitively reject creation. Uncertain delivery keeps its identity.
      if ([400, 403, 404, 422].contains(error.statusCode)) {
        await pendingStore.clear(customerId);
        pendingRequest = null;
      }
      rethrow;
    } finally {
      _sendingRequest = false;
      _notify();
    }
  }

  Future<Json> saveVehicle(Json body, {String? id}) async {
    final result = await repository.saveVehicle(body, id: id);
    selectedVehicleId = result['id'] as String;
    await refresh();
    return result;
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
