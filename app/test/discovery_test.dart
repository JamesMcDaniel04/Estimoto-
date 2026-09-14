import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/services.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/pending_request_store.dart';
import 'package:estimoto_plus/screens/estibot_screen.dart';
import 'package:estimoto_plus/screens/my_shops_screen.dart';
import 'package:estimoto_plus/widgets/discovery_results.dart';
import 'package:estimoto_plus/data/demo_seed.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/find_help_screen.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';

Json partner({
  String name = 'Nearby Dent and Collision Shop',
  String id = 'partner-plus-id',
}) => {
  'id': id,
  'source': 'estimoto',
  'source_id': 'original-source-id',
  'source_url': '',
  'name': name,
  'kind': 'shop',
  'city': 'Denver',
  'address': '1 Test Road, Denver, CO 80221',
  'phone': '+13035550100',
  'website': '',
  'accepting_requests': true,
  'specialties': ['pdr', 'collision'],
  'postal_codes': ['80221'],
  'mobile_service': false,
  'mobile_status': 'not_listed',
  'request_modes': ['shop_visit'],
  'distance_miles': 6.2,
  'description': 'Owner-described dent repairs.',
  'specialty_evidence': [
    {'specialty': 'pdr', 'basis': 'owner_declared'},
  ],
  'vehicle_match': {'status': 'not_verified'},
  'favorite': false,
};
Json independent() => {
  ...partner(name: 'Independent Audi Repair', id: 'osm:node:123'),
  'source': 'openstreetmap',
  'source_id': 'node:123',
  'source_url': 'https://www.openstreetmap.org/node/123',
  'website': 'https://independent.example.test',
  'accepting_requests': false,
  'request_modes': [],
  'vehicle_match': {'status': 'not_verified'},
  'specialty_evidence': [],
  'mobile_status': 'unknown',
};
Json envelope({
  List<Json>? providers,
  List<Json>? alternatives,
  String status = 'ready',
}) => {
  'postal_code': '80204',
  'radius_miles': 30,
  'distance_basis': 'zip_centroid',
  'providers': providers ?? [partner(), independent()],
  'shop_visit_alternatives': alternatives ?? [],
  'status': status,
  'exhaustive': false,
  'truncated': false,
  'checked_at': '2026-09-13T12:00:00Z',
  'message': 'Confirm services with the shop.',
  'source_attributions': [
    {
      'name': '© OpenStreetMap contributors',
      'url': 'https://www.openstreetmap.org/copyright',
      'license': 'ODbL-1.0',
    },
  ],
};

class DiscoveryRepository extends DemoPlusRepository {
  @override
  bool get isDemo => false;
  final calls = <Json>[];
  final responses = <Completer<Json>>[];
  bool delayed = false;
  Json response = envelope();
  List<Json> favorites = [];
  Json? savedFavorite, createdRequest;
  @override
  Future<PlusSnapshot> bootstrap() async {
    final data = demoSeed();
    (data['profile'] as Json)['postal_code'] = '80204';
    data['capabilities'] = {'live_discovery': true, 'live_requests': true};
    return PlusSnapshot.fromJson(data);
  }

  @override
  Future<Json> discoverProviders(Json query) async {
    calls.add(Map.of(query));
    if (delayed) {
      final c = Completer<Json>();
      responses.add(c);
      return c.future;
    }
    return jsonDecode(jsonEncode(response)) as Json;
  }

  @override
  Future<List<Json>> listDiscoveryFavorites(String vehicleId) async =>
      favorites;
  @override
  Future<Json> saveDiscoveryFavorite(String specialty, Json body) async {
    savedFavorite = {'specialty': specialty, ...body};
    favorites = [savedFavorite!];
    return savedFavorite!;
  }

  @override
  Future<void> deleteDiscoveryFavorite(
    String specialty,
    String vehicleId,
  ) async {
    favorites = [];
  }

  @override
  Future<Json> createRequest(Json body, String key) async {
    createdRequest = body;
    return {'id': 'new-request'};
  }
}

Future<PlusController> discoveryController(DiscoveryRepository repo) async {
  final c = PlusController(repo);
  await c.refresh();
  return c;
}

Future<void> mountDiscovery(
  WidgetTester tester,
  PlusController c, {
  double scale = 1,
  double width = 390,
}) async {
  tester.view.physicalSize = Size(width, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: plusTheme().copyWith(
        textTheme: plusTheme().textTheme.apply(fontFamily: 'Roboto'),
        filledButtonTheme: FilledButtonThemeData(
          style: plusTheme().filledButtonTheme.style!.copyWith(
            textStyle: const WidgetStatePropertyAll(
              TextStyle(
                fontFamily: 'Roboto',
                fontSize: 15,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ),
      ),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(scale)),
        child: RepaintBoundary(
          key: const Key('discovery-proof'),
          child: child!,
        ),
      ),
      home: Scaffold(body: FindHelpScreen(controller: c)),
    ),
  );
  await tester.pump();
}

Future<void> tapDiscovery(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> discoveryProof(WidgetTester tester, String name) async {
  const directory = String.fromEnvironment('DISCOVERY_CAPTURE_DIR');
  if (directory.isEmpty) return;
  final boundary = tester.renderObject<RenderRepaintBoundary>(
    find.byKey(const Key('discovery-proof')),
  );
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 1);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    await Directory(directory).create(recursive: true);
    await File(
      '$directory/$name.png',
    ).writeAsBytes(bytes!.buffer.asUint8List());
    image.dispose();
  });
}

class AssistantDiscoveryRepository extends DiscoveryRepository {
  final answer = Completer<AssistantAnswer>();
  @override
  Future<AssistantAnswer> askAssistant(Json body) => answer.future;
}

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));
  setUpAll(() async {
    const directory = String.fromEnvironment('DISCOVERY_FONT_DIR');
    if (directory.isEmpty) return;
    for (final pair in [
      ('Roboto', 'Roboto-Regular.ttf'),
      ('MaterialIcons', 'MaterialIcons-Regular.otf'),
    ]) {
      final font = FontLoader(pair.$1)
        ..addFont(
          Future.value(
            ByteData.sublistView(
              await File('$directory/${pair.$2}').readAsBytes(),
            ),
          ),
        );
      await font.load();
    }
  });
  testWidgets(
    'independent contact handoff opens a private editable shop review without sending',
    (tester) async {
      final repo = DiscoveryRepository()
        ..response = envelope(providers: [independent()]);
      final c = await discoveryController(repo);
      await mountDiscovery(tester, c);
      await tester.pumpAndSettle();
      await tapDiscovery(
        tester,
        find.text('Save contact for reviewed scheduling'),
      );
      expect(find.byType(ShopEditor), findsOneWidget);
      expect(
        tester
            .widget<TextFormField>(find.byKey(const Key('shop-name')))
            .controller!
            .text,
        'Independent Audi Repair',
      );
      expect(
        tester
            .widget<TextFormField>(find.byKey(const Key('shop-phone')))
            .controller!
            .text,
        '+13035550100',
      );
      expect(repo.createdRequest, isNull);
      expect(repo.savedFavorite, isNull);
    },
  );
  testWidgets(
    'owned saved shop can become the dedicated choice without provider bridge IDs',
    (tester) async {
      final repo = DiscoveryRepository();
      final c = await discoveryController(repo);
      final shop = await repo.saveMyShop({
        'name': 'My trusted shop',
        'email': '',
        'phone': '+13035550100',
        'address': 'Test address',
      });
      await tester.pumpWidget(MaterialApp(home: MyShopsScreen(controller: c)));
      await tester.pumpAndSettle();
      await tapDiscovery(
        tester,
        find.text('Dedicated shop for ${c.selectedVehicle!.title}'),
      );
      await tapDiscovery(tester, find.text('Save for: Maintenance'));
      expect(repo.savedFavorite, {
        'specialty': 'maintenance',
        'vehicle_id': c.selectedVehicle!.id,
        'source': 'my_shop',
        'source_id': shop['id'],
      });
      expect(repo.createdRequest, isNull);
    },
  );
  testWidgets(
    'changing the vehicle during a nearby provider review removes send controls',
    (tester) async {
      final repo = DiscoveryRepository()
        ..response = envelope(providers: [partner()]);
      final c = await discoveryController(repo);
      await mountDiscovery(tester, c);
      await tester.pumpAndSettle();
      await tapDiscovery(tester, find.text('Request help'));
      c.selectVehicle(c.snapshot!.vehicles.last.id);
      await tester.pumpAndSettle();
      expect(find.text('Your search changed'), findsOneWidget);
      expect(find.byKey(const Key('send-request')), findsNothing);
      expect(repo.createdRequest, isNull);
    },
  );
  testWidgets(
    'a merged independent favorite stays visible and removable on its participating result',
    (tester) async {
      final repo = DiscoveryRepository();
      final c = await discoveryController(repo);
      final reference = {
        'vehicle_id': c.selectedVehicle!.id,
        'specialty': 'pdr',
        'source': 'openstreetmap',
        'source_id': 'node:123',
      };
      repo.favorites = [reference];
      repo.response = envelope(
        providers: [
          {
            ...partner(),
            'favorite': true,
            'favorite_references': [reference],
          },
        ],
      );
      await mountDiscovery(tester, c);
      await tester.pumpAndSettle();
      expect(find.text('Request help'), findsOneWidget);
      expect(find.text('Your dedicated shop: PDR'), findsOneWidget);
      await tapDiscovery(tester, find.text('Change or remove saved choice'));
      await tapDiscovery(tester, find.text('Remove: PDR'));
      expect(repo.favorites, isEmpty);
      expect(repo.savedFavorite, isNull);
      expect(find.text('Your dedicated shop: PDR'), findsNothing);
      expect(find.text('Save as my dedicated shop'), findsOneWidget);
    },
  );
  testWidgets(
    'private favorite saves and removes the source reference without contacting a listing',
    (tester) async {
      final repo = DiscoveryRepository()
        ..response = envelope(providers: [independent()]);
      final c = await discoveryController(repo);
      await mountDiscovery(tester, c);
      await tester.pumpAndSettle();
      expect(find.text('Request help'), findsNothing);
      await tapDiscovery(tester, find.text('Save as my dedicated shop'));
      await tapDiscovery(tester, find.text('Save for: PDR'));
      expect(repo.savedFavorite, {
        'specialty': 'pdr',
        'vehicle_id': c.selectedVehicle!.id,
        'source': 'openstreetmap',
        'source_id': 'node:123',
      });
      expect(repo.createdRequest, isNull);
      expect(find.text('Your dedicated shop: PDR'), findsOneWidget);
      await tapDiscovery(tester, find.text('Change or remove saved choice'));
      await tapDiscovery(tester, find.text('Remove: PDR'));
      expect(repo.favorites, isEmpty);
    },
  );
  testWidgets(
    'vehicle change while a favorite review is open cannot save the old preference',
    (tester) async {
      final repo = DiscoveryRepository()
        ..response = envelope(providers: [independent()]);
      final c = await discoveryController(repo);
      await mountDiscovery(tester, c);
      await tester.pumpAndSettle();
      await tapDiscovery(tester, find.text('Save as my dedicated shop'));
      c.selectVehicle(c.snapshot!.vehicles.last.id);
      await tester.pumpAndSettle();
      expect(find.text('Save for: PDR'), findsNothing);
      await tapDiscovery(tester, find.text('Close'));
      expect(repo.savedFavorite, isNull);
    },
  );
  testWidgets(
    'new nearby shop request freezes shop_visit after explicit sharing on a narrow large-text phone',
    (tester) async {
      final repo = DiscoveryRepository()
        ..response = envelope(
          providers: [
            partner(
              name:
                  'A deliberately long nearby collision and dent repair shop name',
            ),
          ],
        );
      final c = await discoveryController(repo);
      await mountDiscovery(tester, c, scale: 1.8, width: 320);
      await tester.pumpAndSettle();
      await discoveryProof(tester, 'directory-320-large');
      await Scrollable.ensureVisible(
        tester.element(find.byType(DiscoveryProviderCard)),
        alignment: 0,
      );
      await tester.pumpAndSettle();
      await discoveryProof(tester, 'directory-card-320-large');
      await tapDiscovery(tester, find.text('Request help'));
      expect(find.text(serviceModeLabel('shop_visit')), findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('request-description')),
        'Please inspect the dent in my door.',
      );
      await tapDiscovery(tester, find.byKey(const Key('send-request')));
      expect(repo.createdRequest, isNull);
      await tapDiscovery(tester, find.byKey(const Key('share-contact')));
      await discoveryProof(tester, 'directory-review-320-large');
      await tapDiscovery(tester, find.byKey(const Key('send-request')));
      expect(repo.createdRequest?['service_mode'], 'shop_visit');
      expect(repo.createdRequest?['provider_id'], 'partner-plus-id');
      expect(repo.createdRequest?['vehicle_id'], c.selectedVehicle!.id);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('old uncertain request is retried without adding service_mode', (
    tester,
  ) async {
    final repo = DiscoveryRepository()
      ..response = envelope(providers: [partner()]);
    final c = await discoveryController(repo);
    final old = {
      'vehicle_id': c.selectedVehicle!.id,
      'provider_id': 'partner-plus-id',
      'specialty': 'pdr',
      'description': 'Saved dent repair request',
      'preferred_time': 'Next week',
      'share_contact': true,
    };
    c.pendingRequest = PendingRequest(
      body: old,
      key: 'old-stable-key',
      provider: ProviderProfile.fromJson(partner()),
    );
    await mountDiscovery(tester, c);
    await tester.pumpAndSettle();
    await tapDiscovery(tester, find.text('Request help'));
    expect(find.text('As previously submitted'), findsOneWidget);
    await tapDiscovery(tester, find.byKey(const Key('share-contact')));
    await tapDiscovery(tester, find.byKey(const Key('send-request')));
    expect(repo.createdRequest, old);
    expect(repo.createdRequest!.containsKey('service_mode'), isFalse);
  });
  testWidgets(
    'directory total cap includes alternatives and labels unavailable searches',
    (tester) async {
      final repo = DiscoveryRepository()
        ..response = envelope(
          status: 'unavailable',
          providers: [
            for (var i = 0; i < 99; i++)
              partner(name: 'Shop $i', id: 'shop-$i'),
          ],
          alternatives: [
            partner(name: 'Alternative 1'),
            partner(name: 'Alternative 2'),
          ],
        );
      repo.response['truncated'] = true;
      final c = await discoveryController(repo);
      await mountDiscovery(tester, c);
      await tester.pumpAndSettle();
      expect(find.byType(DiscoveryProviderCard), findsNWidgets(100));
      expect(find.text('Alternative 1'), findsOneWidget);
      expect(find.text('Alternative 2'), findsNothing);
      expect(
        find.textContaining('Live directory search is unavailable'),
        findsOneWidget,
      );
      expect(find.textContaining('100 listings total'), findsOneWidget);
    },
  );
  testWidgets(
    'Estibot cards retain the searched vehicle and hide after a vehicle change',
    (tester) async {
      final repo = AssistantDiscoveryRepository();
      final c = await discoveryController(repo);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ListenableBuilder(
              listenable: c,
              builder: (_, _) => EstibotScreen(controller: c),
            ),
          ),
        ),
      );
      final pending = c.ask('Find mobile dent repair');
      repo.answer.complete(
        AssistantAnswer.fromJson({
          'reply': 'Consider a shop visit.',
          'intent': 'find_provider',
          'specialty': 'pdr',
          'providers': [partner()],
          'discovery': envelope(providers: []),
        }),
      );
      await pending;
      await tester.pumpAndSettle();
      expect(find.text('Nearby shops you can visit'), findsOneWidget);
      expect(find.text('Nearby Dent and Collision Shop'), findsOneWidget);
      c.selectVehicle(c.snapshot!.vehicles.last.id);
      await tester.pumpAndSettle();
      expect(find.text('Nearby Dent and Collision Shop'), findsNothing);
      expect(
        find.textContaining('Search again for current shop options'),
        findsOneWidget,
      );
    },
  );
  test(
    'assistant response arriving after a vehicle change is replaced with a fresh-search prompt',
    () async {
      final repo = AssistantDiscoveryRepository();
      final c = await discoveryController(repo);
      final pending = c.ask('Find nearby shops');
      c.selectVehicle(c.snapshot!.vehicles.last.id);
      repo.answer.complete(
        AssistantAnswer.fromJson({
          'reply': 'Obsolete results',
          'providers': [partner()],
        }),
      );
      await pending;
      expect(c.messages.last.text, contains('changed while I was checking'));
      expect(c.messages.last.answer!.providers, isEmpty);
    },
  );
  testWidgets(
    'late account-invalidated discovery and assistant replies never become actionable',
    (tester) async {
      final repo = AssistantDiscoveryRepository()..delayed = true;
      final c = await discoveryController(repo);
      await mountDiscovery(tester, c);
      final pending = c.ask('Find a repair shop');
      c.invalidateSession();
      repo.responses.single.complete(envelope());
      repo.answer.complete(
        AssistantAnswer.fromJson({
          'reply': 'Private old reply',
          'providers': [partner()],
        }),
      );
      await pending;
      await tester.pumpAndSettle();
      expect(find.text('Nearby Dent and Collision Shop'), findsNothing);
      expect(c.messages.any((e) => e.text == 'Private old reply'), isFalse);
    },
  );

  test(
    'discovery and private favorites use exact query paths and provenance',
    () async {
      final rows = <Json>[];
      final dynamic repo = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () async => 'owner',
        client: MockClient((r) async {
          rows.add({
            'method': r.method,
            'path': r.url.path,
            'query': r.url.queryParameters,
            'body': r.body.isEmpty ? null : jsonDecode(r.body),
          });
          expect(r.headers['Authorization'], 'Bearer owner');
          return http.Response(
            r.url.path.endsWith('/favorites') ? '[]' : '{}',
            200,
          );
        }),
      );
      await repo.discoverProviders({
        'postal_code': '80204',
        'vehicle_id': 'vehicle',
        'specialty': 'pdr',
        'mobile_only': true,
      });
      await repo.listDiscoveryFavorites('vehicle');
      await repo.saveDiscoveryFavorite('pdr', {
        'vehicle_id': 'vehicle',
        'source': 'openstreetmap',
        'source_id': 'node:123',
      });
      await repo.deleteDiscoveryFavorite('pdr', 'vehicle');
      expect(rows, [
        {
          'method': 'GET',
          'path': '/v1/discovery',
          'query': {
            'postal_code': '80204',
            'radius_miles': '30',
            'vehicle_id': 'vehicle',
            'specialty': 'pdr',
            'mobile_only': 'true',
          },
          'body': null,
        },
        {
          'method': 'GET',
          'path': '/v1/discovery/favorites',
          'query': {'vehicle_id': 'vehicle'},
          'body': null,
        },
        {
          'method': 'PUT',
          'path': '/v1/discovery/favorites/pdr',
          'query': {},
          'body': {
            'vehicle_id': 'vehicle',
            'source': 'openstreetmap',
            'source_id': 'node:123',
          },
        },
        {
          'method': 'DELETE',
          'path': '/v1/discovery/favorites/pdr',
          'query': {'vehicle_id': 'vehicle'},
          'body': null,
        },
      ]);
    },
  );
  testWidgets(
    'nearby partner outside exact ZIP appears with independent provenance',
    (tester) async {
      final repo = DiscoveryRepository();
      final owner = await discoveryController(repo);
      await mountDiscovery(tester, owner);
      await tester.pumpAndSettle();
      expect(find.text('Nearby Dent and Collision Shop'), findsOneWidget);
      expect(find.textContaining('6.2 mi'), findsWidgets);
      await tapDiscovery(tester, find.text('About these results'));
      expect(find.textContaining('not driving distance'), findsWidgets);
      expect(find.text('Independent Audi Repair'), findsOneWidget);
      expect(find.textContaining('Listed support for Audi'), findsNothing);
      expect(repo.calls.single['vehicle_id'], owner.selectedVehicle!.id);
      expect(find.text('Request help'), findsOneWidget);
      await Scrollable.ensureVisible(
        tester.element(find.byType(DiscoveryProviderCard).first),
        alignment: 0,
      );
      await tester.pumpAndSettle();
      await discoveryProof(tester, 'directory-card-390');
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('mobile empty results label shop visits as alternatives', (
    tester,
  ) async {
    final repo = DiscoveryRepository()
      ..response = envelope(providers: [], alternatives: [partner()]);
    final c = await discoveryController(repo);
    await mountDiscovery(tester, c);
    await tester.pumpAndSettle();
    await tapDiscovery(tester, find.text('Come to me'));
    expect(find.text('Nearby shops you can visit'), findsOneWidget);
    expect(
      find.textContaining('No mobile provider lists coverage'),
      findsOneWidget,
    );
    expect(find.textContaining('Mobile coverage confirmed'), findsNothing);
  });
  testWidgets('late old vehicle results cannot replace the current search', (
    tester,
  ) async {
    final repo = DiscoveryRepository()..delayed = true;
    final c = await discoveryController(repo);
    await mountDiscovery(tester, c);
    c.selectVehicle(c.snapshot!.vehicles.last.id);
    await tester.pump();
    repo.responses.last.complete(
      envelope(providers: [partner(name: 'Current vehicle shop')]),
    );
    await tester.pumpAndSettle();
    repo.responses.first.complete(
      envelope(providers: [partner(name: 'Old vehicle shop')]),
    );
    await tester.pumpAndSettle();
    expect(find.text('Current vehicle shop'), findsOneWidget);
    expect(find.text('Old vehicle shop'), findsNothing);
  });
}
