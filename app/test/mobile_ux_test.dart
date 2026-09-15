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

void main() {
  testWidgets('garage reminders show how soon they are due', (tester) async {
    await _app(tester);
    expect(find.text('Due in 14 days'), findsOneWidget);
    expect(find.byTooltip('Mark reminder complete'), findsOneWidget);
  });

  testWidgets('pulling down the garage refreshes the account', (tester) async {
    final controller = await _app(tester);
    final before = controller.snapshot;
    await tester.fling(find.textContaining('Hi, '), const Offset(0, 400), 1200);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byType(RefreshProgressIndicator), findsOneWidget);
    await tester.pumpAndSettle();
    expect(find.byType(RefreshProgressIndicator), findsNothing);
    expect(identical(controller.snapshot, before), isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets('estimate cards summarize photos and last update', (
    tester,
  ) async {
    await _app(tester);
    await tester.tap(find.byKey(const Key('nav-estimates')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Demo Dent Studio · Updated'), findsOneWidget);
  });

  testWidgets('the Estibot composer keeps the newest message in view', (
    tester,
  ) async {
    await _app(tester);
    await tester.tap(find.byKey(const Key('nav-estibot')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('assistant-message')),
      'How do I check tire pressure?',
    );
    await tester.tap(find.byKey(const Key('assistant-send')));
    await tester.pumpAndSettle();
    final scrollable = find.descendant(
      of: find.byType(SingleChildScrollView),
      matching: find.byType(Scrollable),
    );
    final position = tester.state<ScrollableState>(scrollable.first).position;
    expect(position.pixels, closeTo(position.maxScrollExtent, 1));
    expect(tester.takeException(), isNull);
  });
}
