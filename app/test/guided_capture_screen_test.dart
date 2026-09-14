import 'dart:async';
import 'dart:io';
import 'package:estimoto_plus/domain/models.dart';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/screens/guided_capture_screen.dart';
import 'package:estimoto_plus/screens/estimate_forms.dart';
import 'package:estimoto_plus/services/estimate_capture.dart';
import 'package:estimoto_plus/services/estimate_capture_steps.dart';
import 'package:estimoto_plus/services/guided_capture_pending.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';
import 'guided_capture_session_test.dart' as fake;

class LiveCaptureRepository extends fake.CaptureRepositoryFake {
  @override
  Future<PlusSnapshot> bootstrap() async {
    final snapshot = await super.bootstrap();
    snapshot.capabilities.json['demo'] = false;
    return snapshot;
  }

  @override
  bool get isDemo => false;
}

class DelayedStore extends MemoryGuidedCapturePendingStore {
  final loaded = Completer<void>();
  @override
  Future<GuidedCapturePending?> read(String ownerId) async {
    await loaded.future;
    return super.read(ownerId);
  }
}

Future<void> tap(WidgetTester tester, String label) async {
  await tester.ensureVisible(find.text(label));
  await tester.tap(find.text(label));
  await tester.pumpAndSettle();
}

final boundary = GlobalKey();
Future<void> screenshot(WidgetTester tester, String name) async {
  if (Platform.environment['CAPTURE_SCREENSHOTS'] != '1') return;
  await tester.runAsync(() async {
    final render =
        boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
    final image = await render.toImage();
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    await Directory('/tmp/plus-guided-ui').create(recursive: true);
    await File(
      '/tmp/plus-guided-ui/$name.png',
    ).writeAsBytes(data!.buffer.asUint8List());
    image.dispose();
  });
}

Future<void> mount(
  WidgetTester tester,
  PlusController controller,
  Widget home, {
  double scale = 1.8,
}) async {
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
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
        appBarTheme: AppBarTheme(
          titleTextStyle: plusTheme().textTheme.titleLarge!.copyWith(
            fontFamily: 'Roboto',
          ),
        ),
      ),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(scale)),
        child: RepaintBoundary(key: boundary, child: child!),
      ),
      home: home,
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(() async {
    const directory = String.fromEnvironment('CAPTURE_FONT_DIR');
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
  for (final discipline in ['pdr', 'collision']) {
    testWidgets(
      '$discipline opens the shared guide from its saved vehicle without sending',
      (tester) async {
        final repo = LiveCaptureRepository();
        final s = await fake.session(repo, MemoryGuidedCapturePendingStore());
        if (discipline == 'collision') {
          await repo.createEstimate({
            'vehicle_id': s.controller.selectedVehicle!.id,
            'discipline': 'collision',
            'description': 'Bumper damage',
          });
          await s.controller.refresh();
        }
        final estimate = s.controller.snapshot!.estimates.firstWhere(
          (e) => e.discipline == discipline && e.status == 'draft',
        );
        await mount(
          tester,
          s.controller,
          EstimateDetailScreen(
            controller: s.controller,
            estimateId: estimate.id,
            captureService: EstimateCaptureService(
              store: MemoryEstimateCaptureStore(),
            ),
            guidedCaptureBuilder: (_) => GuidedCaptureScreen(
              controller: s.controller,
              estimateId: estimate.id,
              store: MemoryGuidedCapturePendingStore(),
              viewBuilder: (session, close, error) => Center(
                child: TextButton(
                  onPressed: close,
                  child: Text('Shared ${session.discipline} vehicle guide'),
                ),
              ),
            ),
          ),
          scale: discipline == 'collision' ? 1 : 1.8,
        );
        expect(find.byKey(const Key('capture-camera')), findsNothing);
        await tester.ensureVisible(
          find.byKey(const Key('open-guided-capture')),
        );
        await tester.pumpAndSettle();
        await screenshot(
          tester,
          'estimate-$discipline-390-${discipline == 'collision' ? 'normal' : 'large'}',
        );
        await tap(tester, 'Start guided photos');
        expect(find.text('Shared $discipline vehicle guide'), findsOneWidget);
        expect(repo.api.saves, isEmpty);
        await tap(tester, 'Shared $discipline vehicle guide');
        expect(find.text('Your estimate'), findsOneWidget);
        expect(
          s.controller.snapshot!.estimates
              .firstWhere((e) => e.id == estimate.id)
              .status,
          'draft',
        );
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'restart waits for storage, then only an explicit retry replays the exact saved photo',
    (tester) async {
      final repo = LiveCaptureRepository(), store = DelayedStore();
      final s = await fake.session(repo, store);
      final value = GuidedCapturePending(
        ownerId: s.ownerId,
        estimateId: s.estimateId,
        operationId: '11111111-1111-4111-8111-111111111111',
        captureKey: 'vin',
        bodyStyle: 'sedan',
        mimeType: 'image/png',
        bytes: await _bytes(),
      );
      await store.write(value);
      var opens = 0;
      final home = GuidedCaptureScreen(
        controller: s.controller,
        estimateId: s.estimateId,
        store: store,
        viewBuilder: (session, close, error) {
          opens++;
          return const Text('Shared camera mounted');
        },
      );
      await tester.pumpWidget(MaterialApp(home: home));
      await tester.pump();
      expect(opens, 0);
      expect(repo.api.saves, isEmpty);
      store.loaded.complete();
      await tester.pumpAndSettle();
      expect(find.text('Retry saved photo'), findsOneWidget);
      expect(opens, 0);
      await tap(tester, 'Retry saved photo');
      expect(repo.api.saves.single.samePayload(value), isTrue);
      expect(await store.read(s.ownerId), isNull);
      expect(find.text('Shared camera mounted'), findsOneWidget);
    },
  );
  testWidgets(
    'saved photo recovery fits large text and explicit discard opens camera without upload',
    (tester) async {
      final repo = LiveCaptureRepository(),
          store = MemoryGuidedCapturePendingStore();
      final s = await fake.session(repo, store);
      await store.write(
        GuidedCapturePending(
          ownerId: s.ownerId,
          estimateId: s.estimateId,
          operationId: '11111111-1111-4111-8111-111111111111',
          captureKey: 'vin',
          bodyStyle: 'sedan',
          mimeType: 'image/png',
          bytes: await _bytes(),
        ),
      );
      await mount(
        tester,
        s.controller,
        GuidedCaptureScreen(
          controller: s.controller,
          estimateId: s.estimateId,
          store: store,
          viewBuilder: (session, close, error) =>
              const Text('Shared camera mounted'),
        ),
      );
      await screenshot(tester, 'recovery-390-large');
      await tap(tester, 'Discard saved photo & retake');
      expect(repo.api.saves, isEmpty);
      expect(await store.read(s.ownerId), isNull);
      expect(find.text('Shared camera mounted'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'account change while pending storage loads never reveals old recovery or camera',
    (tester) async {
      final repo = LiveCaptureRepository(), store = DelayedStore();
      final s = await fake.session(repo, store);
      await tester.pumpWidget(
        MaterialApp(
          home: GuidedCaptureScreen(
            controller: s.controller,
            estimateId: s.estimateId,
            store: store,
            viewBuilder: (session, close, error) =>
                const Text('Private camera'),
          ),
        ),
      );
      await tester.pump();
      s.controller.invalidateSession();
      store.loaded.complete();
      await tester.pumpAndSettle();
      expect(find.text('Private camera'), findsNothing);
      expect(find.text('Sign in to view your saved details.'), findsOneWidget);
      expect(repo.api.calls, isEmpty);
    },
  );
  testWidgets(
    'background removes camera and resume checks pending state before remounting',
    (tester) async {
      final repo = LiveCaptureRepository(),
          store = MemoryGuidedCapturePendingStore();
      final s = await fake.session(repo, store);
      await mount(
        tester,
        s.controller,
        GuidedCaptureScreen(
          controller: s.controller,
          estimateId: s.estimateId,
          store: store,
          viewBuilder: (session, close, error) => const Text('Private camera'),
        ),
      );
      expect(find.text('Private camera'), findsOneWidget);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      // Paused frames do not paint; the session is already invalidated.
      await store.write(
        GuidedCapturePending(
          ownerId: s.ownerId,
          estimateId: s.estimateId,
          operationId: '11111111-1111-4111-8111-111111111111',
          captureKey: 'vin',
          bodyStyle: 'sedan',
          mimeType: 'image/png',
          bytes: await _bytes(),
        ),
      );
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.text('Private camera'), findsNothing);
      expect(find.text('Retry saved photo'), findsOneWidget);
      expect(repo.api.saves, isEmpty);
    },
  );
  test(
    'PDR readiness accepts a matching close and raking pair; VIN is required',
    () async {
      final repo = LiveCaptureRepository();
      final s = await fake.session(repo, MemoryGuidedCapturePendingStore());
      final estimate = s.controller.snapshot!.estimates.firstWhere(
        (e) => e.id == s.estimateId,
      );
      expect(requiredEstimateViews, contains('vin'));
      expect(estimatePhotosReady(s.controller.snapshot!, estimate), isFalse);
      CustomerEstimate withPhotos(List<String> keys) =>
          CustomerEstimate.fromJson({
            'id': estimate.id,
            'vehicle_id': estimate.vehicleId,
            'discipline': 'pdr',
            'status': 'draft',
            'photos': [
              for (final key in keys) {'id': 'photo-$key', 'label': key},
            ],
          });
      final keys = [
        ...requiredEstimateViews,
        'hail_close_hood',
        'hail_raking_hood',
      ];
      expect(
        estimatePhotosReady(s.controller.snapshot!, withPhotos(keys)),
        isTrue,
      );
      expect(
        estimatePhotosReady(
          s.controller.snapshot!,
          withPhotos(keys.where((k) => k != 'vin').toList()),
        ),
        isFalse,
      );
      expect(
        estimatePhotosReady(
          s.controller.snapshot!,
          withPhotos([
            ...requiredEstimateViews,
            'hail_close_hood',
            'hail_raking_roof',
          ]),
        ),
        isFalse,
      );
    },
  );
}

Future<Uint8List> _bytes() async => Uint8List.fromList([1, 2, 3]);
