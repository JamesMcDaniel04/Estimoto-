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
  Future<List<Json>> listMyShops();
  Future<Json> saveMyShop(Json body, {String? id});
  Future<void> deleteMyShop(String id);
  Future<List<Json>> listShopOutreach();
  Future<Json> getShopOutreach(String id);
  Future<Json> createShopOutreach(Json body, String idempotencyKey);
  Future<Json> authorizeShopOutreach(
    String id,
    Json body,
    String idempotencyKey,
  );
  Future<Json> getKnowledge();
  Future<Json> addKnowledgeRecord(Json body, String idempotencyKey);
  Future<void> deleteKnowledgeRecord(String id);
  Future<Json> saveKnowledgePreferences(Json body);
  void close() {}
}
