import 'package:flutter/material.dart';
import '../data/repository.dart';
import '../domain/models.dart';
import '../services/receipt_upload.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';
import 'garage_forms.dart';
import 'history_screen.dart';

void openVehicleValue(BuildContext context, PlusController controller) {
  final vehicle = controller.selectedVehicle;
  if (vehicle == null) return;
  Navigator.push(
    context,
    MaterialPageRoute<void>(
      builder: (_) =>
          VehicleValueScreen(controller: controller, vehicleId: vehicle.id),
    ),
  );
}

class VehicleValueScreen extends StatefulWidget {
  const VehicleValueScreen({
    super.key,
    required this.controller,
    required this.vehicleId,
  });
  final PlusController controller;
  final String vehicleId;
  @override
  State<VehicleValueScreen> createState() => _VehicleValueScreenState();
}

class _VehicleValueScreenState extends State<VehicleValueScreen> {
  late final PlusController controller;
  late final String owner, id;
  String? state;
  String condition = 'average';
  String? error, requestFingerprint;
  Json? result;
  List<Json> pastLookups = [];
  bool busy = false, historyOutdated = false;
  int historyRevision = 0;
  int epoch = 0;
  Vehicle? get vehicle => controller.snapshot?.vehicle(id);
  bool get current =>
      mounted &&
      identical(widget.controller, controller) &&
      widget.vehicleId == id &&
      controller.isCurrentCustomer(owner);
  String get fingerprint =>
      '${vehicle?.year}|${vehicle?.make}|${vehicle?.model}|${vehicle?.vin}|${vehicle?.mileage}';
  @override
  void initState() {
    super.initState();
    controller = widget.controller;
    owner = controller.snapshot!.profile.id;
    id = widget.vehicleId;
    historyRevision = controller.historyRevision;
    controller.addListener(changed);
    loadPastLookups();
  }

  Future<void> loadPastLookups() async {
    if (!current || vehicle == null) return;
    try {
      final data = await controller.repository.listVehicleValuations(id);
      if (!current) return;
      setState(() => pastLookups = rowsOf(data, 'valuations'));
    } catch (e) {
      // A vanished vehicle is already shown by the record fallback; other
      // failures surface once the customer looks up a value.
      if (current && e is PlusApiException && e.statusCode != 404) {
        setState(() => error = PlusController.readableError(e));
      }
    }
  }

  Future<void> removePastLookup(Json row) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove this past lookup?'),
        content: const Text('Only your saved copy is removed.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true || !current) return;
    try {
      await controller.repository.deleteVehicleValuation(
        id,
        row['id'] as String,
      );
      await loadPastLookups();
    } catch (e) {
      if (current) setState(() => error = PlusController.readableError(e));
    }
  }

  String _bucketSummary(Json payload) => [
    for (final bucket in rowsOf(payload, 'buckets'))
      '${textOf(bucket, 'kind') == 'wholesale' ? 'Wholesale' : 'Retail'} ${receiptCost(intOf(bucket, 'amount_cents'))}',
  ].join(' · ');

  @override
  void dispose() {
    epoch++;
    controller.removeListener(changed);
    super.dispose();
  }

  void changed() {
    if (!mounted) return;
    if (historyRevision != controller.historyRevision && result != null) {
      result = {...result!, 'history': <String, dynamic>{}};
      historyOutdated = true;
    }
    historyRevision = controller.historyRevision;
    if (requestFingerprint != null && requestFingerprint != fingerprint) {
      epoch++;
      result = null;
      busy = false;
      error =
          'Your saved vehicle details changed. Check them and look up its value again.';
      requestFingerprint = null;
    }
    setState(() {});
  }

  void update(VoidCallback edit) {
    epoch++;
    setState(() {
      edit();
      result = null;
      error = null;
      busy = false;
    });
  }

  Future<void> lookup() async {
    if (!current || busy || state == null || vehicle == null) return;
    final run = ++epoch,
        saved = fingerprint,
        historyRun = controller.historyRevision;
    final body = <String, dynamic>{'state': state, 'condition': condition};
    bool valid() => current && run == epoch && saved == fingerprint;
    setState(() {
      busy = true;
      error = null;
      result = null;
      historyOutdated = false;
      requestFingerprint = saved;
    });
    try {
      final value = await controller.repository.lookupVehicleValue(
        id,
        body,
        isCurrent: valid,
      );
      if (!valid()) return;
      if (value['vehicle_id'] != id ||
          value['condition'] != body['condition'] ||
          value['state'] != body['state'] ||
          value['currency'] != 'USD') {
        throw const PlusApiException(
          'The value response did not match this vehicle. Try again.',
          502,
        );
      }
      setState(() {
        historyOutdated = historyRun != controller.historyRevision;
        result = historyOutdated
            ? {...value, 'history': <String, dynamic>{}}
            : value;
      });
      await loadPastLookups();
    } catch (e) {
      if (valid()) {
        setState(
          () => error = e is PlusApiException && e.statusCode == 422
              ? 'Check the saved VIN and mileage in Garage, then choose a state and condition.'
              : PlusController.readableError(e),
        );
      }
    } finally {
      if (valid()) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!current) {
      return const UnavailableRecordScreen(
        title: 'Vehicle value',
        message: 'Sign in again to view your vehicle value.',
      );
    }
    final car = vehicle;
    final ready =
        car != null &&
        RegExp(r'^[A-HJ-NPR-Z0-9]{17}$').hasMatch(car.vin.toUpperCase()) &&
        car.json['mileage'] != null;
    final values = result == null ? <Json>[] : rowsOf(result!, 'buckets');
    final history = result?['history'] is Map
        ? Map<String, dynamic>.from(result!['history'] as Map)
        : <String, dynamic>{};
    final available = result?['status'] == 'available' && values.isNotEmpty;
    return Scaffold(
      appBar: AppBar(title: const Text('Vehicle value')),
      body: PageBody(
        children: [
          PageHeading(
            'A market view of your car.',
            car?.title ?? 'This vehicle is no longer available.',
          ),
          Text(
            widget.controller.isDemo
                ? 'Preview a fictional valuation with a synthetic demo VIN. Live valuations use your saved VIN and mileage, plus your state and selected condition.'
                : 'Get a CarsXE estimate using your saved VIN and mileage, plus your state and the condition you select.',
          ),
          const SizedBox(height: 18),
          if (car != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ReviewBlock(
                      'Saved mileage',
                      '${mileageText(car.mileage)} miles',
                    ),
                    Text(
                      ready
                          ? 'VIN saved in Garage'
                          : 'Add a valid 17-character VIN and current mileage in Garage.',
                    ),
                    TextButton.icon(
                      onPressed: busy
                          ? null
                          : () async {
                              await editVehicle(
                                context,
                                controller,
                                vehicle: car,
                              );
                              if (current) setState(() {});
                            },
                      icon: const Icon(Icons.edit_outlined),
                      label: const Text('Edit vehicle details'),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 18),
          DropdownButtonFormField<String>(
            key: const Key('value-state'),
            initialValue: state,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Vehicle state'),
            items: [
              for (final entry in _states.entries)
                DropdownMenuItem(
                  value: entry.key,
                  child: Text('${entry.value} (${entry.key})'),
                ),
            ],
            onChanged: busy ? null : (value) => update(() => state = value),
          ),
          const SizedBox(height: 18),
          DropdownButtonFormField<String>(
            key: const Key('value-condition'),
            initialValue: condition,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Overall condition'),
            items: [
              for (final entry in const {
                'excellent': 'Excellent',
                'clean': 'Clean',
                'average': 'Average',
                'rough': 'Rough',
              }.entries)
                DropdownMenuItem(value: entry.key, child: Text(entry.value)),
            ],
            onChanged: busy
                ? null
                : (value) => update(() => condition = value!),
          ),
          const SizedBox(height: 10),
          const Text(
            'Choose the condition that best reflects the whole vehicle, including wear and repair needs.',
          ),
          const SizedBox(height: 20),
          BusyButton(
            busy: busy,
            label: 'Look up vehicle value',
            onPressed: ready && state != null ? lookup : null,
          ),
          if (error != null) WorkspaceError(error!),
          if (result != null) ...[
            if (result!['sample'] == true) ...[
              const StatusPill('Sample valuation • fictional amounts'),
              const SizedBox(height: 12),
              Text(textOf(result!, 'message')),
            ],
            const SectionHeading('Estimated market value'),
            if (!available)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Text(
                    textOf(
                      result!,
                      'message',
                      'A market estimate is unavailable right now. Your history is still saved.',
                    ),
                  ),
                ),
              ),
            if (available) ...[
              for (final bucket in values)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(switch (textOf(bucket, 'kind')) {
                          'retail' => 'Retail estimate',
                          'wholesale' => 'Wholesale estimate',
                          _ => 'Market estimate',
                        }, style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        FittedBox(
                          fit: BoxFit.scaleDown,
                          alignment: Alignment.centerLeft,
                          child: Text(
                            receiptCost(intOf(bucket, 'amount_cents')),
                            maxLines: 1,
                            style: Theme.of(context).textTheme.headlineMedium,
                          ),
                        ),
                        const Text('USD'),
                        const SizedBox(height: 8),
                        Text(
                          '${result!['sample'] == true ? 'Demo sample' : 'CarsXE'} · ${textOf(result!, 'condition')} condition',
                        ),
                        if (textOf(result!, 'provider_region').isNotEmpty &&
                            result!['provider_region'] != state)
                          Text(
                            'Provider market region: ${result!['provider_region']}',
                          ),
                        ExpansionTile(
                          tilePadding: EdgeInsets.zero,
                          title: const Text('How this estimate is presented'),
                          children: [
                            ReviewBlock(
                              result!['sample'] == true
                                  ? 'Sample base'
                                  : 'Provider base',
                              receiptCost(intOf(bucket, 'base_cents')),
                            ),
                            ReviewBlock(
                              'Mileage adjustment',
                              receiptCost(
                                intOf(bucket, 'mileage_adjustment_cents'),
                              ),
                            ),
                            ReviewBlock(
                              'Equipment adjustment',
                              receiptCost(
                                intOf(bucket, 'equipment_adjustment_cents'),
                              ),
                            ),
                            ReviewBlock(
                              'Region adjustment',
                              receiptCost(
                                intOf(bucket, 'regional_adjustment_cents'),
                              ),
                            ),
                            Text(
                              result!['sample'] == true
                                  ? 'These fixed fictional amounts demonstrate the display only. They are not calculated from this vehicle.'
                                  : bucket['amount_basis'] ==
                                        'provider_adjusted'
                                  ? 'The displayed amount is the provider’s adjusted estimate. Component details may not add to the same total.'
                                  : 'The displayed amount combines the provider’s base and listed adjustments.',
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              Text(
                result!['sample'] == true
                    ? 'Local demo sample'
                    : '${result!['cached'] == true ? 'Saved provider result' : 'Provider lookup'}${textOf(result!, 'fetched_at').isNotEmpty ? ' · ${dateText(textOf(result!, 'fetched_at'))}' : ''}',
              ),
              if (textOf(result!, 'provider_publish_date').isNotEmpty)
                Text(
                  'Provider data date: ${textOf(result!, 'provider_publish_date')}',
                ),
              const SizedBox(height: 12),
              const Text(
                'This is an estimate, not an offer or appraisal. Actual selling prices depend on the vehicle, local market and buyer. No trade-in value is shown unless supplied by the provider.',
              ),
            ],
            if (historyOutdated)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 16),
                child: Text(
                  'Your history changed after this lookup. Open history & receipts for the latest records.',
                ),
              ),
            if (history.isNotEmpty) ...[
              const SectionHeading('Your documented care'),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${intOf(history, 'records_count')} saved history entries · ${intOf(history, 'receipt_count')} receipts',
                      ),
                      if (history['costs_cents'] is int)
                        ReviewBlock(
                          'Recorded costs (USD)',
                          receiptCost(history['costs_cents'] as int),
                        ),
                      for (final factor in (history['factors'] as List? ?? []))
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Text(factor.toString()),
                        ),
                      const Text(
                        'Your records help document care and modifications. Their costs are kept separate from the provider’s market estimate.',
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ],
          const SectionHeading('Past lookups'),
          if (pastLookups.isEmpty)
            const Text('Lookups you run are kept here for this vehicle.')
          else
            for (final (index, row) in pastLookups.indexed)
              Card(
                child: ListTile(
                  title: Text(
                    '${index == 0 ? 'Latest · ' : ''}${dateText(textOf(row, 'created_at').substring(0, 10))}',
                  ),
                  subtitle: Text(
                    '${textOf(row, 'state')} · ${textOf(row, 'condition')} · ${mileageText(intOf(row, 'mileage'))} miles\n${_bucketSummary(row['payload'] as Json? ?? const {})}',
                  ),
                  isThreeLine: true,
                  trailing: IconButton(
                    tooltip: 'Remove past lookup',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: busy ? null : () => removePastLookup(row),
                  ),
                ),
              ),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            onPressed: () => openVehicleHistory(context, controller),
            icon: const Icon(Icons.receipt_long_outlined),
            label: const Text('View history & receipts'),
          ),
        ],
      ),
    );
  }
}

const _states = {
  'AL': 'Alabama',
  'AK': 'Alaska',
  'AZ': 'Arizona',
  'AR': 'Arkansas',
  'CA': 'California',
  'CO': 'Colorado',
  'CT': 'Connecticut',
  'DE': 'Delaware',
  'DC': 'District of Columbia',
  'FL': 'Florida',
  'GA': 'Georgia',
  'HI': 'Hawaii',
  'ID': 'Idaho',
  'IL': 'Illinois',
  'IN': 'Indiana',
  'IA': 'Iowa',
  'KS': 'Kansas',
  'KY': 'Kentucky',
  'LA': 'Louisiana',
  'ME': 'Maine',
  'MD': 'Maryland',
  'MA': 'Massachusetts',
  'MI': 'Michigan',
  'MN': 'Minnesota',
  'MS': 'Mississippi',
  'MO': 'Missouri',
  'MT': 'Montana',
  'NE': 'Nebraska',
  'NV': 'Nevada',
  'NH': 'New Hampshire',
  'NJ': 'New Jersey',
  'NM': 'New Mexico',
  'NY': 'New York',
  'NC': 'North Carolina',
  'ND': 'North Dakota',
  'OH': 'Ohio',
  'OK': 'Oklahoma',
  'OR': 'Oregon',
  'PA': 'Pennsylvania',
  'RI': 'Rhode Island',
  'SC': 'South Carolina',
  'SD': 'South Dakota',
  'TN': 'Tennessee',
  'TX': 'Texas',
  'UT': 'Utah',
  'VT': 'Vermont',
  'VA': 'Virginia',
  'WA': 'Washington',
  'WV': 'West Virginia',
  'WI': 'Wisconsin',
  'WY': 'Wyoming',
};
