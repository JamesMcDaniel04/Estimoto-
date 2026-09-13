import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../services/estimate_capture_steps.dart';
import '../state/plus_controller.dart';
import 'common.dart';

List<String> missingEstimateContact(CustomerProfile profile) => [
  if (profile.name.trim().isEmpty) 'name',
  if (!RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(profile.email.trim()))
    'email',
  if (profile.phone.replaceAll(RegExp(r'\D'), '').length < 7) 'phone',
  if (!RegExp(r'^\d{5}$').hasMatch(profile.postalCode.trim())) 'ZIP code',
];

List<ProviderProfile> eligibleEstimateProviders(
  PlusSnapshot snapshot,
  CustomerEstimate estimate,
) => snapshot.providers
    .where(
      (provider) =>
          provider.kind == 'shop' &&
          provider.json['public_visible'] != false &&
          provider.matches(
            specialty: estimate.discipline,
            postalCode: snapshot.profile.postalCode,
          ),
    )
    .toList();

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

class _EstimateSubmissionReviewState extends State<EstimateSubmissionReview> {
  ProviderProfile? selected;
  ProviderProfile? get chosen =>
      widget.controller.pendingEstimate(widget.estimate.id)?.provider ??
      selected;
  bool share = false, busy = false;
  String? error;
  late final String customerId;
  @override
  void initState() {
    super.initState();
    customerId = widget.controller.snapshot!.profile.id;
    selected = widget.controller.pendingEstimate(widget.estimate.id)?.provider;
  }

  Future<void> _send() async {
    if (!widget.controller.isCurrentCustomer(customerId)) return;
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
    if (pending == null &&
        (latest == null ||
            latest.status != 'draft' ||
            missingEstimateContact(snapshot.profile).isNotEmpty ||
            !estimatePhotosReady(snapshot, latest) ||
            !eligibleEstimateProviders(
              snapshot,
              widget.estimate,
            ).any((p) => p.id == chosen!.id))) {
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
        pending?.body ?? {'provider_id': chosen!.id, 'share_contact': true},
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
      final providers = eligibleEstimateProviders(snapshot, widget.estimate);
      final canSend =
          pending != null ||
          (snapshot.capabilities.liveEstimates &&
              missingContact.isEmpty &&
              estimatePhotosReady(snapshot, widget.estimate) &&
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
            ] else if (providers.isEmpty) ...[
              const Text(
                'No accepting shop currently matches this estimate type and your saved ZIP code. Your draft and photos remain saved. Check your profile or try again later.',
              ),
              TextButton(
                onPressed: busy ? null : () => widget.controller.refresh(),
                child: const Text('Refresh shops'),
              ),
            ] else
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
