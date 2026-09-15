import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/gmail_screen.dart';
import 'package:estimoto_plus/screens/history_screen.dart';
import 'package:estimoto_plus/screens/settings_screen.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';

Json _message(String id, String category, {String status = 'new'}) => {
  'id': 'row-$id',
  'message_id': id,
  'thread_id': 't-$id',
  'received_at': '2026-09-01T15:00:00+00:00',
  'sender_name': 'Demo Body Shop',
  'sender_address': 'service@demobodyshop.example',
  'subject': switch (category) {
    'receipt' => 'Receipt for invoice 4471',
    'estimate' => 'Your repair estimate is ready',
    _ => 'Appointment confirmed for Tuesday',
  },
  'snippet': 'Paid \$412.50',
  'category': category,
  'status': status,
  'knowledge_record_id': null,
  'gmail_url': 'https://mail.google.com/mail/u/0/#all/$id',
};

class _MailRepository extends DemoPlusRepository {
  _MailRepository({this.configured = true, this.connected = true});
  bool configured, connected;
  List<Json> messages = [_message('m1', 'receipt'), _message('m2', 'estimate')];
  int scans = 0, disconnects = 0;
  final statusWrites = <(String, String, String?)>[];
  @override
  bool get isDemo => false;
  @override
  Future<PlusSnapshot> bootstrap() async {
    final demo = await super.bootstrap();
    return PlusSnapshot.fromJson({
      'profile': demo.profile.json,
      'vehicles': demo.vehicles.map((v) => v.json).toList(),
      'capabilities': {'demo': false},
    });
  }

  Json get _status => {
    'configured': configured,
    'connected': connected,
    'status': !configured
        ? 'unavailable'
        : connected
        ? 'connected'
        : 'disconnected',
    'generation': 1,
    'email_address': connected ? 'alex.driver@gmail.example' : null,
    'last_scan_at': connected ? '2026-09-14T09:00:00+00:00' : null,
    'attempt_id': null,
    'message_counts': {
      'new': messages.where((m) => m['status'] == 'new').length,
      'saved': messages.where((m) => m['status'] == 'saved').length,
      'dismissed': messages.where((m) => m['status'] == 'dismissed').length,
    },
  };
  @override
  Future<Json> getGmailStatus() async => _status;
  @override
  Future<Json> listGmailMessages() async => {
    'messages': [...messages],
  };
  @override
  Future<Json> scanGmail() async {
    scans++;
    messages.insert(0, _message('m${messages.length + 1}', 'appointment'));
    return {
      'scanned': 1,
      'messages': [...messages],
    };
  }

  @override
  Future<Json> setGmailMessageStatus(
    String id,
    String status, {
    String? knowledgeRecordId,
  }) async {
    statusWrites.add((id, status, knowledgeRecordId));
    final index = messages.indexWhere((m) => m['id'] == id);
    if (index < 0) throw const PlusApiException('Message not found.', 404);
    messages[index] = {
      ...messages[index],
      'status': status,
      'knowledge_record_id': status == 'saved' ? knowledgeRecordId : null,
    };
    return messages[index];
  }

  @override
  Future<Json> disconnectGmail() async {
    disconnects++;
    connected = false;
    messages = [];
    return {'disconnected': true};
  }
}

Future<PlusController> _mount(
  WidgetTester tester,
  _MailRepository repository, {
  bool settings = false,
}) async {
  final controller = PlusController(repository);
  await controller.refresh();
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: plusTheme(),
      home: settings
          ? SettingsScreen(controller: controller)
          : GmailScreen(controller: controller),
    ),
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
  test('a scanned message becomes a reviewable history draft', () {
    final draft = historyDraftFromMessage(
      _message('m1', 'receipt'),
      vehicleId: 'v1',
    );
    expect(draft['vehicle_id'], 'v1');
    expect(draft['service_type'], 'repair');
    expect(draft['service_date'], '2026-09-01');
    expect(draft['shop_name'], 'Demo Body Shop');
    expect(draft['notes'], contains('Receipt for invoice 4471'));
    expect(draft['notes'], contains('From Gmail on Sep 1, 2026.'));
    expect(
      historyDraftFromMessage(_message('m3', 'appointment'))['service_type'],
      'maintenance',
    );
  });

  testWidgets('an unconfigured server is honest and offers no connect', (
    tester,
  ) async {
    await _mount(tester, _MailRepository(configured: false, connected: false));
    expect(find.textContaining('not available yet'), findsOneWidget);
    expect(find.byKey(const Key('gmail-connect')), findsNothing);
  });

  testWidgets('a disconnected account can start connecting', (tester) async {
    await _mount(tester, _MailRepository(connected: false));
    expect(find.widgetWithText(FilledButton, 'Connect Gmail'), findsOneWidget);
    expect(find.byKey(const Key('gmail-scan')), findsNothing);
  });

  testWidgets('connected mail lists categories, scans, dismisses and files', (
    tester,
  ) async {
    final repository = _MailRepository();
    await _mount(tester, repository);
    expect(find.text('alex.driver@gmail.example'), findsOneWidget);
    expect(find.text('Receipt'), findsOneWidget);
    expect(find.text('Estimate'), findsOneWidget);
    expect(find.text('Receipt for invoice 4471'), findsOneWidget);

    await _tap(tester, find.byKey(const Key('gmail-scan')));
    expect(repository.scans, 1);
    expect(find.text('Found 1 new message.'), findsOneWidget);
    expect(find.text('Appointment'), findsOneWidget);

    await _tap(tester, find.widgetWithText(TextButton, 'Dismiss').first);
    expect(repository.statusWrites.last.$2, 'dismissed');
    expect(find.text('Handled'), findsOneWidget);
    expect(find.text('Move back'), findsOneWidget);

    final add = find.widgetWithText(FilledButton, 'Add to history').first;
    await tester.ensureVisible(add);
    await tester.tap(add);
    // The editor restores drafts asynchronously; settle a few frames instead
    // of waiting for its progress indicator.
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.byType(HistoryEditor), findsOneWidget);
    expect(
      find.widgetWithText(TextFormField, 'Demo Body Shop'),
      findsOneWidget,
    );
    expect(find.textContaining('From Gmail on'), findsOneWidget);
  });

  testWidgets('disconnecting asks first and forgets scanned mail', (
    tester,
  ) async {
    final repository = _MailRepository();
    await _mount(tester, repository);
    await _tap(tester, find.byKey(const Key('gmail-disconnect')));
    expect(find.text('Disconnect Gmail?'), findsOneWidget);
    await _tap(tester, find.widgetWithText(TextButton, 'Keep connected'));
    expect(repository.disconnects, 0);
    await _tap(tester, find.byKey(const Key('gmail-disconnect')));
    await _tap(tester, find.widgetWithText(FilledButton, 'Disconnect'));
    expect(repository.disconnects, 1);
    expect(find.text('Receipt for invoice 4471'), findsNothing);
    expect(find.widgetWithText(FilledButton, 'Connect Gmail'), findsOneWidget);
  });

  testWidgets('the settings tile shows mail waiting to be filed', (
    tester,
  ) async {
    await _mount(tester, _MailRepository(), settings: true);
    final tile = find.byKey(const Key('settings-gmail-connection'));
    await tester.ensureVisible(tile);
    expect(
      find.text('alex.driver@gmail.example · 2 messages to file'),
      findsOneWidget,
    );
    await _tap(tester, tile);
    expect(find.byType(GmailScreen), findsOneWidget);
  });

  testWidgets('the demo settings tile explains sample mode', (tester) async {
    final controller = PlusController(DemoPlusRepository());
    await controller.refresh();
    await tester.pumpWidget(
      MaterialApp(
        theme: plusTheme(),
        home: SettingsScreen(controller: controller),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('Sample mode'), findsOneWidget);
    expect(find.text('Not configured'), findsNothing);
  });
}
