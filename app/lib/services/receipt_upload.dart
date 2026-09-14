import 'dart:math';
import '../data/repository.dart';
import '../domain/models.dart';
import 'receipt_pending.dart';

/// One owner and one already-saved history entry. Reads never send a request.
class ReceiptUpload {
  ReceiptUpload({
    required this.ownerId,
    required this.recordId,
    required this.store,
    required this.isCurrent,
    required this.send,
  });
  final String ownerId, recordId;
  final ReceiptPendingStore store;
  final bool Function() isCurrent;
  final Future<Json> Function(ReceiptPending) send;
  static final _sending = <String>{};
  void check() {
    if (!isCurrent()) {
      throw const PlusApiException(
        'Your account changed. Reopen your history to continue.',
        401,
      );
    }
  }

  Future<ReceiptPending?> restore() async {
    check();
    final value = await store.read(ownerId);
    check();
    return value;
  }

  Future<void> stage(ReceiptPending value) async {
    check();
    if (value.ownerId != ownerId || value.recordId != recordId) {
      throw const PlusApiException(
        'Reopen the history entry for this receipt.',
        409,
      );
    }
    await store.write(value);
    check();
  }

  Future<Json> retry() async {
    check();
    if (!_sending.add(ownerId)) {
      throw const PlusApiException(
        'A receipt is already saving. Wait for its result.',
        409,
      );
    }
    try {
      final value = await restore();
      if (value == null || value.recordId != recordId) {
        throw const PlusApiException(
          'Open the original history entry to recover this receipt.',
          409,
        );
      }
      final result = await send(value);
      check();
      if (textOf(result, 'id').isEmpty) {
        throw const PlusApiException(
          'The receipt response was incomplete. Retry the saved file.',
          502,
        );
      }
      await store.clear(ownerId, value.operationId);
      check();
      return result;
    } finally {
      _sending.remove(ownerId);
    }
  }

  Future<void> discard(ReceiptPending value) async {
    check();
    if (value.ownerId != ownerId || value.recordId != recordId) {
      throw const PlusApiException(
        'Reopen the history entry for this receipt.',
        409,
      );
    }
    await store.clear(ownerId, value.operationId);
    check();
  }
}

String newReceiptOperation() {
  final random = Random.secure(),
      bytes = List.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}

int? parseReceiptCost(String input) {
  final value = input.trim();
  if (value.isEmpty) return null;
  if (!RegExp(r'^\d{1,8}(\.\d{1,2})?$').hasMatch(value)) {
    throw const FormatException(
      'Enter a USD total with no more than two decimal places.',
    );
  }
  final parts = value.split('.');
  final cents =
      int.parse(parts.first) * 100 +
      (parts.length == 1 ? 0 : int.parse(parts.last.padRight(2, '0')));
  if (cents > 100000000) {
    throw const FormatException('Enter a total no greater than USD 1,000,000.');
  }
  return cents;
}

String receiptCost(int cents) {
  final amount = cents.abs();
  final whole = (amount ~/ 100).toString().replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
    (m) => '${m[1]},',
  );
  return '${cents < 0 ? '-' : ''}\$$whole.${(amount % 100).toString().padLeft(2, '0')}';
}

String historyCategory(String service) => switch (service) {
  'modification' => 'Modifications',
  'repair' || 'diagnostics' || 'collision' || 'pdr' => 'Repairs',
  'oil_change' ||
  'tires' ||
  'brakes' ||
  'battery' ||
  'maintenance' => 'Maintenance',
  _ => 'Other',
};
