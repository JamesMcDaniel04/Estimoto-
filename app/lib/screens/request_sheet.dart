import 'dart:convert';
import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';

Future<void> requestProvider(
  BuildContext context,
  PlusController controller,
  ProviderProfile provider, {
  String? specialty,
  String description = '',
}) => showModalBottomSheet<void>(
  context: context,
  isScrollControlled: true,
  builder: (_) => RequestSheet(
    controller: controller,
    provider: provider,
    specialty: specialty,
    description: description,
  ),
);

class RequestSheet extends StatefulWidget {
  const RequestSheet({
    super.key,
    required this.controller,
    required this.provider,
    this.specialty,
    this.description = '',
  });
  final PlusController controller;
  final ProviderProfile provider;
  final String? specialty;
  final String description;
  @override
  State<RequestSheet> createState() => _RequestSheetState();
}

class _RequestSheetState extends State<RequestSheet> {
  late final TextEditingController description;
  final timing = TextEditingController();
  final form = GlobalKey<FormState>();
  late String specialty;
  bool share = false, busy = false;
  String? error, fingerprint;
  String key = PlusController.requestKey();
  @override
  void initState() {
    super.initState();
    description = TextEditingController(text: widget.description);
    specialty = widget.provider.specialties.contains(widget.specialty)
        ? widget.specialty!
        : widget.provider.specialties.first;
  }

  @override
  void dispose() {
    description.dispose();
    timing.dispose();
    super.dispose();
  }

  Future<void> send() async {
    if (!form.currentState!.validate()) return;
    if (!share) {
      setState(
        () => error =
            'Choose to share your contact and vehicle details to send this request.',
      );
      return;
    }
    final vehicle = widget.controller.selectedVehicle;
    if (vehicle == null) {
      setState(() => error = 'Add a vehicle in your garage first.');
      return;
    }
    final profile = widget.controller.snapshot!.profile;
    if (!RegExp(r'^\d{5}$').hasMatch(profile.postalCode)) {
      setState(
        () =>
            error = 'Add your service ZIP code in your profile before sending.',
      );
      return;
    }
    final body = <String, dynamic>{
      'vehicle_id': vehicle.id,
      'provider_id': widget.provider.id,
      'specialty': specialty,
      'description': description.text.trim(),
      'preferred_time': timing.text.trim(),
      'share_contact': true,
    };
    final nextFingerprint = jsonEncode(body);
    if (fingerprint != null && fingerprint != nextFingerprint) {
      key = PlusController.requestKey();
    }
    fingerprint = nextFingerprint;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.controller.repository.createRequest(body, key);
      await widget.controller.refresh();
      widget.controller.selectTab(3);
      if (mounted) {
        final messenger = ScaffoldMessenger.of(context);
        Navigator.pop(context);
        messenger.showSnackBar(
          SnackBar(
            content: Text(
              widget.controller.isDemo
                  ? 'Demo request saved. No provider was contacted.'
                  : 'Request saved. Track delivery and the provider’s response in Repairs.',
            ),
          ),
        );
      }
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
  Widget build(BuildContext context) {
    final p = widget.controller.snapshot!.profile;
    final canSend =
        widget.controller.isDemo ||
        widget.controller.snapshot!.capabilities.liveRequests;
    return FormSheet(
      title: 'Review your request',
      child: Form(
        key: form,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.provider.name,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 6),
            Text(
              'Your provider will confirm availability and pricing. A request does not reserve an appointment.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 20),
            VehiclePicker(controller: widget.controller),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: specialty,
              decoration: const InputDecoration(labelText: 'Service'),
              items: widget.provider.specialties
                  .map(
                    (s) => DropdownMenuItem(
                      value: s,
                      child: Text(specialtyLabel(s)),
                    ),
                  )
                  .toList(),
              onChanged: busy
                  ? null
                  : (s) => setState(() => specialty = s ?? specialty),
            ),
            const SizedBox(height: 16),
            TextFormField(
              key: const Key('request-description'),
              controller: description,
              enabled: !busy,
              maxLines: 3,
              maxLength: 2000,
              decoration: const InputDecoration(
                labelText: 'What would you like help with?',
              ),
              validator: (v) => (v?.trim().length ?? 0) < 5
                  ? 'Add a few details about the work'
                  : null,
            ),
            const SizedBox(height: 8),
            TextFormField(
              controller: timing,
              enabled: !busy,
              maxLength: 200,
              decoration: const InputDecoration(
                labelText: 'Preferred timing',
                hintText: 'For example, next week',
              ),
            ),
            const SizedBox(height: 12),
            Text(
              'Contact: ${p.name.isEmpty ? p.email : '${p.name} · ${p.email}'}${p.phone.isEmpty ? '' : '\n${p.phone}'}\nService ZIP: ${p.postalCode.isEmpty ? 'Add a ZIP code to your profile' : p.postalCode}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            CheckboxListTile(
              key: const Key('share-contact'),
              value: share,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: Text(
                'Share my contact details, selected vehicle and this request with ${widget.provider.name}.',
                style: const TextStyle(fontSize: 14),
              ),
              onChanged: busy
                  ? null
                  : (value) => setState(() => share = value == true),
            ),
            if (widget.controller.isDemo)
              const Padding(
                padding: EdgeInsets.only(bottom: 12),
                child: Text(
                  'Demo request: no technician or shop will be contacted.',
                ),
              ),
            if (!canSend)
              const Padding(
                padding: EdgeInsets.only(bottom: 12),
                child: Text(
                  'Provider requests are not connected yet. Please check back when early access opens.',
                ),
              ),
            if (error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            BusyButton(
              key: const Key('send-request'),
              busy: busy,
              label: widget.controller.isDemo
                  ? 'Save demo request'
                  : 'Send request',
              icon: Icons.send_outlined,
              onPressed: canSend ? send : null,
            ),
          ],
        ),
      ),
    );
  }
}
