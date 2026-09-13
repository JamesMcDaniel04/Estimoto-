import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/widgets/vehicle_photo.dart';

class _Photos extends DemoPlusRepository {
  final calls = <String>[];
  final responses = <String, Completer<VehiclePhoto?>>{};
  @override
  Future<VehiclePhoto?> getVehicleImage(String id) {
    calls.add(id);
    return (responses[id] ??= Completer<VehiclePhoto?>()).future;
  }
}

void main() {
  testWidgets(
    'rebuilds reuse a vehicle photo and stale vehicle responses are ignored',
    (tester) async {
      final repository = _Photos();
      final controller = PlusController(repository);
      await controller.refresh();
      Future<void> show(Vehicle vehicle) => tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: VehiclePhotoPanel(controller: controller, vehicle: vehicle),
          ),
        ),
      );
      final vehicles = controller.snapshot!.vehicles;
      await show(vehicles.first);
      await controller.refresh(quiet: true);
      await show(controller.snapshot!.vehicles.first);
      expect(repository.calls, [vehicles.first.id]);
      await show(vehicles.last);
      expect(repository.calls, [vehicles.first.id, vehicles.last.id]);
      repository.responses[vehicles.last.id]!.complete(null);
      await tester.pump();
      repository.responses[vehicles.first.id]!.complete(
        VehiclePhoto(Uint8List(0), source: 'upload'),
      );
      await tester.pump();
      expect(find.text('Your photo'), findsNothing);
      expect(find.text('Add a photo of your car'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets(
    'a signed-out customer cannot render an image that finishes later',
    (tester) async {
      final repository = _Photos();
      final controller = PlusController(repository);
      await controller.refresh();
      final vehicle = controller.selectedVehicle!;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: VehiclePhotoPanel(controller: controller, vehicle: vehicle),
          ),
        ),
      );
      controller.invalidateSession();
      repository.responses[vehicle.id]!.complete(
        VehiclePhoto(Uint8List(0), source: 'upload'),
      );
      await tester.pump();
      expect(find.text('Your photo'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );
}
