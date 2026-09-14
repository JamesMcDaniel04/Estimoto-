import 'dart:async';
import 'support/receipt_proof.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/vehicle_value_screen.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';

class _Repository extends DemoPlusRepository {
  final calls = <Json>[];
  Completer<Json>? delayed;
  bool unavailable = false;
  @override
  Future<Json> lookupVehicleValue(
    String vehicleId,
    Json body, {
    required bool Function() isCurrent,
  }) async {
    calls.add({...body, 'vehicle_id': vehicleId});
    if (delayed != null) return delayed!.future;
    return answer(vehicleId, body);
  }

  Json answer(String id, Json body) => {
    'vehicle_id': id,
    ...body,
    'status': unavailable ? 'unavailable' : 'available',
    'provider': 'CarsXE',
    'currency': 'USD',
    'provider_region': 'NT',
    'cached': true,
    'fetched_at': '2026-09-13T12:00:00Z',
    'provider_publish_date': '2026-09',
    'message': 'A provider estimate is temporarily unavailable.',
    'buckets': unavailable
        ? <Json>[]
        : [
            {
              'kind': 'retail',
              'condition': body['condition'],
              'amount_cents': 2400050,
              'base_cents': 2500000,
              'mileage_adjustment_cents': -100000,
              'equipment_adjustment_cents': 0,
              'regional_adjustment_cents': 50,
              'amount_basis': 'provider_adjusted',
            },
          ],
    'history': {
      'records_count': 2,
      'costs_cents': 300000,
      'receipt_count': 1,
      'factors': ['One modification is documented.'],
    },
  };
}

Future<PlusController> _setup(_Repository repo) async {
  final c = PlusController(repo);
  await c.refresh();
  final car = c.selectedVehicle!;
  await repo.saveVehicle({...car.json, 'vin': '1HGBH41JXMN109186'}, id: car.id);
  await c.refresh();
  return c;
}

Future<void> mount(WidgetTester t, PlusController c) async {
  t.view.physicalSize = const Size(320, 740);
  t.view.devicePixelRatio = 1;
  addTearDown(t.view.resetPhysicalSize);
  addTearDown(t.view.resetDevicePixelRatio);
  await t.pumpWidget(
    MaterialApp(
      theme: const String.fromEnvironment('RECEIPT_FONT_DIR').isEmpty
          ? plusTheme()
          : plusTheme().copyWith(
              textTheme: plusTheme().textTheme.apply(fontFamily: 'Roboto'),
              primaryTextTheme: plusTheme().primaryTextTheme.apply(
                fontFamily: 'Roboto',
              ),
            ),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(1.8)),
        child: RepaintBoundary(
          key: const ValueKey('receipt-proof'),
          child: child!,
        ),
      ),
      home: VehicleValueScreen(controller: c, vehicleId: c.selectedVehicle!.id),
    ),
  );
  await t.pumpAndSettle();
  await t.ensureVisible(find.byKey(const Key('value-state')));
  await t.tap(find.byKey(const Key('value-state')));
  await t.pumpAndSettle();
  await t.ensureVisible(find.text('Colorado (CO)').last);
  await t.tap(find.text('Colorado (CO)').last);
  await t.pumpAndSettle();
}

Future<void> lookup(WidgetTester t, {bool settle = true}) async {
  final button = find.widgetWithText(FilledButton, 'Look up vehicle value');
  await t.ensureVisible(button);
  await t.tap(button);
  if (settle) {
    await t.pumpAndSettle();
  } else {
    await t.pump();
  }
}

void main() {
  setUpAll(loadReceiptProofFonts);
  testWidgets(
    'value lookup is explicit and keeps provider value separate from documented costs at 320px',
    (t) async {
      final repo = _Repository();
      final controller = await _setup(repo);
      await mount(t, controller);
      expect(repo.calls, isEmpty);
      await lookup(t);
      expect(repo.calls.single, {
        'state': 'CO',
        'condition': 'average',
        'vehicle_id': controller.selectedVehicle!.id,
      });
      expect(find.text('\$24,000.50'), findsOneWidget);
      expect(find.text('\$3,000.00'), findsOneWidget);
      expect(find.text('Provider market region: NT'), findsOneWidget);
      expect(find.textContaining('One modification'), findsOneWidget);
      await t.ensureVisible(find.text('Retail estimate'));
      await t.pumpAndSettle();
      await saveReceiptProof(t, 'vehicle-value-320-large');
      expect(t.takeException(), isNull);
      controller.historyChanged();
      await t.pumpAndSettle();
      expect(find.text('\$3,000.00'), findsNothing);
      expect(find.text('\$24,000.50'), findsOneWidget);
      expect(repo.calls.length, 1);
    },
  );
  testWidgets(
    'late provider result after mileage change cannot replace current vehicle data',
    (t) async {
      final repo = _Repository();
      final c = await _setup(repo);
      final done = Completer<Json>();
      repo.delayed = done;
      await mount(t, c);
      await lookup(t, settle: false);
      final car = c.selectedVehicle!;
      await repo.saveVehicle({
        ...car.json,
        'mileage': car.mileage + 1000,
      }, id: car.id);
      await c.refresh();
      done.complete(
        repo.answer(car.id, {'state': 'CO', 'condition': 'average'}),
      );
      await t.pumpAndSettle();
      expect(find.text('\$24,000.50'), findsNothing);
      expect(
        find.textContaining('saved vehicle details changed'),
        findsOneWidget,
      );
    },
  );
  testWidgets(
    'editing the saved vehicle model invalidates an already displayed quote',
    (t) async {
      final repo = _Repository();
      final c = await _setup(repo);
      await mount(t, c);
      await lookup(t);
      final car = c.selectedVehicle!;
      await repo.saveVehicle({
        ...car.json,
        'model': 'Changed model',
      }, id: car.id);
      await c.refresh();
      await t.pumpAndSettle();
      expect(find.text('\$24,000.50'), findsNothing);
      expect(
        find.textContaining('saved vehicle details changed'),
        findsOneWidget,
      );
    },
  );
  testWidgets(
    'unavailable provider keeps history; sign-out hides private value result',
    (t) async {
      final repo = _Repository()..unavailable = true;
      final c = await _setup(repo);
      await mount(t, c);
      await lookup(t);
      expect(find.text('\$3,000.00'), findsOneWidget);
      expect(find.text('Retail estimate'), findsNothing);
      expect(repo.calls.length, 1);
      c.invalidateSession();
      await t.pumpAndSettle();
      expect(find.text('\$3,000.00'), findsNothing);
      expect(find.textContaining('Sign in again'), findsOneWidget);
    },
  );
}
