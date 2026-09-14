import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/widgets/discovery_results.dart';
import 'package:estimoto_plus/widgets/shop_profile.dart';

ProviderProfile googleShop() => ProviderProfile.fromJson({
  'id': 'google:city-repair',
  'source': 'google_places',
  'source_id': 'city-repair',
  'name': 'City Auto Repair',
  'kind': 'shop',
  'source_url':
      'https://www.google.com/maps/search/?api=1&query_place_id=city-repair&query=City+Auto+Repair',
  'address': '123 W 30th St, New York, NY 10001',
  'phone': '+12125550100',
  'website': 'https://repair.example/',
  'specialties': ['mechanical'],
  'request_modes': [],
  'accepting_requests': false,
  'vehicle_match': {
    'status': 'search_relevance',
    'basis': 'google_places_query',
    'make': 'Toyota',
  },
  'source_attributions': [
    {'name': 'Google Maps', 'url': 'https://maps.google.com/'},
    {'name': 'Directory contributor', 'url': 'https://contributor.example/'},
  ],
});

void main() {
  test('Google Maps deep link identifies the exact shop', () {
    final uri = shopMapsUri(googleShop());
    expect(uri.queryParameters['query_place_id'], 'city-repair');
    expect(uri.host, 'www.google.com');
  });

  testWidgets(
    'Google suggestions are attributed and never claim documented make support',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: DiscoveryProviderCard(
                provider: googleShop(),
                vehicleMake: 'Toyota',
              ),
            ),
          ),
        ),
      );
      expect(
        find.text('Suggested for your Toyota · confirm services with the shop'),
        findsOneWidget,
      );
      expect(find.textContaining('Listed support'), findsNothing);
      expect(find.text('Google Maps'), findsOneWidget);
      expect(find.text('Directory contributor'), findsOneWidget);
      expect(find.text('Independent listing · OpenStreetMap'), findsNothing);
      expect(find.text('Request help'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Google profile retains contact actions and ID favorite without copying content',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ShopProfile(
              provider: googleShop(),
              canSave: true,
              canSaveContact: true,
            ),
          ),
        ),
      );
      expect(find.text('Google Maps'), findsOneWidget);
      expect(find.text('Call shop'), findsOneWidget);
      expect(find.text('Website'), findsOneWidget);
      expect(find.text('Save as my dedicated shop'), findsOneWidget);
      expect(find.text('Save contact for reviewed scheduling'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
