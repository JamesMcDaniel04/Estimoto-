import 'dart:typed_data';
import '../domain/models.dart';
import 'receipt_pending_types.dart';

abstract class ReceiptApi {
  Future<Json> upload(ReceiptPending value);
  Future<Uint8List> read(String receiptId);
  Future<void> delete(String receiptId);
}
