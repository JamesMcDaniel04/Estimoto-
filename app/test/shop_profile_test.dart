import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/theme.dart';
import 'package:estimoto_plus/widgets/discovery_results.dart';
import 'package:estimoto_plus/widgets/shop_profile.dart';

ProviderProfile profile() => ProviderProfile.fromJson({
  'source': 'openstreetmap',
  'source_id': 'node:42',
  'id': 'osm:node:42',
  'name': 'Verified repair & maintenance shop',
  'address': 'Old abbreviated street',
  'phone': '+13035550142',
  'website': 'https://shop.example/branch?location=42',
  'specialties': ['maintenance', 'mechanical'],
  'distance_miles': 4.2,
  'description': 'Brake repairs and scheduled maintenance.',
  'service_details': ['Brake repairs', 'Oil changes'],
  'verification': {
    'status': 'contact_confirmed',
    'checked_at': '2026-09-13',
    'address': '42 Confirmed Street, Denver CO 80204',
    'source_url': 'https://shop.example/contact',
  },
});

void main() {
  testWidgets(
    'directory card shows verified address when map address is empty',
    (tester) async {
      final provider = ProviderProfile.fromJson({
        ...profile().json,
        'address': '',
      });
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: DiscoveryProviderCard(provider: provider),
            ),
          ),
        ),
      );
      expect(find.text('42 Confirmed Street, Denver CO 80204'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'maps link uses public verified business location and correct URI escaping',
    () {
      final uri = shopMapsUri(profile());
      expect(uri.host, 'www.google.com');
      expect(
        uri.queryParameters['query'],
        'Verified repair & maintenance shop 42 Confirmed Street, Denver CO 80204',
      );
      expect(uri.queryParameters.keys, unorderedEquals(['api', 'query']));
    },
  );

  testWidgets(
    'tapping card padding opens its profile without contacting the shop',
    (tester) async {
      final launches = <String>[];
      const channel = MethodChannel('plugins.flutter.io/url_launcher');
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
        call,
      ) async {
        if (call.method == 'launch') {
          launches.add(call.arguments['url'] as String);
        }
        return true;
      });
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          channel,
          null,
        ),
      );
      var saved = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: DiscoveryProviderCard(
                provider: profile(),
                onSave: () => saved = true,
              ),
            ),
          ),
        ),
      );
      final card = find.byKey(ValueKey('shop-card-${profile().id}'));
      await tester.tapAt(tester.getTopLeft(card) + const Offset(8, 8));
      await tester.pumpAndSettle();
      expect(find.byType(ShopProfile), findsOneWidget);
      expect(launches, isEmpty);
      expect(saved, isFalse);
      await tester.ensureVisible(find.text('Call shop'));
      await tester.tap(find.text('Call shop'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Website'));
      await tester.tap(find.text('Website'));
      await tester.pumpAndSettle();
      expect(launches, [
        'tel:+13035550142',
        'https://shop.example/branch?location=42',
      ]);
      expect(find.byType(ShopProfile), findsOneWidget);
      await tester.ensureVisible(find.text('Save as my dedicated shop'));
      await tester.tap(find.text('Save as my dedicated shop'));
      await tester.pumpAndSettle();
      expect(saved, isTrue);
      expect(find.byType(ShopProfile), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'network request badge acts directly while card taps still open the profile',
    (tester) async {
      final network = ProviderProfile.fromJson({
        ...profile().json,
        'source': 'estimoto',
        'id': 'network-shop',
        'accepting_requests': true,
        'request_modes': ['shop_visit'],
      });
      var requests = 0;
      Future<void> mountProvider(ProviderProfile provider) => tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: DiscoveryProviderCard(
                provider: provider,
                onRequest: () => requests++,
              ),
            ),
          ),
        ),
      );
      await mountProvider(network);
      final badge = find.byKey(const ValueKey('shop-request-network-shop'));
      expect(badge, findsOneWidget);
      await tester.ensureVisible(badge);
      await tester.tap(badge);
      await tester.pumpAndSettle();
      expect(requests, 1);
      expect(find.byType(ShopProfile), findsNothing);
      await tester.tap(find.text(network.name));
      await tester.pumpAndSettle();
      expect(find.byType(ShopProfile), findsOneWidget);
      expect(requests, 1);
      await tester.tap(find.byTooltip('Close shop profile'));
      await tester.pumpAndSettle();
      await mountProvider(profile());
      expect(find.text('Request help'), findsNothing);
      await mountProvider(
        ProviderProfile.fromJson({
          ...network.json,
          'accepting_requests': false,
        }),
      );
      expect(find.text('Request help'), findsNothing);
      expect(requests, 1);
      expect(tester.takeException(), isNull);
    },
  );

  for (final scale in [1.0, 2.0]) {
    testWidgets(
      'profile opens from directory and fits 320px at text scale $scale',
      (tester) async {
        tester.view.physicalSize = const Size(320, 780);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: plusTheme(),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: TextScaler.linear(scale)),
              child: child!,
            ),
            home: Scaffold(
              body: SingleChildScrollView(
                child: DiscoveryProviderCard(provider: profile()),
              ),
            ),
          ),
        );
        expect(find.text('Call'), findsNothing);
        expect(find.text('Website'), findsNothing);
        expect(find.text('View shop profile'), findsNothing);
        await tester.ensureVisible(find.text(profile().name));
        await tester.tap(find.text(profile().name));
        await tester.pumpAndSettle();
        expect(find.byType(ShopProfile), findsOneWidget);
        await tester.ensureVisible(find.text('Google Maps & reviews'));
        expect(find.text('Call shop'), findsOneWidget);
        expect(find.text('+13035550142'), findsOneWidget);
        await tester.ensureVisible(find.text('Official business source'));
        expect(
          find.textContaining(
            'Location, repair services, website and phone checked',
          ),
          findsOneWidget,
        );
        expect(find.textContaining('5.0'), findsNothing);
        expect(tester.takeException(), isNull);
        await tester.ensureVisible(find.byTooltip('Close shop profile'));
        await tester.tap(find.byTooltip('Close shop profile'));
        await tester.pumpAndSettle();
        expect(find.byType(ShopProfile), findsNothing);
      },
    );
  }
}
