import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/screens/calendar_screen.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';

void main() {
  testWidgets('the demo calendar can be disconnected', (tester) async {
    final controller = PlusController(DemoPlusRepository());
    await controller.refresh();
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        theme: plusTheme(),
        home: CalendarScreen(controller: controller),
      ),
    );
    await tester.pumpAndSettle();
    final disconnect = find.byKey(const Key('calendar-disconnect'));
    expect(disconnect, findsOneWidget);
    await tester.ensureVisible(disconnect);
    await tester.tap(disconnect);
    await tester.pumpAndSettle();
    final confirm = find.widgetWithText(FilledButton, 'Disconnect');
    if (confirm.evaluate().isNotEmpty) {
      await tester.tap(confirm);
      await tester.pumpAndSettle();
    }
    expect(find.byKey(const Key('calendar-disconnect')), findsNothing);
    expect(
      (await controller.repository.getCalendarStatus())['connected'],
      false,
    );
  });
}
