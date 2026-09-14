import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../services/customer_workspace.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';
import 'garage_forms.dart';
import 'history_receipts_screen.dart';
import '../services/receipt_pending.dart';
import '../services/receipt_upload.dart';

void openVehicleHistory(BuildContext context, PlusController controller) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => HistoryScreen(controller: controller),
    ),
  );
}

class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key, required this.controller});
  final PlusController controller;
  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends WorkspaceState<HistoryScreen> {
  @override
  PlusController get controller => widget.controller;
  List<Json> records = [];
  bool loading = true, loaded = false, share = false, pendingRecord = false;
  bool? uncertainPreference;
  int generation = 0;
  ReceiptPending? pendingReceipt;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    if (!active) return;
    final run = ++generation;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final values = await Future.wait<Object?>([
        controller.repository.getKnowledge(),
        workspace.pending('history-record'),
        controller.isDemo
            ? Future<ReceiptPending?>.value()
            : createReceiptPendingStore()
                  .read(workspace.customerId)
                  .catchError((Object _) => null),
      ]);
      if (!active || run != generation) return;
      final data = values[0] as Json;
      setState(() {
        loaded = true;
        records = rowsOf(data, 'records');
        share =
            (data['preferences'] as Map?)?['share_aggregate_insights'] == true;
        pendingRecord = values[1] != null;
        pendingReceipt = values[2] as ReceiptPending?;
        uncertainPreference = null;
      });
    } catch (e) {
      if (active && run == generation) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    } finally {
      if (active && run == generation) {
        setState(() {
          loading = false;
        });
      }
    }
  }

  Future<void> add() async {
    final saved = await Navigator.of(context).push<Json>(
      MaterialPageRoute<Json>(
        builder: (_) => HistoryEditor(controller: controller),
      ),
    );
    if (active && saved != null) await openReceipts(textOf(saved, 'id'));
    if (active) await load();
  }

  Future<void> openReceipts(String id) async {
    if (!active) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) =>
            HistoryReceiptsScreen(controller: controller, recordId: id),
      ),
    );
    if (active) await load();
  }

  Future<void> preference(bool selected) async {
    await perform(() async {
      setState(() {
        uncertainPreference = selected;
      });
      final result = await controller.repository.saveKnowledgePreferences({
        'share_aggregate_insights': selected,
      });
      if (active) {
        setState(() {
          share = result['share_aggregate_insights'] == true;
          uncertainPreference = null;
        });
      }
    });
  }

  Future<void> remove(Json record) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this history entry?'),
        content: Text(
          '${serviceName(textOf(record, 'service_type'))} on ${dateText(textOf(record, 'service_date'))} will be removed from your personal history.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep entry'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete entry'),
          ),
        ],
      ),
    );
    if (confirmed != true || !active) return;
    await perform(() async {
      await controller.repository.deleteKnowledgeRecord(record['id'] as String);
      if (active) {
        controller.historyChanged();
        await load();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final vehicle = controller.selectedVehicle;
    final visible = records
        .where((r) => vehicle == null || r['vehicle_id'] == vehicle.id)
        .toList();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Service history & receipts'),
        actions: [
          IconButton(
            tooltip: 'Refresh service history',
            onPressed: busy || loading ? null : load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: PageBody(
        children: [
          const PageHeading(
            'The story of your car.',
            'Save past repairs, maintenance and modifications with receipts, costs and parts details. These are your own records.',
          ),
          VehiclePicker(controller: controller),
          const SizedBox(height: 18),
          FilledButton.icon(
            onPressed: busy || loading
                ? null
                : vehicle == null
                ? () => editVehicle(context, controller)
                : add,
            icon: const Icon(Icons.add),
            label: Text(
              vehicle == null
                  ? 'Add a vehicle'
                  : pendingRecord
                  ? 'Recover saved history entry'
                  : 'Add service history',
            ),
          ),
          if (error != null) WorkspaceError(error!),
          if (loading)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: CircularProgressIndicator()),
            ),
          if (pendingReceipt != null)
            Card(
              child: ListTile(
                leading: const Icon(Icons.upload_file_outlined),
                title: const Text('A receipt is waiting to finish'),
                subtitle: const Text(
                  'Review the original entry to retry its saved attachment.',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: busy
                    ? null
                    : () => openReceipts(pendingReceipt!.recordId),
              ),
            ),
          if (visible.any((r) => r['cost_cents'] is int)) ...[
            const SectionHeading('Documented costs'),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final category in [
                      'Repairs',
                      'Maintenance',
                      'Modifications',
                      'Other',
                    ])
                      ReviewBlock(
                        category,
                        receiptCost(
                          visible
                              .where(
                                (r) =>
                                    historyCategory(
                                      textOf(r, 'service_type'),
                                    ) ==
                                    category,
                              )
                              .fold<int>(
                                0,
                                (sum, r) =>
                                    sum +
                                    (r['cost_cents'] is int
                                        ? r['cost_cents'] as int
                                        : 0),
                              ),
                        ),
                      ),
                    const Text(
                      'Your recorded spending in USD. Costs are not an estimate of resale value.',
                    ),
                  ],
                ),
              ),
            ),
          ],
          const SectionHeading('Your service records'),
          if (!loading && visible.isEmpty)
            const EmptyState(
              icon: Icons.history_outlined,
              title: 'Start with your last service',
              message:
                  'Save its date, mileage, shop and any parts details you want to remember.',
            ),
          for (final record in visible)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Text(
                              serviceName(textOf(record, 'service_type')),
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                          ),
                          IconButton(
                            tooltip: 'Delete history entry',
                            onPressed: busy ? null : () => remove(record),
                            icon: const Icon(Icons.delete_outline),
                          ),
                        ],
                      ),
                      Text(dateText(textOf(record, 'service_date'))),
                      if (record['mileage'] != null)
                        Text('${mileageText(intOf(record, 'mileage'))} miles'),
                      const SizedBox(height: 12),
                      if (textOf(record, 'shop_name').isNotEmpty)
                        ReviewBlock('Shop', textOf(record, 'shop_name')),
                      if (textOf(record, 'parts_source').isNotEmpty)
                        ReviewBlock(
                          'Parts source',
                          textOf(record, 'parts_source'),
                        ),
                      if (textOf(record, 'parts_description').isNotEmpty)
                        ReviewBlock(
                          'Parts',
                          textOf(record, 'parts_description'),
                        ),
                      if (textOf(record, 'notes').isNotEmpty)
                        ReviewBlock('Your notes', textOf(record, 'notes')),
                      if (record['cost_cents'] is int)
                        ReviewBlock(
                          'Recorded total (USD)',
                          receiptCost(record['cost_cents'] as int),
                        ),
                      const StatusPill('Added by you'),
                      const SizedBox(height: 12),
                      OutlinedButton.icon(
                        onPressed: busy
                            ? null
                            : () => openReceipts(textOf(record, 'id')),
                        icon: const Icon(Icons.receipt_long_outlined),
                        label: Text(
                          'Receipts (${rowsOf(record, 'receipts').length}) · View or add',
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          const SectionHeading('Your choice about insights'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (!loaded)
                    const Text(
                      'Refresh to load your saved insights-sharing choice.',
                    ),
                  if (loaded)
                    SwitchListTile(
                      key: const Key('insights-consent'),
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Help improve repair insights'),
                      value: share,
                      onChanged: loading || busy || uncertainPreference != null
                          ? null
                          : preference,
                    ),
                  const Text(
                    'Optionally share grouped service needs, requests and parts-source trends. Contact details, VIN, insurance and free-text notes are excluded. You can turn this off at any time; your personal history will still work.',
                  ),
                  if (uncertainPreference != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      'Your change to turn insights sharing ${uncertainPreference! ? 'on' : 'off'} has not been confirmed. Retry or refresh to check the saved setting.',
                    ),
                    OutlinedButton(
                      onPressed: busy
                          ? null
                          : () => preference(uncertainPreference!),
                      child: const Text('Retry preference change'),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class HistoryEditor extends StatefulWidget {
  const HistoryEditor({super.key, required this.controller});
  final PlusController controller;
  @override
  State<HistoryEditor> createState() => _HistoryEditorState();
}

class _HistoryEditorState extends WorkspaceState<HistoryEditor> {
  @override
  PlusController get controller => widget.controller;
  final form = GlobalKey<FormState>();
  final fields = <String, TextEditingController>{};
  String? vehicleId;
  String type = 'maintenance';
  DateTime date = DateTime.now();
  PendingWorkspaceWrite? pending;
  bool restoring = true;
  @override
  void initState() {
    super.initState();
    for (final key in [
      'mileage',
      'cost_cents',
      'shop_name',
      'parts_source',
      'parts_description',
      'notes',
    ]) {
      fields[key] = TextEditingController();
    }
    vehicleId = controller.selectedVehicle?.id;
    restore();
  }

  Future<void> restore() async {
    try {
      final saved = await workspace.pending('history-record');
      if (!active) return;
      setState(() {
        pending = saved;
        if (saved != null) {
          vehicleId = saved.body['vehicle_id'] as String?;
          type = textOf(saved.body, 'service_type');
          date = DateTime.parse(textOf(saved.body, 'service_date'));
          for (final entry in fields.entries) {
            entry.value.text =
                entry.key == 'cost_cents' && saved.body[entry.key] is int
                ? receiptCost(saved.body[entry.key] as int).substring(1)
                : saved.body[entry.key]?.toString() ?? '';
          }
        }
        restoring = false;
      });
    } catch (e) {
      if (active) {
        setState(() {
          error = PlusController.readableError(e);
        });
      }
    }
  }

  @override
  void dispose() {
    for (final field in fields.values) {
      field.dispose();
    }
    super.dispose();
  }

  Future<void> pickDate() async {
    final result = await showDatePicker(
      context: context,
      initialDate: date,
      firstDate: DateTime(1950),
      lastDate: DateTime.now(),
    );
    if (result != null && active) {
      setState(() {
        date = result;
      });
    }
  }

  Future<void> save() async {
    if (restoring || (pending == null && !form.currentState!.validate())) {
      return;
    }
    await perform(() async {
      final body =
          pending?.body ??
          <String, dynamic>{
            'vehicle_id': vehicleId,
            'service_type': type,
            'service_date':
                '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}',
            for (final entry in fields.entries)
              entry.key: entry.key == 'mileage'
                  ? int.tryParse(entry.value.text.trim())
                  : entry.key == 'cost_cents'
                  ? parseReceiptCost(entry.value.text)
                  : entry.value.text.trim(),
          };
      try {
        final result = await workspace.addHistory(body);
        if (mounted && active) {
          controller.historyChanged();
          Navigator.pop(context, result);
        }
      } catch (_) {
        if (active) {
          final saved = await workspace.pending('history-record');
          if (active) {
            setState(() {
              pending = saved;
            });
          }
        }
        rethrow;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final locked = busy || restoring || pending != null;
    return Scaffold(
      appBar: AppBar(title: const Text('Add service history')),
      body: PageBody(
        children: [
          const PageHeading(
            'Remember the details.',
            'Save work that has already happened. Add receipt photos or PDFs after saving this entry. Leave unknown details blank.',
          ),
          if (pending != null)
            const Padding(
              padding: EdgeInsets.only(bottom: 18),
              child: Text(
                'This entry may already be saved. Retry its original details to recover the result without adding a duplicate.',
              ),
            ),
          if (restoring && error == null) const CircularProgressIndicator(),
          if (restoring && error != null)
            OutlinedButton(
              onPressed: restore,
              child: const Text('Retry history recovery'),
            ),
          Form(
            key: form,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (pending != null)
                  ReviewBlock(
                    'Saved vehicle',
                    controller.snapshot!.vehicle(vehicleId ?? '')?.title ??
                        'Previously selected vehicle',
                  )
                else
                  SavedVehicleField(
                    controller: controller,
                    value: vehicleId,
                    enabled: !locked,
                    onChanged: (value) => setState(() {
                      vehicleId = value;
                    }),
                  ),
                const SizedBox(height: 18),
                DropdownButtonFormField<String>(
                  key: ValueKey('history-type-$type'),
                  initialValue: type,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Service type'),
                  items: [
                    for (final key in [
                      'oil_change',
                      'tires',
                      'brakes',
                      'battery',
                      'maintenance',
                      'repair',
                      'modification',
                      'diagnostics',
                      'collision',
                      'pdr',
                      'other',
                    ])
                      DropdownMenuItem(
                        value: key,
                        child: Text(serviceName(key)),
                      ),
                  ],
                  onChanged: locked
                      ? null
                      : (value) => setState(() {
                          type = value!;
                        }),
                ),
                const SizedBox(height: 18),
                OutlinedButton.icon(
                  onPressed: locked ? null : pickDate,
                  icon: const Icon(Icons.event_outlined),
                  label: Text(
                    'Service date: ${dateText(date.toIso8601String())}',
                  ),
                ),
                const SizedBox(height: 18),
                for (final key in fields.keys)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 18),
                    child: TextFormField(
                      key: ValueKey('history-$key'),
                      controller: fields[key],
                      enabled: !locked,
                      maxLength: key == 'notes'
                          ? 1000
                          : key == 'mileage'
                          ? 7
                          : 200,
                      maxLines: key == 'notes' ? 4 : 1,
                      keyboardType: key == 'mileage'
                          ? TextInputType.number
                          : key == 'cost_cents'
                          ? const TextInputType.numberWithOptions(decimal: true)
                          : TextInputType.text,
                      decoration: InputDecoration(
                        labelText: const {
                          'mileage': 'Mileage (optional)',
                          'cost_cents': 'Total cost in USD (optional)',
                          'shop_name': 'Shop or DIY (optional)',
                          'parts_source':
                              'Where the parts came from (optional)',
                          'parts_description': 'Parts used (optional)',
                          'notes': 'Notes (optional)',
                        }[key],
                        counterText: '',
                      ),
                      validator: (value) {
                        if (key == 'cost_cents') {
                          try {
                            parseReceiptCost(value ?? '');
                          } on FormatException {
                            return 'Enter USD 0–1,000,000 with up to two decimal places.';
                          }
                        }
                        return key == 'mileage' &&
                                value!.trim().isNotEmpty &&
                                (int.tryParse(value.trim()) == null ||
                                    int.parse(value.trim()) < 0)
                            ? 'Enter mileage as a whole number.'
                            : null;
                      },
                    ),
                  ),
                if (error != null) WorkspaceError(error!),
                BusyButton(
                  busy: busy,
                  label: pending != null
                      ? 'Recover saved entry'
                      : 'Save history entry',
                  onPressed: restoring ? null : save,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
