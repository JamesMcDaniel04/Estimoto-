import 'dart:convert';
import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/data/pending_request_store.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/estimate_forms.dart';
import 'package:estimoto_plus/services/estimate_capture.dart';
import 'package:estimoto_plus/services/estimate_capture_steps.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';
import 'package:estimoto_plus/widgets/common.dart';
import 'package:estimoto_plus/widgets/private_estimate_photo.dart';
import 'package:estimoto_plus/widgets/estimate_submission_review.dart';

final _pixel = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
);

class _Picker implements EstimatePhotoPicker {
  @override
  Future<XFile?> pick(ImageSource source) async =>
      XFile('/private/test-photo.png');
  @override
  Future<XFile?> recover() async => null;
}

class _RecoveryFailurePicker extends _Picker {
  @override
  Future<XFile?> recover() async =>
      throw const PlusApiException('Camera recovery unavailable');
}

class _Repository extends DemoPlusRepository {
  _Repository({String discipline = 'pdr', bool complete = false}) {
    data = {
      'profile': {
        'id': 'customer-1',
        'name': 'Alex Example',
        'email': 'alex@example.test',
        'phone': '3035550100',
        'postal_code': '80202',
      },
      'vehicles': [
        {'id': 'vehicle-1', 'year': 2021, 'make': 'Toyota', 'model': 'Tacoma'},
      ],
      'providers': [
        {
          'id': 'shop-1',
          'name': 'Long Named Local Collision and Dent Repair Shop',
          'kind': 'shop',
          'public_visible': true,
          'accepting_requests': true,
          'specialties': ['pdr', 'collision'],
          'postal_codes': ['80221'],
          'city': 'Denver',
        },
        {
          'id': 'private-shop',
          'name': 'Private shop',
          'kind': 'shop',
          'public_visible': false,
          'accepting_requests': true,
          'specialties': ['pdr', 'collision'],
          'postal_codes': ['80202'],
        },
        {
          'id': 'wrong-zip',
          'name': 'Outside your area',
          'kind': 'shop',
          'accepting_requests': true,
          'specialties': ['pdr', 'collision'],
          'postal_codes': ['99999'],
        },
        {
          'id': 'technician',
          'name': 'Mobile technician',
          'kind': 'technician',
          'accepting_requests': true,
          'specialties': ['pdr', 'collision'],
          'postal_codes': ['80202'],
        },
      ],
      'estimates': [
        <String, dynamic>{
          'id': 'estimate-1',
          'vehicle_id': 'vehicle-1',
          'discipline': discipline,
          'status': 'draft',
          'description': 'Dent behind the front door handle.',
          'photos': [
            if (complete)
              for (final key in [
                ...requiredEstimateViews,
                if (discipline == 'pdr') 'panel_front_door_left',
              ])
                {'id': 'photo-$key', 'label': key},
          ],
        },
      ],
      'capabilities': {
        'live_estimates': true,
        'required_estimate_photo_keys': requiredEstimateViews,
        'pdr_damage_panel_types': pdrDamagePanels,
      },
    };
  }
  late Json data;
  final discoveryQueries = <Json>[];
  @override
  Future<Json> discoverProviders(Json query) async {
    discoveryQueries.add(Map.of(query));
    return super.discoverProviders(query);
  }

  final uploads = <String>[];
  final sends = <Json>[];
  int photoReads = 0;
  Json get estimate => (data['estimates'] as List).first as Json;
  @override
  bool get isDemo => false;
  @override
  Future<PlusSnapshot> bootstrap() async =>
      PlusSnapshot.fromJson(jsonDecode(jsonEncode(data)) as Json);
  @override
  Future<Json> uploadPhoto(
    String estimateId,
    Uint8List bytes,
    String filename,
    String label,
  ) async {
    expect(estimateId, 'estimate-1');
    uploads.add(label);
    final photo = {'id': 'photo-${uploads.length}', 'label': label};
    (estimate['photos'] as List).add(photo);
    return photo;
  }

  @override
  Future<Uint8List> getPhoto(String estimateId, String photoId) async {
    expect(estimateId, 'estimate-1');
    photoReads++;
    return _pixel;
  }

  @override
  Future<Json> submitEstimate(
    String id,
    Json body,
    String idempotencyKey,
  ) async {
    sends.add({...body, 'key': idempotencyKey});
    estimate.addAll({
      'status': 'submitted',
      'delivery_status': 'queued',
      'processing_state': 'pending',
      'amount_cents': null,
    });
    return estimate;
  }
}

class _DelayedPhotoRepository extends _Repository {
  final pendingPhoto = Completer<Uint8List>();
  @override
  Future<Uint8List> getPhoto(String estimateId, String photoId) =>
      pendingPhoto.future;
}

Future<PlusController> _mount(
  WidgetTester tester,
  _Repository repository, {
  double scale = 1.8,
  bool reviewOnly = false,
  VoidCallback? onEditProfile,
  EstimateCaptureService? captureService,
}) async {
  tester.view.physicalSize = const Size(320, 740);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final controller = PlusController(repository);
  await controller.refresh();
  await tester.pumpWidget(
    MaterialApp(
      theme: plusTheme(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(scale)),
        child: child!,
      ),
      home: reviewOnly
          ? Scaffold(
              body: EstimateSubmissionReview(
                controller: controller,
                estimate: controller.snapshot!.estimates.single,
                onEditProfile: onEditProfile ?? () {},
              ),
            )
          : EstimateDetailScreen(
              controller: controller,
              estimateId: 'estimate-1',
              captureService:
                  captureService ??
                  EstimateCaptureService(
                    store: MemoryEstimateCaptureStore(),
                    picker: _Picker(),
                    readBytes: (_) async => _pixel,
                  ),
            ),
    ),
  );
  await tester.pumpAndSettle();
  return controller;
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'legacy uncertain estimate retry preserves its exact body without service_mode or discovery admission',
    (tester) async {
      final repo = _Repository(complete: true);
      final c = PlusController(repo);
      final old = {'provider_id': 'shop-1', 'share_contact': true};
      await c.pendingStore.write(
        'estimate:customer-1:estimate-1',
        PendingRequest(
          body: old,
          key: 'estimate:estimate-1',
          provider: ProviderProfile.fromJson(
            (repo.data['providers'] as List).first as Json,
          ),
        ),
      );
      await c.refresh();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () => showModalBottomSheet<void>(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => EstimateSubmissionReview(
                    controller: c,
                    estimate: c.snapshot!.estimates.single,
                    onEditProfile: () {},
                  ),
                ),
                child: const Text('Open review'),
              ),
            ),
          ),
        ),
      );
      await _tap(tester, find.text('Open review'));
      expect(repo.discoveryQueries, isEmpty);
      await _tap(tester, find.byKey(const Key('estimate-share-contact')));
      await _tap(tester, find.byKey(const Key('estimate-send')));
      expect(repo.sends.single, {...old, 'key': 'estimate:estimate-1'});
      expect(repo.sends.single.containsKey('service_mode'), isFalse);
    },
  );

  testWidgets(
    'completed guided PDR photos still require a shop choice and explicit contact consent',
    (tester) async {
      final repository = _Repository(complete: true);
      final controller = await _mount(tester, repository);
      expect(find.byKey(const Key('open-guided-capture')), findsOneWidget);
      expect(find.byKey(const Key('capture-camera')), findsNothing);
      expect(repository.sends, isEmpty);
      await _tap(tester, find.byKey(const Key('estimate-review')));
      expect(repository.discoveryQueries.single['vehicle_id'], 'vehicle-1');
      expect(repository.discoveryQueries.single['specialty'], 'pdr');
      expect(find.byType(TextField), findsNothing);
      expect(find.text('alex@example.test'), findsOneWidget);
      expect(find.text('Private shop'), findsNothing);
      expect(find.text('Outside your area'), findsNothing);
      expect(find.text('Mobile technician'), findsNothing);
      await _tap(tester, find.byKey(const Key('estimate-provider-shop-1')));
      await _tap(tester, find.byKey(const Key('estimate-send')));
      expect(repository.sends, isEmpty);
      expect(
        find.textContaining('Choose to share your saved details'),
        findsOneWidget,
      );
      await _tap(tester, find.byKey(const Key('estimate-share-contact')));
      await _tap(tester, find.byKey(const Key('estimate-send')));
      expect(repository.sends.single, {
        'provider_id': 'shop-1',
        'share_contact': true,
        'service_mode': 'shop_visit',
        'key': 'estimate:estimate-1',
      });
      expect(controller.snapshot!.estimates.single.amountCents, isNull);
      expect(find.text('Waiting to send to the shop'), findsOneWidget);
      expect(find.text('No price has been quoted yet.'), findsOneWidget);
      expect(repository.photoReads, greaterThan(0));
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'missing contact opens the Garage profile path without duplicating personal-data fields',
    (tester) async {
      final repository = _Repository(complete: true);
      (repository.data['profile'] as Json)['phone'] = '';
      var edit = false;
      await _mount(
        tester,
        repository,
        reviewOnly: true,
        onEditProfile: () => edit = true,
      );
      expect(find.byType(TextField), findsNothing);
      expect(
        tester
            .widget<BusyButton>(find.byKey(const Key('estimate-send')))
            .onPressed,
        isNull,
      );
      await _tap(tester, find.byKey(const Key('estimate-edit-profile')));
      expect(edit, isTrue);
      expect(repository.sends, isEmpty);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('documentary views alone cannot submit PDR', (tester) async {
    final repository = _Repository(complete: true);
    (repository.estimate['photos'] as List).removeLast();
    await _mount(tester, repository, reviewOnly: true);
    expect(
      tester
          .widget<BusyButton>(find.byKey(const Key('estimate-send')))
          .onPressed,
      isNull,
    );
    expect(repository.sends, isEmpty);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'failed delivery and completed processing do not imply an available price',
    (tester) async {
      final repository = _Repository(complete: true, discipline: 'collision');
      repository.estimate.addAll({
        'status': 'submitted',
        'delivery_status': 'failed',
        'processing_state': 'complete',
        'amount_cents': null,
      });
      await _mount(tester, repository);
      expect(find.text('Delivery to the shop failed'), findsOneWidget);
      expect(
        find.text(
          'Photo processing is complete. A price is not available yet.',
        ),
        findsOneWidget,
      );
      expect(find.text('Your estimate is ready to review.'), findsNothing);
      expect(find.text('No price has been quoted yet.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'a recovery error keeps an explicit retake path for the original view',
    (tester) async {
      final store = MemoryEstimateCaptureStore()
        ..value = const PendingEstimateCapture(
          id: 'interrupted',
          customerId: 'customer-1',
          estimateId: 'estimate-1',
          captureKey: 'engine_bay',
        );
      await _mount(
        tester,
        _Repository(),
        captureService: EstimateCaptureService(
          store: store,
          picker: _RecoveryFailurePicker(),
        ),
      );
      expect(
        find.text(
          'The camera did not finish this view. Retake it to continue.',
        ),
        findsOneWidget,
      );
      await _tap(tester, find.text('Retake this view'));
      expect(store.value, isNull);
      expect(find.byKey(const Key('open-guided-capture')), findsOneWidget);
      expect(find.byKey(const Key('capture-camera')), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'another account unfinished capture offers a private explicit discard path',
    (tester) async {
      final store = MemoryEstimateCaptureStore()
        ..value = const PendingEstimateCapture(
          id: 'other',
          customerId: 'secret-owner',
          estimateId: 'secret-estimate',
          captureKey: 'engine_bay',
          localPath: '/private/secret-photo.jpg',
        );
      await _mount(
        tester,
        _Repository(),
        captureService: EstimateCaptureService(
          store: store,
          picker: _Picker(),
          readBytes: (_) async => _pixel,
        ),
      );
      expect(find.byKey(const Key('capture-camera')), findsNothing);
      expect(find.textContaining('secret'), findsNothing);
      await _tap(tester, find.byKey(const Key('discard-other-capture')));
      expect(store.value, isNull);
      expect(find.byKey(const Key('open-guided-capture')), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'detail review returns to Garage and opens the existing profile editor',
    (tester) async {
      final repository = _Repository(complete: true);
      (repository.data['profile'] as Json)['phone'] = '';
      final controller = await _mount(tester, repository);
      await _tap(tester, find.byKey(const Key('estimate-review')));
      await _tap(tester, find.byKey(const Key('estimate-edit-profile')));
      expect(controller.tab, 0);
      expect(find.text('Your profile'), findsOneWidget);
      expect(find.widgetWithText(TextFormField, 'Name'), findsOneWidget);
      expect(repository.sends, isEmpty);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('late private photo bytes stay hidden after a sign-in change', (
    tester,
  ) async {
    final repository = _DelayedPhotoRepository();
    final controller = PlusController(repository);
    await controller.refresh();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 120,
            height: 100,
            child: PrivateEstimatePhoto(
              controller: controller,
              customerId: 'customer-1',
              estimateId: 'estimate-1',
              photoId: 'photo-1',
              label: 'Odometer',
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    controller.invalidateSession();
    repository.pendingPhoto.complete(_pixel);
    await tester.pumpAndSettle();
    expect(find.byType(Image), findsNothing);
    expect(find.byTooltip('Reload Odometer photo'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
