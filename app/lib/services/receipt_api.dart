import 'dart:typed_data';
import '../domain/models.dart';
import '../data/repository.dart';
import 'receipt_pending_types.dart';

abstract class ReceiptApi {
  Future<Json> upload(ReceiptPending value);
  Future<Uint8List> read(String receiptId);
  Future<void> delete(String receiptId);
  Future<Json> parseTotal(String receiptId) => throw const PlusApiException(
    'Total extraction is available when signed in.',
  );
  Future<Json> applyTotal(String receiptId, int? expectedCostCents) =>
      throw const PlusApiException(
        'Total extraction is available when signed in.',
      );
}
