import 'dart:typed_data';
import '../domain/models.dart';

class PlusApiException implements Exception {
  const PlusApiException(this.message, [this.statusCode, this.code]);
  final String message;
  final int? statusCode;
  final String? code;
  @override
  String toString() => message;
}

abstract class PlusRepository {
  bool get isDemo;
  Future<PlusSnapshot> bootstrap();
  Future<Json> saveProfile(Json body);
  Future<Json> saveVehicle(Json body, {String? id});
  Future<void> deleteVehicle(String id);
  Future<Json> createEstimate(Json body);
  Future<Json> uploadPhoto(
    String estimateId,
    Uint8List bytes,
    String filename,
    String label,
  );
  Future<Uint8List> getPhoto(String estimateId, String photoId);
  Future<Json> submitEstimate(String id, Json body, String idempotencyKey);
  Future<Json> createRequest(Json body, String idempotencyKey);
  Future<Json> cancelRequest(String id);
  Future<Json> addReminder(Json body);
  Future<Json> completeReminder(String id);
  Future<AssistantAnswer> askAssistant(Json body);
  void close() {}
}
