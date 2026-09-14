import 'receipt_pending_types.dart';

ReceiptPendingStore createStore() =>
    throw const ReceiptPendingException(ReceiptPendingFailure.storage);
