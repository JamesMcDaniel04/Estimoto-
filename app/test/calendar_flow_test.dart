import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/request_sheet.dart';
import 'package:estimoto_plus/screens/shop_outreach_screen.dart';
import 'package:estimoto_plus/theme.dart';
import 'calendar_screen_test.dart'
    show CalendarRepository, calendarController, tapCalendar;

class FlowRepository extends CalendarRepository {
  Json? request, draftBody;
  final shop = <String, dynamic>{
    'id': 'shop-1',
    'name': 'My trusted shop',
    'email': 'shop@example.test',
  };
  @override
  Future<Json> createRequest(Json body, String key) async {
    request = jsonDecode(jsonEncode(body)) as Json;
    return {'id': 'request-1'};
  }

  @override
  Future<Json> createShopOutreach(Json body, String key) async {
    draftBody = jsonDecode(jsonEncode(body)) as Json;
    return {'id': 'draft-1'};
  }

  @override
  Future<Json> getShopOutreach(String id) async => {
    'id': id,
    'shop_name': shop['name'],
    'recipient_email': shop['email'],
    'message': 'Exact frozen message',
    'subject': 'Frozen subject',
    'shared_contact': {
      'name': 'Reviewed customer',
      'email': 'owner@example.test',
    },
    'vehicle_summary': '2022 Audi Q5',
    'review_hash': 'frozen-hash',
    'proposed_slots': draftBody?['proposed_slots'] ?? [],
    'calendar_check': true,
    'calendar_time_zone': 'America/Denver',
    'duration_minutes': 60,
    'calendar_sync_status': 'not_enabled',
    'status': 'draft',
    'delivery_status': 'draft',
  };
}

Future<void> chooseTime(WidgetTester tester) async {
  await tapCalendar(tester, find.byKey(const Key('choose-calendar-times')));
  await tapCalendar(tester, find.byKey(const Key('calendar-find-times')));
  await tapCalendar(tester, find.byKey(const Key('calendar-slot-0')));
  await tapCalendar(tester, find.byKey(const Key('calendar-use-times')));
}

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });
  testWidgets('provider review sends selected UTC slots only after consent', (
    tester,
  ) async {
    final repo = FlowRepository();
    repo.status.addAll({
      'connected': true,
      'status': 'connected',
      'selected_calendar_ids': ['one'],
      'time_zone': 'America/Denver',
    });
    final controller = await calendarController(repo);
    await tester.pumpWidget(
      MaterialApp(
        theme: plusTheme(),
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => requestProvider(
                context,
                controller,
                controller.snapshot!.providers.first,
                description: 'Please inspect the brakes.',
              ),
              child: const Text('Open request'),
            ),
          ),
        ),
      ),
    );
    await tapCalendar(tester, find.text('Open request'));
    await chooseTime(tester);
    expect(find.textContaining('America/Denver'), findsWidgets);
    expect(repo.request, isNull);
    await tapCalendar(tester, find.byKey(const Key('share-contact')));
    await tapCalendar(tester, find.byKey(const Key('send-request')));
    expect(repo.request?['calendar_check'], true);
    expect(repo.request?['duration_minutes'], 60);
    expect(repo.request?['calendar_generation'], 1);
    expect(repo.request?['proposed_slots'], [repo.lastSlots.first['start']]);
    expect(repo.request?['share_contact'], true);
    expect(repo.request?.containsKey('selected_calendar_ids'), false);
    expect(controller.messages, isEmpty);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'outreach drafts freeze checked slots and preserve exact private review',
    (tester) async {
      final repo = FlowRepository();
      repo.status.addAll({
        'connected': true,
        'status': 'connected',
        'selected_calendar_ids': ['one'],
        'time_zone': 'America/Denver',
      });
      final controller = await calendarController(repo);
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: plusTheme(),
          home: ShopOutreachComposer(
            controller: controller,
            shops: [repo.shop],
            initialSummary: 'Please inspect the brakes.',
          ),
        ),
      );
      await tester.pumpAndSettle();
      await chooseTime(tester);
      await tapCalendar(tester, find.text('Review request'));
      expect(repo.draftBody?['calendar_check'], true);
      expect(repo.draftBody?['proposed_slots'], [
        repo.lastSlots.first['start'],
      ]);
      expect(find.textContaining('Exact frozen message'), findsOneWidget);
      expect(find.text('shop@example.test'), findsOneWidget);
      expect(find.textContaining('America/Denver'), findsWidgets);
      expect(find.textContaining('60 minutes'), findsWidgets);
      expect(find.byKey(const Key('outreach-consent')), findsOneWidget);
      expect(repo.request, isNull);
      expect(tester.takeException(), isNull);
    },
  );
}
