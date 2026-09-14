import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../domain/models.dart';
import '../theme.dart';
import 'common.dart';
import 'shop_media.dart';

Uri shopMapsUri(ProviderProfile provider) => Uri.https(
  'www.google.com',
  '/maps/search/',
  {'api': '1', 'query': '${provider.name} ${provider.displayAddress}'},
);

Future<void> showShopProfile(BuildContext context, ProviderProfile provider) =>
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      useSafeArea: true,
      builder: (_) => FractionallySizedBox(
        heightFactor: .9,
        child: ShopProfile(provider: provider),
      ),
    );

class ShopProfile extends StatelessWidget {
  const ShopProfile({super.key, required this.provider});
  final ProviderProfile provider;

  Future<void> open(BuildContext context, Uri uri) async {
    try {
      if (await launchUrl(uri, mode: LaunchMode.externalApplication)) return;
    } catch (_) {}
    if (context.mounted) {
      showMessage(context, 'Could not open this contact option.');
    }
  }

  @override
  Widget build(BuildContext context) {
    final verification = provider.json['verification'] as Map? ?? {};
    final confirmed = verification['status'] == 'contact_confirmed';
    final phone = provider.phone.replaceAll(RegExp(r'[^+\d]'), '');
    final website = Uri.tryParse(textOf(provider.json, 'website'));
    final media = provider.media;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 30),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Align(
            alignment: Alignment.centerRight,
            child: IconButton(
              tooltip: 'Close shop profile',
              onPressed: () => Navigator.pop(context),
              icon: const Icon(Icons.close),
            ),
          ),
          ShopMediaThumbnail(provider: provider, size: 120),
          const SizedBox(height: 20),
          Text(
            provider.name,
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 8),
          Text(
            provider.independent
                ? 'Independent repair shop'
                : 'Participating Estimoto provider',
          ),
          if (confirmed) ...[
            const SizedBox(height: 12),
            const StatusPill(
              'Business contact details checked',
              color: PlusColors.navy,
            ),
          ],
          const SizedBox(height: 20),
          Text(confirmed ? '${verification['address']}' : provider.address),
          if (provider.distanceMiles != null) ...[
            const SizedBox(height: 6),
            Text(
              'About ${provider.distanceMiles!.toStringAsFixed(1)} mi from your ZIP center',
            ),
          ],
          if (provider.phone.isNotEmpty) ...[
            const SizedBox(height: 8),
            SelectableText(provider.phone),
            if (provider.json['phone_kind'] == 'national_customer_service')
              const Text('National customer service'),
          ],
          const SizedBox(height: 16),
          Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              if (RegExp(r'^\+?\d{7,15}$').hasMatch(phone))
                FilledButton.icon(
                  onPressed: () =>
                      open(context, Uri(scheme: 'tel', path: phone)),
                  icon: const Icon(Icons.phone_outlined),
                  label: const Text('Call shop'),
                ),
              if (website != null &&
                  const ['https', 'http'].contains(website.scheme) &&
                  website.host.isNotEmpty &&
                  website.userInfo.isEmpty)
                OutlinedButton.icon(
                  onPressed: () => open(context, website),
                  icon: const Icon(Icons.language),
                  label: const Text('Website'),
                ),
              OutlinedButton.icon(
                onPressed: () => open(context, shopMapsUri(provider)),
                icon: const Icon(Icons.map_outlined),
                label: const Text('Google Maps & reviews'),
              ),
            ],
          ),
          const SectionHeading('Services'),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final service in provider.specialties)
                StatusPill(specialtyLabel(service)),
            ],
          ),
          if (provider.description.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(provider.description),
          ],
          if (provider.json['service_details'] is List) ...[
            const SizedBox(height: 12),
            for (final service
                in (provider.json['service_details'] as List)
                    .whereType<String>())
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('• $service'),
              ),
          ],
          const SizedBox(height: 16),
          Text(
            provider.independent
                ? 'Call the shop to confirm services, pricing and appointment availability.'
                : 'Request help from the shop card. The provider will confirm your appointment.',
          ),
          if (confirmed) ...[
            const SectionHeading('Business information'),
            Text(
              'Location, repair services, website and phone checked ${dateText('${verification['checked_at']}')}. This confirms the business details, not the quality of its work.',
            ),
            TextButton(
              onPressed: () =>
                  openExternal(context, '${verification['source_url']}'),
              child: const Text('Official business source'),
            ),
          ],
          if (textOf(provider.json, 'source_url').isNotEmpty)
            TextButton(
              onPressed: () =>
                  openExternal(context, textOf(provider.json, 'source_url')),
              child: const Text('Map listing source'),
            ),
          if (media != null) ShopMediaCredit(media: media),
        ],
      ),
    );
  }
}
