import 'receipt_pending_types.dart';
import 'receipt_pending_unsupported.dart'
    if (dart.library.io) 'receipt_pending_native.dart'
    if (dart.library.js_interop) 'receipt_pending_web.dart'
    as platform;

export 'receipt_pending_types.dart';

/// Device-only storage. Await write before the first network request, then send
/// the stored fields and bytes unchanged on every retry. Verify the receipt's
/// operation/receipt hash before clearing the exact operation. A read never uploads.
/// The host must check its current account/history-entry epoch around each await;
/// storage intentionally has no authentication token or network knowledge.
/// Corrupt-data discard requires an explicit current-owner recovery decision.
ReceiptPendingStore createReceiptPendingStore() => platform.createStore();
