import 'package:flutter/material.dart';
import '../domain/models.dart';
import '../state/plus_controller.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'garage_forms.dart';
import 'request_sheet.dart';

class FindHelpScreen extends StatefulWidget {
  const FindHelpScreen({super.key, required this.controller});
  final PlusController controller;
  @override
  State<FindHelpScreen> createState() => _FindHelpScreenState();
}

class _FindHelpScreenState extends State<FindHelpScreen> {
  String? specialty;
  bool mobileOnly = false;
  @override
  Widget build(BuildContext context) {
    final data = widget.controller.snapshot!;
    final postal = data.profile.postalCode;
    final providers = data.providers
        .where(
          (p) => p.matches(
            specialty: specialty,
            postalCode: postal,
            mobileOnly: mobileOnly,
          ),
        )
        .toList();
    return PageBody(
      children: [
        const PageHeading(
          'Find your kind of help.',
          'Connect with participating shops and technicians.',
        ),
        Card(
          child: ListTile(
            leading: const Icon(
              Icons.location_on_outlined,
              color: PlusColors.blue,
            ),
            title: Text(
              postal.isEmpty ? 'Choose your service area' : 'Serving $postal',
            ),
            subtitle: const Text('Your saved ZIP code'),
            trailing: TextButton(
              onPressed: () => editProfile(context, widget.controller),
              child: const Text('Change'),
            ),
          ),
        ),
        const SizedBox(height: 18),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: [
            for (final type in <String?>[
              null,
              'pdr',
              'collision',
              'maintenance',
              'mechanical',
            ])
              ChoiceChip(
                label: Text(
                  type == null ? 'All services' : specialtyLabel(type),
                ),
                selected: specialty == type,
                onSelected: (_) => setState(() => specialty = type),
              ),
          ],
        ),
        const SizedBox(height: 10),
        SwitchListTile.adaptive(
          contentPadding: EdgeInsets.zero,
          title: const Text('Come to me'),
          subtitle: const Text('Show mobile technicians'),
          value: mobileOnly,
          onChanged: (value) => setState(() => mobileOnly = value),
        ),
        const SizedBox(height: 8),
        if (postal.isEmpty)
          EmptyState(
            icon: Icons.location_searching,
            title: 'Where does your car need help?',
            message:
                'Add a ZIP code so we can show providers who cover your area.',
            action: 'Add ZIP code',
            onAction: () => editProfile(context, widget.controller),
          )
        else if (providers.isEmpty)
          const EmptyState(
            icon: Icons.search_off_outlined,
            title: 'No matches here yet',
            message:
                'Try another service or turn off mobile-only search. More participating providers can join over time.',
          )
        else ...[
          Text(
            '${providers.length} ${providers.length == 1 ? 'provider' : 'providers'} serving your area',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 14),
          for (final provider in providers)
            Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: ProviderCard(
                provider: provider,
                onRequest: () => requestProvider(
                  context,
                  widget.controller,
                  provider,
                  specialty: specialty,
                ),
              ),
            ),
        ],
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () => widget.controller.selectTab(2),
          icon: const Icon(Icons.support_agent_outlined),
          label: const Text('Let Estibot help me choose'),
        ),
      ],
    );
  }
}

class ProviderCard extends StatelessWidget {
  const ProviderCard({
    super.key,
    required this.provider,
    required this.onRequest,
  });
  final ProviderProfile provider;
  final VoidCallback onRequest;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFEDF3FB),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(
                  provider.kind == 'technician'
                      ? Icons.handyman_outlined
                      : Icons.storefront_outlined,
                  color: PlusColors.navy,
                ),
              ),
              const SizedBox(width: 13),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      provider.name,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      provider.city,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final service in provider.specialties)
                StatusPill(specialtyLabel(service)),
              if (provider.mobileService)
                const StatusPill('Mobile service', color: Color(0xFF08796D)),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            provider.description,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: provider.acceptingRequests ? onRequest : null,
              child: const Text('Request help'),
            ),
          ),
          if (provider.address.isNotEmpty)
            TextButton.icon(
              onPressed: () => openExternal(
                context,
                Uri.https('www.google.com', '/maps/search/', {
                  'api': '1',
                  'query': '${provider.name} ${provider.address}',
                }).toString(),
              ),
              icon: const Icon(Icons.map_outlined, size: 18),
              label: const Text('View on map'),
            ),
        ],
      ),
    ),
  );
}
