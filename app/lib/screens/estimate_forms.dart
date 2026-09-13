import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';

Future<void> newEstimate(
  BuildContext context,
  PlusController controller,
) async {
  if (controller.selectedVehicle == null) {
    showMessage(context, 'Add a vehicle in your garage first.');
    controller.selectTab(0);
    return;
  }
  final id = await showModalBottomSheet<String>(
    context: context,
    isScrollControlled: true,
    builder: (_) => _EstimateForm(controller: controller),
  );
  if (id != null && context.mounted) {
    controller.selectTab(1);
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) =>
            EstimateDetailScreen(controller: controller, estimateId: id),
      ),
    );
  }
}

class _EstimateForm extends StatefulWidget {
  const _EstimateForm({required this.controller});
  final PlusController controller;
  @override
  State<_EstimateForm> createState() => _EstimateFormState();
}

class _EstimateFormState extends State<_EstimateForm> {
  final description = TextEditingController();
  final claim = TextEditingController();
  DateTime? lossDate;
  late String discipline;
  bool busy = false;
  String? error;
  @override
  void initState() {
    super.initState();
    discipline = widget.controller.discipline;
  }

  @override
  void dispose() {
    description.dispose();
    claim.dispose();
    super.dispose();
  }

  Future<void> save() async {
    if (description.text.trim().length < 5) {
      setState(() => error = 'Describe the damage in a few words.');
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.controller.repository.createEstimate({
        'vehicle_id': widget.controller.selectedVehicle!.id,
        'discipline': discipline,
        'description': description.text.trim(),
        'claim_number': claim.text.trim(),
        'date_of_loss': lossDate?.toIso8601String().substring(0, 10),
      });
      widget.controller.selectDiscipline(discipline);
      await widget.controller.refresh();
      if (mounted) Navigator.pop(context, result['id'] as String);
    } catch (e) {
      if (mounted) {
        setState(() {
          error = PlusController.readableError(e);
          busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => FormSheet(
    title: 'Start an estimate',
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        VehiclePicker(controller: widget.controller),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                value: 'pdr',
                label: Text('PDR'),
                icon: Icon(Icons.auto_fix_high_outlined),
              ),
              ButtonSegment(
                value: 'collision',
                label: Text('Collision'),
                icon: Icon(Icons.car_crash_outlined),
              ),
            ],
            selected: {discipline},
            onSelectionChanged: busy
                ? null
                : (v) => setState(() => discipline = v.first),
          ),
        ),
        const SizedBox(height: 18),
        Text(
          discipline == 'pdr'
              ? 'Door dings, small dents or hail damage.'
              : 'Body damage, paint repairs or accident damage.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 18),
        TextField(
          controller: description,
          maxLines: 3,
          maxLength: 2000,
          enabled: !busy,
          decoration: const InputDecoration(labelText: 'Describe the damage'),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: claim,
          enabled: !busy,
          maxLength: 100,
          decoration: const InputDecoration(
            labelText: 'Claim number (if you have one)',
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: busy
              ? null
              : () async {
                  final date = await showDatePicker(
                    context: context,
                    initialDate: lossDate ?? DateTime.now(),
                    firstDate: DateTime(2000),
                    lastDate: DateTime.now(),
                  );
                  if (date != null && mounted) setState(() => lossDate = date);
                },
          icon: const Icon(Icons.event_outlined),
          label: Text(
            lossDate == null
                ? 'Date of damage (optional)'
                : dateText(lossDate!.toIso8601String()),
          ),
        ),
        const SizedBox(height: 18),
        const Text(
          'Your saved vehicle and insurance details stay in your garage. Next, add photos to this draft.',
        ),
        const SizedBox(height: 20),
        if (error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        BusyButton(
          busy: busy,
          label: 'Save draft & add photos',
          icon: Icons.add_a_photo_outlined,
          onPressed: save,
        ),
      ],
    ),
  );
}

class EstimateDetailScreen extends StatefulWidget {
  const EstimateDetailScreen({
    super.key,
    required this.controller,
    required this.estimateId,
  });
  final PlusController controller;
  final String estimateId;
  @override
  State<EstimateDetailScreen> createState() => _EstimateDetailScreenState();
}

class _EstimateDetailScreenState extends State<EstimateDetailScreen> {
  bool uploading = false;
  String label = 'Damage detail';
  Future<void> photo(ImageSource source) async {
    setState(() => uploading = true);
    try {
      final file = await ImagePicker().pickImage(
        source: source,
        maxWidth: 2560,
        maxHeight: 2560,
        imageQuality: 90,
      );
      if (file != null) {
        await widget.controller.repository.uploadPhoto(
          widget.estimateId,
          await file.readAsBytes(),
          file.name,
          label,
        );
        await widget.controller.refresh();
        if (mounted) {
          showMessage(
            context,
            widget.controller.isDemo
                ? 'Photo added to the demo draft for this session.'
                : 'Photo saved to your draft.',
          );
        }
      }
    } catch (e) {
      if (mounted) showMessage(context, PlusController.readableError(e));
    } finally {
      if (mounted) setState(() => uploading = false);
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final estimate = widget.controller.snapshot?.estimates
          .where((e) => e.id == widget.estimateId)
          .firstOrNull;
      return Scaffold(
        appBar: AppBar(title: const Text('Your estimate')),
        body: estimate == null
            ? const Center(child: Text('This estimate is no longer available.'))
            : PageBody(
                children: [
                  if (widget.controller.isDemo)
                    const Padding(
                      padding: EdgeInsets.only(bottom: 16),
                      child: StatusPill('Demo · sample data'),
                    ),
                  PageHeading(
                    specialtyLabel(estimate.discipline),
                    widget.controller.snapshot!
                            .vehicle(estimate.vehicleId)
                            ?.title ??
                        'Your vehicle',
                  ),
                  StatusPill(estimate.statusLabel),
                  const SizedBox(height: 20),
                  Text(
                    estimate.description,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  if (estimate.amountCents != null) ...[
                    const SizedBox(height: 20),
                    Text(
                      moneyText(estimate.amountCents!),
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    Text(
                      widget.controller.isDemo
                          ? 'Example amount for this demo'
                          : estimate.providerName,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                  if (estimate.status == 'draft') ...[
                    const SizedBox(height: 20),
                    const Card(
                      child: Padding(
                        padding: EdgeInsets.all(18),
                        child: Text(
                          'This is a saved draft. A price will appear after your photos and damage are reviewed.',
                        ),
                      ),
                    ),
                    const SectionHeading('Add clear photos'),
                    const Text(
                      'Start with the whole vehicle, then the damaged area. Use good light and capture a close view and a wider view.',
                    ),
                    const SizedBox(height: 18),
                    DropdownButtonFormField<String>(
                      initialValue: label,
                      decoration: const InputDecoration(
                        labelText: 'What does this photo show?',
                      ),
                      items:
                          [
                                'Damage detail',
                                'Front of vehicle',
                                'Rear of vehicle',
                                'Driver side',
                                'Passenger side',
                                'Odometer',
                                'Engine bay',
                                'Tire tread',
                                'VIN',
                              ]
                              .map(
                                (s) =>
                                    DropdownMenuItem(value: s, child: Text(s)),
                              )
                              .toList(),
                      onChanged: (value) =>
                          setState(() => label = value ?? label),
                    ),
                    const SizedBox(height: 16),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        FilledButton.icon(
                          onPressed: uploading
                              ? null
                              : () => photo(ImageSource.camera),
                          icon: const Icon(Icons.camera_alt_outlined),
                          label: const Text('Take photo'),
                        ),
                        OutlinedButton.icon(
                          onPressed: uploading
                              ? null
                              : () => photo(ImageSource.gallery),
                          icon: const Icon(Icons.photo_library_outlined),
                          label: const Text('Choose photo'),
                        ),
                      ],
                    ),
                    if (uploading)
                      const Padding(
                        padding: EdgeInsets.only(top: 16),
                        child: LinearProgressIndicator(),
                      ),
                  ],
                  SectionHeading('Photos (${estimate.photos.length})'),
                  if (estimate.photos.isEmpty)
                    const Text(
                      'No photos attached yet.',
                      style: TextStyle(color: PlusColors.muted),
                    )
                  else
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final photo in estimate.photos)
                          Chip(
                            avatar: const Icon(
                              Icons.check_circle_outline,
                              size: 18,
                            ),
                            label: Text(textOf(photo, 'label')),
                          ),
                      ],
                    ),
                  if (estimate.status == 'draft') ...[
                    const SizedBox(height: 26),
                    if (!widget.controller.snapshot!.capabilities.liveEstimates)
                      const Text(
                        'Your draft is saved. Submission will open when the estimating service is connected.',
                        style: TextStyle(color: PlusColors.muted),
                      ),
                    const SizedBox(height: 12),
                    BusyButton(
                      busy: uploading,
                      label: 'Submit for review',
                      onPressed:
                          widget.controller.snapshot!.capabilities.liveEstimates
                          ? () => runAction(
                              context,
                              widget.controller,
                              () async {
                                await widget.controller.repository
                                    .submitEstimate(estimate.id);
                              },
                              success: 'Estimate submitted for review.',
                            )
                          : null,
                    ),
                  ],
                ],
              ),
      );
    },
  );
}
