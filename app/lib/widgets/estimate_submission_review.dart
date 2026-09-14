import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../services/estimate_capture_steps.dart';
import '../state/plus_controller.dart';
import 'common.dart';
import 'workspace_widgets.dart';
import 'discovery_results.dart';

List<String> missingEstimateContact(CustomerProfile profile) => [
  if (profile.name.trim().isEmpty) 'name',
  if (!RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(profile.email.trim()))
    'email',
  if (profile.phone.replaceAll(RegExp(r'\D'), '').length < 7) 'phone',
  if (!RegExp(r'^\d{5}$').hasMatch(profile.postalCode.trim())) 'ZIP code',
];

class EstimateSubmissionReview extends StatefulWidget {
  const EstimateSubmissionReview({
    super.key,
    required this.controller,
    required this.estimate,
    required this.onEditProfile,
  });
  final PlusController controller;
  final CustomerEstimate estimate;
  final VoidCallback onEditProfile;
  @override
  State<EstimateSubmissionReview> createState() =>
      _EstimateSubmissionReviewState();
}

class _EstimateSubmissionReviewState
    extends WorkspaceState<EstimateSubmissionReview> {
  @override
  PlusController get controller => widget.controller;
  Json? discovery;
  String? serviceMode;
  bool loading = true;
  int epoch = 0;
  String scope = '';
  String get currentScope =>
      '${controller.snapshot?.profile.postalCode}|${widget.estimate.vehicleId}|${widget.estimate.discipline}';
  List<ProviderProfile> get providers => discovery == null
      ? []
      : [
              ...discoveryProviders(discovery!, 'providers'),
              ...discoveryProviders(discovery!, 'shop_visit_alternatives'),
            ]
            .take(100)
            .where(
              (p) =>
                  !p.independent &&
                  p.kind == 'shop' &&
                  p.specialties.contains(widget.estimate.discipline) &&
                  p.requestModes.isNotEmpty,
            )
            .toList();
  ProviderProfile? selected;
  ProviderProfile? get chosen =>
      widget.controller.pendingEstimate(widget.estimate.id)?.provider ??
      selected;
  bool share = false;
  late final String customerId;
  @override
  void initState() {
    super.initState();
    customerId = widget.controller.snapshot!.profile.id;
    selected = widget.controller.pendingEstimate(widget.estimate.id)?.provider;
    loadShops();
  }

  @override
  void changed() {
    if (active && scope != currentScope) {
      loadShops();
    } else {
      super.changed();
    }
  }

  Future<void> loadShops() async {
    if (!active) return;
    final run = ++epoch;
    setState(() {
      scope = currentScope;
      selected = null;
      share = false;
      serviceMode = null;
      discovery = null;
      error = null;
      loading = true;
    });
    if (controller.pendingEstimate(widget.estimate.id) != null) {
      setState(() => loading = false);
      return;
    }
    try {
      final value = await controller.repository.discoverProviders({
        'postal_code': controller.snapshot!.profile.postalCode,
        'vehicle_id': widget.estimate.vehicleId,
        'specialty': widget.estimate.discipline,
        'mobile_only': false,
      });
      if (!active || run != epoch || scope != currentScope) return;
      setState(() => discovery = value);
    } catch (e) {
      if (active && run == epoch) {
        setState(() => error = PlusController.readableError(e));
      }
    } finally {
      if (active && run == epoch) setState(() => loading = false);
    }
  }

  Future<void> _send() async {
    if (!active || busy) return;
    final snapshot = widget.controller.snapshot!;
    final pending = widget.controller.pendingEstimate(widget.estimate.id);
    final latest = snapshot.estimates
        .where((e) => e.id == widget.estimate.id)
        .firstOrNull;
    if (!share || chosen == null) {
      setState(
        () => error = chosen == null
            ? 'Choose a shop to review your estimate.'
            : 'Choose to share your saved details and photos with the selected shop.',
      );
      return;
    }
    if (pending == null && serviceMode == null) {
      setState(
        () => error = 'Choose a shop visit or mobile service before sharing.',
      );
      return;
    }
    if (pending == null &&
        (latest == null ||
            latest.status != 'draft' ||
            missingEstimateContact(snapshot.profile).isNotEmpty ||
            !estimatePhotosReady(snapshot, latest) ||
            scope != currentScope ||
            !providers.any(
              (p) => p.id == chosen!.id && p.requestModes.contains(serviceMode),
            ))) {
      setState(
        () => error =
            'Your details or shop availability changed. Close this review and check the estimate before sending.',
      );
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.controller.submitEstimate(
        widget.estimate.id,
        pending?.body ??
            {
              'provider_id': chosen!.id,
              'share_contact': true,
              'service_mode': serviceMode,
            },
        pending?.provider ?? chosen!,
      );
      if (widget.controller.isCurrentCustomer(customerId)) {
        await widget.controller.refresh();
      }
      if (mounted && widget.controller.isCurrentCustomer(customerId)) {
        final messenger = ScaffoldMessenger.of(context);
        Navigator.pop(context);
        messenger.showSnackBar(
          const SnackBar(
            content: Text(
              'Submission saved. Check delivery and review progress on your estimate.',
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted && widget.controller.isCurrentCustomer(customerId)) {
        setState(() => error = PlusController.readableError(e));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      if (!widget.controller.isCurrentCustomer(customerId)) {
        return const SizedBox.shrink();
      }
      final snapshot = widget.controller.snapshot!;
      final profile = snapshot.profile;
      final pending = widget.controller.pendingEstimate(widget.estimate.id);
      final missingContact = missingEstimateContact(profile);
      final canSend =
          pending != null ||
          (snapshot.capabilities.liveEstimates &&
              missingContact.isEmpty &&
              estimatePhotosReady(snapshot, widget.estimate) &&
              !loading &&
              providers.isNotEmpty);
      return FormSheet(
        title: 'Review estimate sharing',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              snapshot.vehicle(widget.estimate.vehicleId)?.title ??
                  'Your saved vehicle',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 6),
            Text(widget.estimate.description),
            const SizedBox(height: 12),
            Text(
              '${widget.estimate.photos.length} saved photos · ${specialtyLabel(widget.estimate.discipline)}',
            ),
            const SizedBox(height: 12),
            const Text(
              'The selected shop will receive your saved contact and vehicle details, damage description and attached photos. A price will appear only after the estimate is reviewed.',
            ),
            const SectionHeading('Your saved contact details'),
            Text(profile.name),
            Text(profile.email),
            Text(profile.phone),
            Text('Service ZIP: ${profile.postalCode}'),
            if (missingContact.isNotEmpty && pending == null) ...[
              const SizedBox(height: 10),
              Text(
                'Add your ${missingContact.join(', ')} in your Garage profile before sending.',
              ),
              TextButton.icon(
                key: const Key('estimate-edit-profile'),
                onPressed: busy ? null : widget.onEditProfile,
                icon: const Icon(Icons.person_outline),
                label: const Text('Edit profile in Garage'),
              ),
            ],
            const SectionHeading('Choose an estimating shop'),
            if (pending != null) ...[
              Text(
                pending.provider.name,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              const Text(
                'The previous submission has an unconfirmed outcome. Retry the saved submission to check its result; its shop and sharing choice stay the same.',
              ),
            ] else ...[
              if (loading) const LinearProgressIndicator(),
              if (discovery != null) DiscoveryNotice(discovery!),
              if (!loading && providers.isEmpty) ...[
                const Text(
                  'No accepting estimating shop was returned for this work within 30 miles of your saved ZIP. Your draft and photos remain saved. Refresh to check nearby shops again.',
                ),
                TextButton(
                  onPressed: busy || loading ? null : loadShops,
                  child: const Text('Refresh shops'),
                ),
              ],
              for (final provider in providers)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Semantics(
                    button: true,
                    selected: selected?.id == provider.id,
                    child: Card(
                      child: InkWell(
                        key: Key('estimate-provider-${provider.id}'),
                        borderRadius: BorderRadius.circular(16),
                        onTap: busy
                            ? null
                            : () => setState(() {
                                selected = provider;
                                serviceMode = provider.requestModes.length == 1
                                    ? provider.requestModes.single
                                    : null;
                                share = false;
                                error = null;
                              }),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(
                                selected?.id == provider.id
                                    ? Icons.radio_button_checked
                                    : Icons.radio_button_off,
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      provider.name,
                                      style: Theme.of(
                                        context,
                                      ).textTheme.titleMedium,
                                    ),
                                    if (provider.distanceMiles != null)
                                      Text(
                                        'About ${provider.distanceMiles!.toStringAsFixed(1)} mi from your ZIP center',
                                      ),
                                    if (provider.city.isNotEmpty)
                                      Text(provider.city),
                                    Text(
                                      provider.address,
                                      style: Theme.of(
                                        context,
                                      ).textTheme.bodySmall,
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              if (discovery != null) DiscoveryDetails(discovery!),
              if (chosen != null) ...[
                const SectionHeading('Service location'),
                for (final mode in chosen!.requestModes)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: OutlinedButton.icon(
                      key: Key('estimate-mode-$mode'),
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
            ],
            if (pending?.body['service_mode'] != null)
              ReviewBlock(
                'Service location',
                serviceModeLabel(pending!.body['service_mode'] as String),
              ),
            const SizedBox(height: 10),
            CheckboxListTile(
              key: const Key('estimate-share-contact'),
              value: share,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: Text(
                chosen == null
                    ? 'Choose a shop above to review contact and photo sharing.'
                    : 'Share my saved contact and vehicle details, damage description and ${widget.estimate.photos.length} photos with ${chosen!.name}.',
              ),
              onChanged: busy || chosen == null
                  ? null
                  : (value) => setState(() => share = value == true),
            ),
            if (error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            if (!snapshot.capabilities.liveEstimates && pending == null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  'Submission is currently unavailable. Your draft and photos remain saved.',
                ),
              ),
            const SizedBox(height: 12),
            BusyButton(
              key: const Key('estimate-send'),
              busy: busy,
              label: pending == null
                  ? 'Submit to selected shop'
                  : 'Retry saved submission',
              onPressed: canSend ? _send : null,
            ),
          ],
        ),
      );
    },
  );
}

class EstimateProgress extends StatelessWidget {
  const EstimateProgress({super.key, required this.estimate});
  final CustomerEstimate estimate;
  @override
  Widget build(BuildContext context) {
    final delivery = textOf(estimate.json, 'delivery_status');
    final processing = textOf(estimate.json, 'processing_state');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(switch (delivery) {
              'queued' => 'Waiting to send to the shop',
              'delivered' => 'Delivered to the shop',
              'failed' => 'Delivery to the shop failed',
              'local_preview' => 'Demo submission · no shop contacted',
              _ => 'Checking submission delivery',
            }, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            Text(switch (processing) {
              'pending' => 'Your photos are waiting for processing.',
              'processing' => 'Your photos are being processed for review.',
              'failed' =>
                'Photo processing needs attention. Contact the shop for help; your saved photos remain attached.',
              'complete' =>
                estimate.amountCents == null
                    ? 'Photo processing is complete. A price is not available yet.'
                    : 'Your estimate is ready to review.',
              _ => 'Review progress will appear here when available.',
            }),
            if (delivery == 'failed')
              const Padding(
                padding: EdgeInsets.only(top: 10),
                child: Text(
                  'Your submission is saved, but delivery has not been confirmed. Contact the selected shop before sending another request.',
                ),
              ),
            if (estimate.amountCents == null)
              const Padding(
                padding: EdgeInsets.only(top: 10),
                child: Text('No price has been quoted yet.'),
              ),
          ],
        ),
      ),
    );
  }
}
