import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/history_screen.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';

void main() {
  testWidgets(
    'inline picker uses a fresh web click and never reopens on refresh',
    (tester) async {
      final repo = DemoPlusRepository();
      final controller = PlusController(repo);
      await controller.refresh();
      var picks = 0;
      await tester.pumpWidget(
        MaterialApp(
          theme: plusTheme(),
          home: HistoryEditor(
            controller: controller,
            pdfPicker: () async {
              picks++;
              return null;
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Choose PDF'));
      await tester.tap(find.text('Choose PDF'));
      await tester.pumpAndSettle();
      expect(find.text('History entry saved.'), findsOneWidget);
      expect(find.textContaining('No receipt attached yet.'), findsOneWidget);
      expect(rowsOf(await repo.getKnowledge(), 'records'), hasLength(1));
      expect(picks, kIsWeb ? 0 : 1);
      await tester.tap(find.byTooltip('Refresh receipts'));
      await tester.pumpAndSettle();
      expect(picks, kIsWeb ? 0 : 1);
      await tester.ensureVisible(find.text('Choose PDF'));
      await tester.tap(find.text('Choose PDF'));
      await tester.pumpAndSettle();
      expect(picks, kIsWeb ? 1 : 2);
      expect(rowsOf(await repo.getKnowledge(), 'records'), hasLength(1));
      expect(tester.takeException(), isNull);
    },
  );
}
