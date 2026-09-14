import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/screens/estimate_forms.dart';
import 'package:estimoto_plus/services/estimate_capture.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';

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

Future<(PlusController, String)> _openDraft(
  WidgetTester tester, {
  String description = 'Small dent',
}) async {
  final repository = DemoPlusRepository();
  final controller = PlusController(repository);
  await controller.refresh();
  final draft = await repository.createEstimate({
    'vehicle_id': controller.snapshot!.vehicles.first.id,
    'discipline': 'pdr',
    'description': description,
  });
  await controller.refresh();
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: plusTheme(),
      home: EstimateDetailScreen(
        controller: controller,
        estimateId: draft['id'] as String,
        captureService: EstimateCaptureService(
          store: MemoryEstimateCaptureStore(),
          picker: _Picker(),
          readBytes: (_) async => _pixel,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return (controller, draft['id'] as String);
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('a draft can be edited, its photo removed, and deleted', (
    tester,
  ) async {
    final (controller, id) = await _openDraft(tester);
    await _tap(tester, find.byTooltip('Estimate options'));
    await _tap(tester, find.text('Edit details'));
    await tester.enterText(
      find.widgetWithText(TextField, 'Describe the damage'),
      'Small dent on the hood',
    );
    await _tap(tester, find.text('Save changes'));
    expect(find.text('Small dent on the hood'), findsOneWidget);
    // Demo drafts can attach a photo through the simple picker.
    await _tap(tester, find.byKey(const Key('capture-gallery')));
    expect(find.text('Saved photos (1)'), findsOneWidget);
    await _tap(tester, find.byTooltip('Remove photo'));
    await _tap(tester, find.widgetWithText(TextButton, 'Remove'));
    expect(find.text('Saved photos (0)'), findsOneWidget);
    await _tap(tester, find.byTooltip('Estimate options'));
    await _tap(tester, find.text('Delete draft'));
    await _tap(tester, find.widgetWithText(TextButton, 'Delete'));
    expect(controller.snapshot!.estimates.any((e) => e.id == id), isFalse);
  });

  testWidgets('a shared estimate shows no edit or delete actions', (
    tester,
  ) async {
    final (controller, id) = await _openDraft(tester, description: 'Shared');
    (controller.repository as DemoPlusRepository).debugEstimateRow(
      id,
    )['delivery_status'] = 'queued';
    await controller.refresh();
    await tester.pumpAndSettle();
    await _tap(tester, find.byTooltip('Estimate options'));
    expect(find.text('Edit details'), findsNothing);
    expect(find.text('Delete draft'), findsNothing);
    expect(find.textContaining('can no longer be changed'), findsOneWidget);
  });
}
