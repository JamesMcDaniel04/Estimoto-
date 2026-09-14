import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/screens/estimate_forms.dart';
import 'package:estimoto_plus/screens/guided_capture_screen.dart';
import 'package:estimoto_plus/screens/history_receipts_screen.dart';
import 'package:estimoto_plus/screens/request_sheet.dart';
import 'package:estimoto_plus/screens/shop_outreach_screen.dart';
import 'package:estimoto_plus/screens/vehicle_photo_screen.dart';
import 'package:estimoto_plus/screens/vehicle_value_screen.dart';
import 'package:estimoto_plus/state/plus_controller.dart';

Future<void> openDetail(WidgetTester tester, Widget detail) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(builder: (_) => detail),
            ),
            child: const Text('Open saved record'),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('Open saved record'));
  await tester.pumpAndSettle();
}

Future<void> goBack(WidgetTester tester) async {
  expect(find.byType(BackButton), findsOneWidget);
  await tester.tap(find.byType(BackButton));
  await tester.pumpAndSettle();
  expect(find.text('Open saved record'), findsOneWidget);
  expect(tester.takeException(), isNull);
}

void main() {
  testWidgets('vehicle removed elsewhere while photo is open retains back', (
    tester,
  ) async {
    final repo = DemoPlusRepository();
    final controller = PlusController(repo);
    await controller.refresh();
    final car = await repo.saveVehicle({'make': 'Demo', 'model': 'Vehicle'});
    await controller.refresh();
    await openDetail(
      tester,
      VehiclePhotoScreen(controller: controller, vehicleId: car['id']),
    );
    await repo.deleteVehicle(car['id']);
    await controller.refresh(quiet: true);
    await tester.pumpAndSettle();
    expect(find.text('This vehicle is no longer available.'), findsOneWidget);
    expect(find.textContaining('Sign in'), findsNothing);
    await goBack(tester);
    controller.dispose();
  });

  for (final kind in [
    'vehicle photo',
    'vehicle value',
    'estimate',
    'guided photos',
    'history',
    'outreach',
  ]) {
    testWidgets('missing $kind record retains back navigation', (tester) async {
      final controller = PlusController(DemoPlusRepository());
      await controller.refresh();
      final screen = switch (kind) {
        'vehicle photo' => VehiclePhotoScreen(
          controller: controller,
          vehicleId: 'deleted',
        ),
        'vehicle value' => VehicleValueScreen(
          controller: controller,
          vehicleId: 'deleted',
        ),
        'estimate' => EstimateDetailScreen(
          controller: controller,
          estimateId: 'deleted',
        ),
        'guided photos' => GuidedCaptureScreen(
          controller: controller,
          estimateId: 'deleted',
        ),
        'history' => HistoryReceiptsScreen(
          controller: controller,
          recordId: 'deleted',
        ),
        _ => ShopOutreachReview(controller: controller, draftId: 'deleted'),
      };
      await openDetail(tester, screen);
      expect(find.textContaining('no longer available'), findsOneWidget);
      expect(find.textContaining('Sign in'), findsNothing);
      await goBack(tester);
      controller.dispose();
    });
  }

  for (final kind in [
    'vehicle photo',
    'vehicle value',
    'estimate',
    'history',
    'receipt',
  ]) {
    testWidgets(
      '$kind loses private content but keeps back after account changes',
      (tester) async {
        final controller = PlusController(DemoPlusRepository());
        await controller.refresh();
        final screen = switch (kind) {
          'vehicle photo' => VehiclePhotoScreen(
            controller: controller,
            vehicleId: controller.selectedVehicle!.id,
          ),
          'vehicle value' => VehicleValueScreen(
            controller: controller,
            vehicleId: controller.selectedVehicle!.id,
          ),
          'estimate' => EstimateDetailScreen(
            controller: controller,
            estimateId: 'demo-estimate',
          ),
          'history' => HistoryReceiptsScreen(
            controller: controller,
            recordId: 'deleted',
          ),
          _ => PrivateReceiptView(
            controller: controller,
            ownerId: controller.snapshot!.profile.id,
            filename: 'private.jpg',
            bytes: Uint8List(0),
            mimeType: 'image/jpeg',
          ),
        };
        await openDetail(tester, screen);
        controller.invalidateSession();
        await tester.pumpAndSettle();
        expect(find.textContaining('Sign in'), findsOneWidget);
        expect(find.text('private.jpg'), findsNothing);
        await goBack(tester);
        controller.dispose();
      },
    );
  }

  testWidgets('request sheet can close after account changes', (tester) async {
    final controller = PlusController(DemoPlusRepository());
    await controller.refresh();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => requestProvider(
                context,
                controller,
                controller.snapshot!.providers.first,
              ),
              child: const Text('Open saved record'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Open saved record'));
    await tester.pumpAndSettle();
    controller.invalidateSession();
    await tester.pumpAndSettle();
    await goBack(tester);
    controller.dispose();
  });
}
