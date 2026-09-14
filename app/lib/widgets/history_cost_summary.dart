import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../screens/history_screen.dart';
import '../services/receipt_upload.dart';
import '../state/plus_controller.dart';

class HistoryCostSummary extends StatefulWidget {
  const HistoryCostSummary({super.key, required this.controller});
  final PlusController controller;
  @override
  State<HistoryCostSummary> createState() => _HistoryCostSummaryState();
}

class _HistoryCostSummaryState extends State<HistoryCostSummary> {
  late final String owner;
  late final PlusController boundController;
  List<Json> records = [];
  bool loading = true, failed = false;
  int epoch = 0, revision = 0, tab = 0;
  String? vehicleId;
  bool get current =>
      mounted &&
      identical(widget.controller, boundController) &&
      widget.controller.isCurrentCustomer(owner);
  @override
  void initState() {
    super.initState();
    boundController = widget.controller;
    owner = widget.controller.snapshot!.profile.id;
    revision = widget.controller.historyRevision;
    vehicleId = widget.controller.selectedVehicle?.id;
    tab = widget.controller.tab;
    widget.controller.addListener(changed);
    load();
  }

  @override
  void dispose() {
    epoch++;
    boundController.removeListener(changed);
    super.dispose();
  }

  void changed() {
    if (!current) {
      if (mounted) {
        setState(() {
          records = [];
        });
      }
      return;
    }
    final c = widget.controller;
    final reload =
        revision != c.historyRevision ||
        vehicleId != c.selectedVehicle?.id ||
        (c.tab == 3 && tab != 3);
    revision = c.historyRevision;
    vehicleId = c.selectedVehicle?.id;
    tab = c.tab;
    if (reload) load();
  }

  Future<void> load() async {
    if (!current) return;
    final run = ++epoch;
    setState(() {
      loading = true;
      failed = false;
    });
    try {
      final result = await widget.controller.repository.getKnowledge();
      if (current && run == epoch) {
        setState(() => records = rowsOf(result, 'records'));
      }
    } catch (_) {
      if (current && run == epoch) setState(() => failed = true);
    } finally {
      if (current && run == epoch) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return const SizedBox.shrink();
    final vehicle = widget.controller.selectedVehicle;
    final rows = records
        .where((r) => vehicle != null && r['vehicle_id'] == vehicle.id)
        .toList();
    final totals = <String, int>{
      'Maintenance': 0,
      'Repairs': 0,
      'Modifications': 0,
    };
    var missing = 0;
    for (final r in rows) {
      final kind = historyCategory(textOf(r, 'service_type'));
      totals.putIfAbsent(kind, () => 0);
      if (r['cost_cents'] is! int) {
        missing++;
        continue;
      }
      totals[kind] = (totals[kind] ?? 0) + (r['cost_cents'] as int);
    }
    final total = totals.values.fold<int>(0, (a, b) => a + b);
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Your recorded costs',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 6),
              Text(vehicle?.title ?? 'Choose a vehicle in your garage'),
              if (loading)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 18),
                  child: LinearProgressIndicator(),
                ),
              if (failed) ...[
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Text(
                    'Costs could not be refreshed. Try again to see saved totals.',
                  ),
                ),
                OutlinedButton(
                  onPressed: load,
                  child: const Text('Retry cost summary'),
                ),
              ] else if (!loading) ...[
                const SizedBox(height: 18),
                for (final e in totals.entries)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: SizedBox(
                      width: double.infinity,
                      child: Wrap(
                        alignment: WrapAlignment.spaceBetween,
                        spacing: 12,
                        runSpacing: 4,
                        children: [
                          Text(e.key),
                          FittedBox(
                            fit: BoxFit.scaleDown,
                            child: Text(
                              receiptCost(e.value),
                              maxLines: 1,
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                const Divider(),
                const SizedBox(height: 8),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Expanded(
                      child: Text(
                        'Total · USD',
                        style: TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Flexible(
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerRight,
                        child: Text(
                          receiptCost(total),
                          maxLines: 1,
                          textAlign: TextAlign.end,
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  '${rows.length} saved ${rows.length == 1 ? 'entry' : 'entries'}${missing > 0 ? ' · $missing missing ${missing == 1 ? 'a cost' : 'costs'} (excluded)' : ''}',
                ),
                const SizedBox(height: 6),
                const Text('Based on the costs you’ve recorded.'),
              ],
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: () => openVehicleHistory(context, widget.controller),
                icon: const Icon(Icons.add),
                label: const Text('Add past work / receipt'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
