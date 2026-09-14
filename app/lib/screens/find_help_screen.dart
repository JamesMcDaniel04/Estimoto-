import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../widgets/common.dart';
import '../widgets/workspace_widgets.dart';
import '../widgets/discovery_results.dart';
import '../widgets/dedicated_shop_choice.dart';
import 'my_shops_screen.dart';
import 'garage_forms.dart';

class FindHelpScreen extends StatefulWidget {
  const FindHelpScreen({super.key, required this.controller});
  final PlusController controller;
  @override
  State<FindHelpScreen> createState() => _FindHelpScreenState();
}

class _FindHelpScreenState extends WorkspaceState<FindHelpScreen> {
  @override
  PlusController get controller => widget.controller;
  String? specialty;
  bool mobileOnly = false, loading = true;
  Json? result;
  int epoch = 0;
  String scope = '';
  String get currentScope =>
      '${controller.selectedVehicle?.id}|${controller.snapshot?.profile.postalCode}|$specialty|$mobileOnly';
  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void changed() {
    if (active && scope != currentScope) {
      load();
    } else {
      super.changed();
    }
  }

  Future<void> load() async {
    if (!active) return;
    final run = ++epoch;
    final postal = controller.snapshot!.profile.postalCode,
        vehicle = controller.selectedVehicle?.id;
    setState(() {
      scope = currentScope;
      loading = postal.isNotEmpty;
      result = null;
      error = null;
    });
    if (postal.isEmpty) return;
    try {
      final value = await controller.repository.discoverProviders({
        'postal_code': postal,
        'vehicle_id': ?vehicle,
        if (specialty != null) 'specialty': specialty,
        'mobile_only': mobileOnly,
      });
      if (!active || run != epoch || scope != currentScope) return;
      setState(() => result = value);
    } catch (e) {
      if (active && run == epoch) {
        setState(() => error = PlusController.readableError(e));
      }
    } finally {
      if (active && run == epoch) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!current) return unavailable;
    final postal = controller.snapshot!.profile.postalCode;
    return PageBody(
      children: [
        const PageHeading(
          'Find your kind of help.',
          'Nearby shops, mobile providers and a place for your trusted favorites.',
        ),
        VehiclePicker(controller: controller),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.location_on_outlined),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        postal.isEmpty
                            ? 'Choose your service area'
                            : 'Near $postal',
                      ),
                    ),
                  ],
                ),
                TextButton(
                  onPressed: () => editProfile(context, controller),
                  child: const Text('Change service ZIP'),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 18),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: [
            for (final type in <String?>[null, ...discoverySpecialties])
              ChoiceChip(
                label: Text(
                  type == null ? 'All services' : specialtyLabel(type),
                ),
                selected: specialty == type,
                onSelected: (_) {
                  specialty = type;
                  load();
                },
              ),
          ],
        ),
        SwitchListTile.adaptive(
          contentPadding: EdgeInsets.zero,
          title: const Text('Come to me'),
          subtitle: const Text(
            'Find providers listing mobile coverage for my ZIP',
          ),
          value: mobileOnly,
          onChanged: (value) {
            mobileOnly = value;
            load();
          },
        ),
        if (postal.isEmpty)
          EmptyState(
            icon: Icons.location_searching,
            title: 'Where does your car need help?',
            message:
                'Add a service ZIP in your saved profile to find nearby shops.',
            action: 'Add ZIP code',
            onAction: () => editProfile(context, controller),
          ),
        if (loading)
          const Padding(
            padding: EdgeInsets.all(16),
            child: Column(
              children: [
                LinearProgressIndicator(),
                SizedBox(height: 12),
                Text(
                  'Checking nearby listings. A fresh search can take up to a minute.',
                ),
              ],
            ),
          ),
        if (error != null) WorkspaceError(error!),
        if (result != null)
          DiscoveryResults(
            key: ValueKey(scope),
            controller: controller,
            data: result!,
            vehicleId: controller.selectedVehicle?.id,
            postalCode: postal,
            specialty: specialty,
            mobileOnly: mobileOnly,
          ),
        if (postal.isNotEmpty)
          OutlinedButton.icon(
            onPressed: loading ? null : load,
            icon: const Icon(Icons.refresh),
            label: const Text('Refresh directory'),
          ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () => openMyShops(context, controller),
          icon: const Icon(Icons.storefront_outlined),
          label: const Text('My shops & scheduling'),
        ),
        OutlinedButton.icon(
          onPressed: () => controller.selectTab(2),
          icon: const Icon(Icons.support_agent_outlined),
          label: const Text('Let Estibot help me choose'),
        ),
      ],
    );
  }
}
