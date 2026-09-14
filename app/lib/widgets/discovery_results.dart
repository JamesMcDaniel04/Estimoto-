import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../screens/request_sheet.dart';
import '../screens/my_shops_screen.dart';
import 'dedicated_shop_choice.dart';
import 'common.dart';
import 'workspace_widgets.dart';

String serviceModeLabel(String mode) => mode == 'mobile'
    ? 'Mobile service · provider comes to you'
    : 'Shop visit · bring your vehicle to the shop';

List<ProviderProfile> discoveryProviders(
  Json data,
  String key, {
  int limit = 100,
}) => rowsOf(data, key)
    .where((p) => p['public_visible'] != false)
    .take(limit)
    .map(ProviderProfile.fromJson)
    .toList();

class DiscoveryNotice extends StatelessWidget {
  const DiscoveryNotice(this.data, {super.key});
  final Json data;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 12),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Within 30 mi · Approximate distances',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (data['truncated'] == true)
          const Text(
            'Showing 100 listings total, including alternatives. Refine your service to narrow results.',
          ),
        if (data['status'] == 'stale')
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text(
              'Live search is unavailable. Showing saved listings; confirm current details with the shop.',
            ),
          ),
        if (data['status'] == 'unavailable')
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text(
              'Live directory search is unavailable. Any nearby providers shown are a partial list.',
            ),
          ),
      ],
    ),
  );
}

class DiscoveryDetails extends StatelessWidget {
  const DiscoveryDetails(this.data, {super.key});
  final Json data;
  @override
  Widget build(BuildContext context) => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    title: const Text('About these results'),
    childrenPadding: const EdgeInsets.only(bottom: 16),
    expandedCrossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        'Distances are approximate straight-line distances from your ZIP center, not driving distance or mobile coverage. Listings may not include every nearby business. Confirm services and availability directly.',
      ),
      if (textOf(data, 'checked_at').isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text('Last checked: ${dateText(textOf(data, 'checked_at'))}'),
        ),
      for (final attribution in rowsOf(data, 'source_attributions'))
        TextButton(
          onPressed: () => openExternal(context, textOf(attribution, 'url')),
          child: Text(textOf(attribution, 'name')),
        ),
    ],
  );
}

class DiscoveryResults extends StatefulWidget {
  const DiscoveryResults({
    super.key,
    required this.controller,
    required this.data,
    required this.vehicleId,
    required this.postalCode,
    this.specialty,
    this.mobileOnly = false,
    this.description = '',
  });
  final PlusController controller;
  final Json data;
  final String? vehicleId, specialty;
  final String postalCode, description;
  final bool mobileOnly;
  @override
  State<DiscoveryResults> createState() => _DiscoveryResultsState();
}

class _DiscoveryResultsState extends WorkspaceState<DiscoveryResults> {
  @override
  PlusController get controller => widget.controller;
  List<Json> favorites = [];
  int epoch = 0;
  bool get sameSearch =>
      active &&
      controller.selectedVehicle?.id == widget.vehicleId &&
      controller.snapshot!.profile.postalCode == widget.postalCode;
  @override
  void initState() {
    super.initState();
    loadFavorites();
  }

  @override
  void didUpdateWidget(covariant DiscoveryResults oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.vehicleId != widget.vehicleId) {
      favorites = [];
      loadFavorites();
    }
  }

  Future<void> loadFavorites() async {
    final run = ++epoch, vehicle = widget.vehicleId;
    if (vehicle == null || !sameSearch) return;
    try {
      final value = await controller.repository.listDiscoveryFavorites(vehicle);
      if (!sameSearch || run != epoch) return;
      setState(() {
        favorites = value;
        error = null;
      });
    } catch (e) {
      if (sameSearch && run == epoch) {
        setState(
          () => error =
              'Saved shop preferences could not be loaded. Refresh the directory to try again.',
        );
      }
    }
  }

  Future<void> save(ProviderProfile provider) async {
    if (!sameSearch || busy || widget.vehicleId == null) return;
    final run = epoch;
    await perform(() async {
      final saved = await chooseDedicatedShop(
        context,
        controller,
        source: provider.source,
        sourceId: provider.sourceId,
        vehicleId: widget.vehicleId!,
      );
      if (saved && sameSearch && run == epoch) await loadFavorites();
    });
  }

  Future<void> saveContact(ProviderProfile provider) async {
    if (!sameSearch) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => ShopEditor(
          controller: controller,
          initialContact: {
            'name': provider.name,
            'email': textOf(provider.json, 'email'),
            'phone': provider.phone,
            'address': provider.address,
            'website': textOf(provider.json, 'website'),
            'vehicle_id': widget.vehicleId,
            'notes': textOf(provider.json, 'source_url').isEmpty
                ? ''
                : 'Public listing: ${textOf(provider.json, 'source_url')}',
          },
        ),
      ),
    );
    if (!mounted || !sameSearch) return;
    openMyShops(context, controller, initialSummary: widget.description);
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return const SizedBox.shrink();
    if (!sameSearch) {
      return const Text(
        'Your vehicle or service ZIP changed. Search again for current shop options.',
      );
    }
    final providers = discoveryProviders(widget.data, 'providers');
    final alternatives = discoveryProviders(
      widget.data,
      'shop_visit_alternatives',
      limit: 100 - providers.length,
    );
    Widget card(ProviderProfile provider, bool alternative) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: DiscoveryProviderCard(
        provider: provider,
        vehicleMake: controller.snapshot!.vehicle(widget.vehicleId ?? '')?.make,
        favorites: favorites
            .where(
              (f) =>
                  f['source'] == provider.source &&
                  f['source_id'] == provider.sourceId,
            )
            .map((f) => specialtyLabel(textOf(f, 'specialty')))
            .toList(),
        onSave: widget.vehicleId == null || busy ? null : () => save(provider),
        onSaveContact: provider.independent
            ? () => saveContact(provider)
            : null,
        onRequest: provider.requestModes.isEmpty
            ? null
            : () {
                if (!sameSearch) return;
                requestProvider(
                  context,
                  controller,
                  provider,
                  specialty: widget.specialty,
                  description: widget.description,
                  searchedVehicleId: widget.vehicleId,
                  searchedPostalCode: widget.postalCode,
                  serviceMode: alternative
                      ? 'shop_visit'
                      : widget.mobileOnly
                      ? 'mobile'
                      : null,
                );
              },
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        DiscoveryNotice(widget.data),
        if (error != null) WorkspaceError(error!),
        if (providers.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 18),
            child: Text(
              widget.mobileOnly
                  ? 'No mobile provider lists coverage for this ZIP in these results. You can consider a shop visit below.'
                  : widget.data['status'] == 'ready'
                  ? 'No matching listings were returned. Try another service or check your saved ZIP.'
                  : 'Refresh the directory to check nearby options again.',
            ),
          ),
        for (final provider in providers) card(provider, false),
        if (alternatives.isNotEmpty) ...[
          const SectionHeading('Nearby shops you can visit'),
          const Text(
            'These are shop-visit alternatives. They do not list mobile coverage for this search.',
          ),
          for (final provider in alternatives) card(provider, true),
        ],
        DiscoveryDetails(widget.data),
      ],
    );
  }
}

class DiscoveryProviderCard extends StatelessWidget {
  const DiscoveryProviderCard({
    super.key,
    required this.provider,
    this.onRequest,
    this.onSave,
    this.onSaveContact,
    this.vehicleMake,
    this.favorites = const [],
  });
  final ProviderProfile provider;
  final VoidCallback? onRequest, onSave, onSaveContact;
  final String? vehicleMake;
  final List<String> favorites;
  Future<void> contact(BuildContext context, Uri uri) async {
    try {
      if (await launchUrl(uri, mode: LaunchMode.externalApplication)) return;
    } catch (_) {}
    if (context.mounted) {
      showMessage(context, 'Could not open this contact option.');
    }
  }

  @override
  Widget build(BuildContext context) {
    final match = provider.json['vehicle_match'] as Map? ?? {};
    final listedMake =
        match['status'] == 'listed_make' &&
        match['basis'] == 'service:vehicle:brand' &&
        vehicleMake != null &&
        '${match['make']}'.toLowerCase() == vehicleMake!.toLowerCase();
    final phone = provider.phone.replaceAll(RegExp(r'[^+\d]'), '');
    final website = Uri.tryParse(textOf(provider.json, 'website'));
    final validWebsite =
        website != null &&
        const ['https', 'http'].contains(website.scheme) &&
        website.host.isNotEmpty &&
        website.userInfo.isEmpty;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              provider.kind == 'technician'
                  ? Icons.handyman_outlined
                  : Icons.storefront_outlined,
              size: 28,
            ),
            const SizedBox(height: 12),
            Text(provider.name, style: Theme.of(context).textTheme.titleMedium),
            if (provider.distanceMiles != null)
              Text(
                'About ${provider.distanceMiles!.toStringAsFixed(1)} mi from your ZIP center',
              ),
            if (provider.address.isNotEmpty) Text(provider.address),
            const SizedBox(height: 12),
            Text(
              provider.independent
                  ? 'Independent listing · OpenStreetMap'
                  : 'Participating Estimoto provider',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (provider.specialties.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final service in provider.specialties)
                      StatusPill(specialtyLabel(service)),
                  ],
                ),
              ),
            if (listedMake)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(
                  'Listed support for ${match['make']} · confirm with the shop',
                ),
              ),
            if (provider.description.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(provider.description),
              ),
            if (provider.requestModes.contains('mobile'))
              const Padding(
                padding: EdgeInsets.only(top: 10),
                child: Text(
                  'Lists mobile service for this ZIP · availability requires confirmation',
                ),
              ),
            if (provider.independent)
              const Padding(
                padding: EdgeInsets.only(top: 10),
                child: Text(
                  'Contact this business directly. Estimoto does not send provider requests to this listing.',
                ),
              ),
            if (favorites.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text('Your dedicated shop: ${favorites.join(', ')}'),
              ),
            const SizedBox(height: 14),
            if (!provider.independent &&
                provider.requestModes.isNotEmpty &&
                onRequest != null)
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: onRequest,
                  child: const Text('Request help'),
                ),
              ),
            Wrap(
              spacing: 10,
              children: [
                if (RegExp(r'^\+?\d{7,15}$').hasMatch(phone))
                  TextButton.icon(
                    onPressed: () =>
                        contact(context, Uri(scheme: 'tel', path: phone)),
                    icon: const Icon(Icons.phone_outlined),
                    label: const Text('Call'),
                  ),
                if (validWebsite)
                  TextButton.icon(
                    onPressed: () => contact(context, website),
                    icon: const Icon(Icons.open_in_new),
                    label: const Text('Website'),
                  ),
                if (textOf(provider.json, 'source_url').isNotEmpty)
                  TextButton(
                    onPressed: () => openExternal(
                      context,
                      textOf(provider.json, 'source_url'),
                    ),
                    child: const Text('Listing source'),
                  ),
              ],
            ),
            OutlinedButton.icon(
              onPressed: onSave,
              icon: const Icon(Icons.bookmark_outline),
              label: Text(
                favorites.isEmpty
                    ? 'Save as my dedicated shop'
                    : 'Change or remove saved choice',
              ),
            ),
            if (onSaveContact != null)
              TextButton.icon(
                onPressed: onSaveContact,
                icon: const Icon(Icons.contact_page_outlined),
                label: const Text('Save contact for reviewed scheduling'),
              ),
            if (onSave == null && favorites.isEmpty)
              const Text('Choose a saved vehicle to save a dedicated shop.'),
          ],
        ),
      ),
    );
  }
}
