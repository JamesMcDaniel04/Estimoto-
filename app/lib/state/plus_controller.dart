import 'dart:convert';
import 'dart:math';
import 'package:flutter/foundation.dart';
import '../data/repository.dart';
import '../domain/models.dart';

class ChatEntry {
  ChatEntry.user(this.text) : answer = null;
  ChatEntry.assistant(this.answer) : text = answer!.reply;
  final String text;
  final AssistantAnswer? answer;
  bool get isUser => answer == null;
}

class PlusController extends ChangeNotifier {
  PlusController(this.repository);
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
    loading = true;
    error = null;
    _notify();
    try {
      snapshot = await repository.bootstrap();
      if (!snapshot!.vehicles.any((v) => v.id == selectedVehicleId)) {
        selectedVehicleId = snapshot!.vehicles.firstOrNull?.id;
      }
    } catch (e) {
      error = readableError(e);
    } finally {
      loading = false;
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
