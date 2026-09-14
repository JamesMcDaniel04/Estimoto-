import 'package:flutter/material.dart';
import '../domain/models.dart';
import 'common.dart';

class GooglePlacesAttribution extends StatelessWidget {
  const GooglePlacesAttribution(this.provider, {super.key});
  final ProviderProfile provider;

  @override
  Widget build(BuildContext context) {
    if (provider.source != 'google_places') return const SizedBox.shrink();
    return Wrap(
      spacing: 8,
      children: [
        TextButton(
          onPressed: () =>
              openExternal(context, textOf(provider.json, 'source_url')),
          child: const Text(
            'Google Maps',
            softWrap: false,
            style: TextStyle(fontWeight: FontWeight.w400),
          ),
        ),
        for (final source in rowsOf(
          provider.json,
          'source_attributions',
        ).where((s) => s['name'] != 'Google Maps').take(5))
          TextButton(
            onPressed: () => openExternal(context, textOf(source, 'url')),
            child: Text(textOf(source, 'name')),
          ),
      ],
    );
  }
}
