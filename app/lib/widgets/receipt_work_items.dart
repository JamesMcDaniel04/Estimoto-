import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../services/receipt_upload.dart';

/// Receipt wording stays attached to its source; only record.cost_cents counts
/// toward spending. These item amounts must never be added to the summary.
class ReceiptWorkItems extends StatelessWidget {
  const ReceiptWorkItems({super.key, required this.receipt});
  final Json receipt;
  @override
  Widget build(BuildContext context) {
    final extraction = receipt['total_extraction'] is Map
        ? Map<String, dynamic>.from(receipt['total_extraction'] as Map)
        : <String, dynamic>{};
    final items = rowsOf(extraction, 'work_items');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (extraction['items_status'] == 'needs_review')
          const Text(
            'Some receipt text was unclear. Check these details against the original.',
          ),
        if (items.isEmpty)
          const Text(
            'Work details have not been read from this receipt yet. Open it to read details or review the original.',
          ),
        for (final item in items)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  textOf(item, 'title'),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                if (item['amount_cents'] is int)
                  Text(
                    'Listed amount: ${receiptCost(item['amount_cents'] as int)}',
                  ),
                for (final task
                    in (item['tasks'] as List? ?? []).whereType<String>())
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text('• $task'),
                  ),
                if ((item['parts'] as List? ?? []).isNotEmpty) ...[
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text(
                      'Parts listed',
                      style: TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                  for (final part
                      in (item['parts'] as List).whereType<String>())
                    Text('• $part'),
                ],
              ],
            ),
          ),
      ],
    );
  }
}
