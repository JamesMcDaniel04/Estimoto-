import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../screens/history_receipts_screen.dart';
import '../state/plus_controller.dart';
import 'receipt_work_items.dart';

class ReceiptWorkHistory extends StatelessWidget {
  const ReceiptWorkHistory({
    super.key,
    required this.records,
    required this.controller,
  });
  final List<Json> records;
  final PlusController controller;
  @override
  Widget build(BuildContext context) {
    final withReceipts =
        records.where((r) => rowsOf(r, 'receipts').isNotEmpty).toList()..sort(
          (a, b) =>
              textOf(b, 'service_date').compareTo(textOf(a, 'service_date')),
        );
    if (withReceipts.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 24),
        const Divider(),
        const SizedBox(height: 12),
        Text(
          'Work from your receipts',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 6),
        const Text(
          'Item amounts are for reference. Recorded costs use the saved entry total.',
        ),
        for (final record in withReceipts) ...[
          const SizedBox(height: 18),
          Text(
            '${textOf(record, 'service_date')} · ${textOf(record, 'shop_name').isEmpty ? 'Saved work' : textOf(record, 'shop_name')}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          for (final receipt in rowsOf(record, 'receipts')) ...[
            const SizedBox(height: 8),
            Text(
              textOf(receipt, 'filename'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
            ReceiptWorkItems(receipt: receipt),
          ],
          OutlinedButton.icon(
            key: ValueKey('work-receipt-${textOf(record, 'id')}'),
            onPressed: () => Navigator.of(context).push<void>(
              MaterialPageRoute(
                builder: (_) => HistoryReceiptsScreen(
                  controller: controller,
                  recordId: textOf(record, 'id'),
                ),
              ),
            ),
            icon: const Icon(Icons.receipt_long_outlined),
            label: const Text('View receipts / read details'),
          ),
        ],
      ],
    );
  }
}
