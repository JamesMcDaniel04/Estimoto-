import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';
import '../widgets/calendar_slot_picker.dart';
import '../services/calendar_time.dart';
import '../widgets/discovery_results.dart';

Future<void> requestProvider(
  BuildContext context,
  PlusController controller,
  ProviderProfile provider, {
  String? specialty,
  String? serviceMode,
  String? searchedVehicleId,
  String? searchedPostalCode,
  String description = '',
}) => showModalBottomSheet<void>(
  context: context,
  isScrollControlled: true,
  builder: (_) => RequestSheet(
    controller: controller,
    provider: controller.pendingRequest?.provider ?? provider,
    specialty: specialty,
    serviceMode: serviceMode,
    searchedVehicleId: searchedVehicleId,
    searchedPostalCode: searchedPostalCode,
    description: description,
  ),
);

class RequestSheet extends StatefulWidget {
  const RequestSheet({
    super.key,
    required this.controller,
    required this.provider,
    this.specialty,
    this.serviceMode,
    this.searchedVehicleId,
    this.searchedPostalCode,
    this.description = '',
  });
  final PlusController controller;
  final ProviderProfile provider;
  final String? specialty, serviceMode, searchedVehicleId, searchedPostalCode;
  final String description;
  @override
  State<RequestSheet> createState() => _RequestSheetState();
}

class _RequestSheetState extends WorkspaceState<RequestSheet> {
  @override
  PlusController get controller => widget.controller;
  CalendarSelection? calendar;
  late final TextEditingController description;
  final timing = TextEditingController();
  final form = GlobalKey<FormState>();
  late String specialty;
  String? serviceMode;
  bool share = false;
  bool get validSearch =>
      locked ||
      (widget.searchedPostalCode == null ||
              widget.searchedPostalCode ==
                  controller.snapshot?.profile.postalCode) &&
          (widget.searchedVehicleId == null ||
              widget.searchedVehicleId == controller.selectedVehicle?.id);
  bool get locked => widget.controller.pendingRequest != null;
  @override
  void initState() {
    super.initState();
    final pending = widget.controller.pendingRequest;
    serviceMode = pending != null
        ? pending.body['service_mode'] as String?
        : widget.serviceMode ??
              (widget.provider.requestModes.length == 1
                  ? widget.provider.requestModes.single
                  : null);
    description = TextEditingController(
      text: pending == null
          ? widget.description
          : textOf(pending.body, 'description'),
    );
    timing.text = pending == null ? '' : textOf(pending.body, 'preferred_time');
    specialty = pending != null
        ? textOf(pending.body, 'specialty')
        : widget.provider.specialties.contains(widget.specialty)
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
    if (!active || busy || !validSearch) return;
    if (!form.currentState!.validate()) return;
    if (!share) {
      setState(
        () => error =
            'Choose to share your contact and vehicle details to send this request.',
      );
      return;
    }
    final pending = widget.controller.pendingRequest;
    final vehicle = pending == null
        ? widget.controller.selectedVehicle
        : widget.controller.snapshot!.vehicle(
            textOf(pending.body, 'vehicle_id'),
          );
    if (vehicle == null && pending == null) {
      setState(() => error = 'Add a vehicle in your garage first.');
      return;
    }
    final profile = widget.controller.snapshot!.profile;
    if (pending == null && !RegExp(r'^\d{5}$').hasMatch(profile.postalCode)) {
      setState(
        () =>
            error = 'Add your service ZIP code in your profile before sending.',
      );
      return;
    }
    if (pending == null &&
        (widget.provider.independent ||
            !widget.provider.requestModes.contains(serviceMode))) {
      setState(
        () => error = 'Choose an available shop visit or mobile service.',
      );
      return;
    }
    final body =
        pending?.body ??
        <String, dynamic>{
          'vehicle_id': vehicle!.id,
          'provider_id': widget.provider.id,
          'specialty': specialty,
          'description': description.text.trim(),
          'preferred_time': timing.text.trim(),
          'share_contact': true,
          'service_mode': serviceMode,
          if (calendar != null) ...calendar!.requestFields,
        };
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.controller.sendRequest(
        body,
        widget.provider,
        reviewTimeZone: calendar?.timeZone,
      );
      if (!active) return;
      await widget.controller.refresh();
      if (!active) return;
      widget.controller.selectTab(3);
      if (mounted && active) {
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
      if (active) {
        setState(() {
          error = PlusController.readableError(e);
          busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    if (!validSearch) {
      return const FormSheet(
        title: 'Your search changed',
        child: Text(
          'Close this review and find nearby providers for your current vehicle and service ZIP.',
        ),
      );
    }
    final p = widget.controller.snapshot!.profile;
    final canSend =
        widget.controller.isDemo ||
        widget.controller.snapshot!.capabilities.liveRequests ||
        locked;
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
            if (locked) ...[
              const Text(
                'A previous send has an uncertain outcome. Retry the saved details to confirm its status before creating a different request. You can cancel it from Repairs once confirmed.',
              ),
              const SizedBox(height: 16),
              Text(
                widget.controller.snapshot!
                        .vehicle(
                          textOf(
                            widget.controller.pendingRequest!.body,
                            'vehicle_id',
                          ),
                        )
                        ?.title ??
                    'Your saved vehicle',
              ),
            ] else if (widget.searchedVehicleId != null)
              Text(
                controller.snapshot!
                        .vehicle(widget.searchedVehicleId!)
                        ?.title ??
                    'Your selected vehicle',
              )
            else
              VehiclePicker(controller: widget.controller),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: specialty,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Service'),
              items: widget.provider.specialties
                  .map(
                    (s) => DropdownMenuItem(
                      value: s,
                      child: Text(specialtyLabel(s)),
                    ),
                  )
                  .toList(),
              onChanged: busy || locked
                  ? null
                  : (s) => setState(() => specialty = s ?? specialty),
            ),
            const SizedBox(height: 16),
            if (locked)
              ReviewBlock(
                'Service location',
                serviceMode == null
                    ? 'As previously submitted'
                    : serviceModeLabel(serviceMode!),
              )
            else ...[
              const Text(
                'Service location',
                style: TextStyle(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              for (final mode in widget.provider.requestModes)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: OutlinedButton.icon(
                    key: Key('request-mode-$mode'),
                    onPressed: busy
                        ? null
                        : () => setState(() {
                            serviceMode = mode;
                            share = false;
                          }),
                    icon: Icon(
                      serviceMode == mode
                          ? Icons.radio_button_checked
                          : Icons.radio_button_off,
                    ),
                    label: Text(serviceModeLabel(mode)),
                  ),
                ),
            ],
            const SizedBox(height: 16),
            TextFormField(
              key: const Key('request-description'),
              controller: description,
              enabled: !busy && !locked,
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
            if (calendar != null ||
                widget.controller.pendingRequest?.body['calendar_check'] ==
                    true) ...[
              ReviewBlock(
                calendar?.sample == true
                    ? 'Sample preferred times'
                    : 'Calendar-checked preferred times',
                calendar?.label ??
                    (widget.controller.pendingRequest!.body['proposed_slots']
                            as List)
                        .map(
                          (s) => calendarSlotLabel(
                            s as String,
                            widget.controller.pendingRequest!.reviewTimeZone ??
                                'Etc/UTC',
                          ),
                        )
                        .join('\n\n'),
              ),
              Text(
                '${calendar?.duration ?? intOf(widget.controller.pendingRequest!.body, 'duration_minutes')} minutes reserved per offer. The provider must confirm.',
              ),
              if (!busy && !locked)
                TextButton(
                  onPressed: () => setState(() {
                    calendar = null;
                    timing.clear();
                    share = false;
                  }),
                  child: const Text('Offer timing manually instead'),
                ),
            ] else
              TextFormField(
                controller: timing,
                enabled: !busy && !locked,
                maxLength: 200,
                decoration: const InputDecoration(
                  labelText: 'Preferred timing',
                  hintText: 'For example, next week',
                ),
              ),
            if (!locked) ...[
              const SizedBox(height: 12),
              OutlinedButton.icon(
                key: const Key('choose-calendar-times'),
                onPressed: busy
                    ? null
                    : () async {
                        final choice = await pickCalendarSlots(
                          context,
                          controller,
                        );
                        if (!active || choice == null) return;
                        setState(() {
                          calendar = choice;
                          timing.text = choice.preferredTime;
                          share = false;
                          error = null;
                        });
                      },
                icon: const Icon(Icons.calendar_month_outlined),
                label: Text(
                  calendar == null
                      ? 'Find available times'
                      : 'Choose different times',
                ),
              ),
              if (calendar == null)
                const Text(
                  'Manual timing has not been checked against Google Calendar.',
                ),
            ],
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
                  : (value) => setState(() {
                      share = value == true;
                      error = null;
                    }),
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
