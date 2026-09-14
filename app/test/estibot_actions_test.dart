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
  await tester.tap(find.byKey(const Key('nav-estibot')));
  await tester.pumpAndSettle();
  return controller;
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the conversation can be cleared', (tester) async {
    final controller = await _app(tester);
    await _tap(tester, find.text('How do I check tire pressure?'));
    expect(controller.messages, isNotEmpty);
    await _tap(tester, find.byTooltip('Conversation options'));
    await _tap(tester, find.text('Clear conversation'));
    expect(find.text('Clear this conversation?'), findsOneWidget);
    await _tap(tester, find.widgetWithText(TextButton, 'Clear'));
    expect(controller.messages, isEmpty);
    expect(find.text('How do I check tire pressure?'), findsOneWidget);
  });

  testWidgets('an unmatched question offers the technician search', (
    tester,
  ) async {
    final controller = await _app(tester);
    await tester.enterText(
      find.byType(TextField),
      'my check engine light is on',
    );
    await _tap(tester, find.byTooltip('Send message'));
    expect(find.textContaining("I can't answer that one yet"), findsOneWidget);
    expect(find.text('Find a technician for this'), findsOneWidget);
    await _tap(tester, find.text('Find a technician for this'));
    expect(controller.tab, 4);
  });
}
