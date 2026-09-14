import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/widgets/history_cost_summary.dart';
import 'package:estimoto_plus/screens/history_receipts_screen.dart';
import 'package:estimoto_plus/theme.dart';

class WorkRepo extends DemoPlusRepository {
  List<Json> records = [];
  @override
  Future<Json> getKnowledge() async => {'records': records, 'preferences': {}};
}

void main() {
  testWidgets('main refresh reloads server receipt details and removed costs', (
    t,
  ) async {
    final repo = WorkRepo();
    final c = PlusController(repo);
    await c.refresh();
    c.selectTab(3);
    addTearDown(c.dispose);
    await t.pumpWidget(
      MaterialApp(
        theme: plusTheme(),
        home: Scaffold(
          body: SingleChildScrollView(child: HistoryCostSummary(controller: c)),
        ),
      ),
    );
    await t.pumpAndSettle();
    expect(find.text('Oil service'), findsNothing);
    repo.records = [
      {
        'id': 'external-entry',
        'vehicle_id': c.selectedVehicle!.id,
        'service_type': 'repair',
        'service_date': '2026-09-14',
        'cost_cents': 12990,
        'receipts': [
          {
            'id': 'external-receipt',
            'filename': 'work.pdf',
            'total_extraction': {
              'items_status': 'ready',
              'work_items': [
                {
                  'title': 'Oil service',
                  'tasks': ['Replace oil and filter'],
                  'parts': [],
                },
              ],
            },
          },
        ],
      },
    ];
    await c.refresh();
    await t.pumpAndSettle();
    expect(find.text('Oil service'), findsOneWidget);
    expect(find.text('\$129.90'), findsNWidgets(2));
    repo.records = [];
    await c.refresh();
    await t.pumpAndSettle();
    expect(find.text('Work from your receipts'), findsNothing);
    expect(find.text('\$129.90'), findsNothing);
    expect(find.text('\$0.00'), findsNWidgets(4));
  });

  testWidgets(
    'Repairs summary shows parsed tasks and parts without adding costs twice',
    (t) async {
      final repo = WorkRepo();
      final c = PlusController(repo);
      await c.refresh();
      addTearDown(c.dispose);
      repo.records = [
        {
          'id': 'entry',
          'vehicle_id': c.selectedVehicle!.id,
          'service_date': '2025-10-15',
          'service_type': 'repair',
          'shop_name': 'Example Garage',
          'cost_cents': 12550,
          'receipts': [
            {
              'id': 'receipt',
              'filename': 'service.pdf',
              'total_extraction': {
                'items_status': 'ready',
                'items_version': 1,
                'work_items': [
                  {
                    'title': 'Oil service',
                    'amount_cents': 10000,
                    'tasks': ['Replace oil and filter'],
                    'parts': ['Oil filter', 'Synthetic engine oil'],
                  },
                  {
                    'title': 'Brake inspection',
                    'amount_cents': 2000,
                    'tasks': ['Road Test'],
                    'parts': [],
                  },
                ],
              },
            },
          ],
        },
        {
          'id': 'other',
          'vehicle_id': 'other-vehicle',
          'service_type': 'repair',
          'cost_cents': 99900,
          'receipts': [
            {
              'id': 'other-receipt',
              'total_extraction': {
                'work_items': [
                  {'title': 'Other vehicle private work'},
                ],
              },
            },
          ],
        },
      ];
      await t.pumpWidget(
        MaterialApp(
          theme: plusTheme(),
          home: Scaffold(
            body: SingleChildScrollView(
              child: HistoryCostSummary(controller: c),
            ),
          ),
        ),
      );
      await t.pumpAndSettle();
      expect(find.text('Work from your receipts'), findsOneWidget);
      expect(find.text('Oil service'), findsOneWidget);
      expect(find.text('• Replace oil and filter'), findsOneWidget);
      expect(find.text('• Oil filter'), findsOneWidget);
      expect(find.text('Other vehicle private work'), findsNothing);
      expect(find.text('\$125.50'), findsNWidgets(2));
      expect(find.text('\$245.50'), findsNothing);
      final view = find.byKey(const ValueKey('work-receipt-entry'));
      await t.ensureVisible(view);
      await t.tap(view);
      await t.pumpAndSettle();
      expect(find.byType(HistoryReceiptsScreen), findsOneWidget);
      await t.pageBack();
      await t.pumpAndSettle();
      repo.records[0]['receipts'] = [];
      c.historyChanged();
      await t.pumpAndSettle();
      expect(find.text('Oil service'), findsNothing);
      expect(find.text('\$125.50'), findsNWidgets(2));
    },
  );
}
