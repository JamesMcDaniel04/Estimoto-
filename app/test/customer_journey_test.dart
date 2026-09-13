import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/app.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/state/plus_controller.dart';

void main() {
  Future<PlusController> launch(
    WidgetTester tester, {
    Size size = const Size(390, 844),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = PlusController(DemoPlusRepository());
    await controller.refresh();
    await tester.pumpWidget(
      EstimotoPlusApp(controller: controller, onExit: () {}),
    );
    await tester.pumpAndSettle();
    return controller;
  }

  testWidgets(
    'customer navigation keeps PDR and Collision tabs and demo identity',
    (tester) async {
      await launch(tester);
      expect(find.text('Estimoto +'), findsOneWidget);
      expect(find.textContaining('Demo'), findsWidgets);
      await tester.tap(find.byKey(const Key('nav-estimates')));
      await tester.pumpAndSettle();
      expect(find.text('PDR'), findsWidgets);
      expect(find.text('Collision'), findsWidgets);
      await tester.tap(find.text('Collision').first);
      await tester.pumpAndSettle();
      expect(find.text('Rear bumper repair.'), findsOneWidget);
      await tester.tap(find.byKey(const Key('nav-garage')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('nav-estimates')));
      await tester.pumpAndSettle();
      expect(find.text('Rear bumper repair.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('Estibot matches providers without sending a request', (
    tester,
  ) async {
    final controller = await launch(tester);
    await tester.tap(find.byKey(const Key('nav-estibot')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('assistant-message')),
      'Find mobile dent repair at my house',
    );
    await tester.tap(find.byKey(const Key('assistant-send')));
    await tester.pumpAndSettle();
    expect(find.text('Demo Dent Studio'), findsWidgets);
    expect(controller.snapshot!.requests, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('garage and navigation remain usable at 320px', (tester) async {
    await launch(tester, size: const Size(320, 740));
    expect(find.byKey(const Key('nav-find-help')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.byKey(const Key('nav-find-help')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'cradled Estibot navigation leaves the composer clear and hides for typing',
    (tester) async {
      await launch(tester);
      await tester.tap(find.byKey(const Key('nav-estibot')));
      await tester.pumpAndSettle();
      final bar = find.byType(BottomAppBar);
      final fab = find.byType(FloatingActionButton);
      expect(bar, findsOneWidget);
      expect(fab, findsOneWidget);
      final barRect = tester.getRect(bar);
      final fabRect = tester.getRect(fab);
      expect(fabRect.center.dx, closeTo(barRect.center.dx, 1));
      expect(fabRect.top, lessThan(barRect.top));
      expect(fabRect.bottom, greaterThan(barRect.top));
      expect(
        tester.getRect(find.byKey(const Key('assistant-message'))).bottom,
        lessThanOrEqualTo(fabRect.top),
      );
      final shape = tester.widget<BottomAppBar>(bar).shape!;
      final host = Rect.fromLTWH(0, 0, barRect.width, barRect.height);
      final guest = fabRect.shift(-barRect.topLeft).inflate(8);
      final path = shape.getOuterPath(host, guest);
      expect(path.contains(Offset(host.center.dx, guest.center.dy)), isFalse);
      expect(path.contains(Offset(36, 36)), isTrue);

      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      addTearDown(tester.view.resetViewInsets);
      await tester.pumpAndSettle();
      expect(fab, findsNothing);
      expect(
        tester.getRect(find.byKey(const Key('assistant-message'))).bottom,
        lessThanOrEqualTo(544),
      );
      tester.view.resetViewInsets();
      await tester.pumpAndSettle();
      expect(fab, findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'a reviewed request requires consent, stays pending, and can cancel',
    (tester) async {
      final controller = await launch(tester);
      await tester.tap(find.byKey(const Key('nav-find-help')));
      await tester.pumpAndSettle();
      final requestAction = find.text('Request help').first;
      await tester.ensureVisible(requestAction);
      await tester.tap(requestAction);
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('request-description')),
        'Please fix the dent on my door.',
      );
      final send = find.byKey(const Key('send-request'));
      await tester.ensureVisible(send);
      await tester.tap(send);
      await tester.pumpAndSettle();
      expect(controller.snapshot!.requests, isEmpty);
      expect(find.textContaining('Choose to share'), findsOneWidget);
      final consent = find.byKey(const Key('share-contact'));
      await tester.ensureVisible(consent);
      await tester.tap(consent);
      await tester.ensureVisible(send);
      await tester.tap(send);
      await tester.pumpAndSettle();
      expect(controller.tab, 3);
      expect(controller.snapshot!.requests.single.status, 'requested');
      expect(
        controller.snapshot!.requests.single.deliveryStatus,
        'local_preview',
      );
      expect(find.text('Review your request'), findsNothing);
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      final cancel = find.text('Cancel request');
      await tester.ensureVisible(cancel);
      await tester.tap(cancel);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Cancel request'));
      await tester.pumpAndSettle();
      expect(controller.snapshot!.requests.single.status, 'cancelled');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('a new draft reuses the car without requiring claim details', (
    tester,
  ) async {
    final controller = await launch(tester);
    await tester.tap(find.text('Get an estimate'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextField, 'Describe the damage'),
      'Small door dent behind the handle.',
    );
    final save = find.text('Save draft & add photos');
    await tester.ensureVisible(save);
    await tester.tap(save);
    await tester.pumpAndSettle();
    final draft = controller.snapshot!.estimates.firstWhere(
      (e) => e.description == 'Small door dent behind the handle.',
    );
    expect(draft.vehicleId, controller.selectedVehicleId);
    expect(draft.status, 'draft');
    expect(draft.amountCents, isNull);
    expect(draft.json['date_of_loss'], isNull);
    expect(find.text('Add clear photos'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('large text remains usable on a narrow phone across tabs', (
    tester,
  ) async {
    tester.platformDispatcher.textScaleFactorTestValue = 1.8;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await launch(tester, size: const Size(320, 740));
    for (final tab in [
      'estimates',
      'estibot',
      'repairs',
      'find-help',
      'garage',
    ]) {
      await tester.tap(find.byKey(Key('nav-$tab')));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: tab);
    }
  });
}
