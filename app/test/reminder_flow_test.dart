import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/app.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/state/plus_controller.dart';

Future<PlusController> _app(WidgetTester tester) async {
  final controller = PlusController(DemoPlusRepository());
  await controller.refresh();
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    EstimotoPlusApp(controller: controller, onExit: () {}),
  );
  await tester.pumpAndSettle();
  return controller;
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('a reminder can be opened, edited and deleted from the garage', (
    tester,
  ) async {
    final controller = await _app(tester);
    final title = controller.snapshot!.reminders.first.title;
    await _tap(tester, find.text(title));
    expect(find.text('Edit reminder'), findsOneWidget);
    await tester.enterText(
      find.widgetWithText(TextField, 'What needs attention?'),
      'Rotate tires',
    );
    await _tap(tester, find.text('Save reminder'));
    expect(find.text('Rotate tires'), findsOneWidget);
    expect(find.text(title), findsNothing);
    await _tap(tester, find.text('Rotate tires'));
    await _tap(tester, find.text('Delete reminder'));
    expect(find.text('Delete this reminder?'), findsOneWidget);
    await _tap(tester, find.widgetWithText(TextButton, 'Delete'));
    expect(find.text('Rotate tires'), findsNothing);
    expect(
      controller.snapshot!.reminders.any((r) => r.title == 'Rotate tires'),
      isFalse,
    );
  });

  testWidgets('completing a reminder offers undo', (tester) async {
    final controller = await _app(tester);
    final reminder = controller.snapshot!.reminders.first;
    await _tap(tester, find.byTooltip('Mark reminder complete').first);
    expect(find.text('Reminder completed'), findsOneWidget);
    expect(find.text(reminder.title), findsNothing);
    await _tap(tester, find.text('Undo'));
    expect(find.text(reminder.title), findsOneWidget);
    expect(
      controller.snapshot!.reminders
          .firstWhere((r) => r.id == reminder.id)
          .completed,
      isFalse,
    );
  });
}
