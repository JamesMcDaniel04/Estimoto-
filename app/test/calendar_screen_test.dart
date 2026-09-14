import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/data/demo_seed.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/calendar_screen.dart';
import 'package:estimoto_plus/services/calendar_time.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';
import 'package:estimoto_plus/widgets/calendar_slot_picker.dart';

class CalendarRepository extends DemoPlusRepository {
  @override
  bool get isDemo => false;
  Json status = {
    'configured': true,
    'connected': false,
    'status': 'disconnected',
    'generation': 1,
    'selected_calendar_ids': <String>[],
    'time_zone': 'Etc/UTC',
    'sync_confirmed': false,
    'attempt_id': null,
    'sync_issues': <Json>[],
  };
  Completer<Json>? reconcile;
  final attempts = <String>[];
  Json? preferences;
  Completer<Json>? availability;
  Json? availabilityQuery;
  Completer<Json>? connecting, calendarList;
  String connectLink = 'https://connect.nango.dev/session';
  Json? retried;
  bool disconnectFails = false;
  @override
  Future<PlusSnapshot> bootstrap() async {
    final value = demoSeed();
    return PlusSnapshot.fromJson({
      ...value,
      'capabilities': {
        ...value['capabilities'] as Json,
        'demo': false,
        'live_requests': true,
      },
    });
  }

  @override
  Future<Json> getCalendarStatus() async => Map.of(status);
  @override
  Future<Json> reconcileGoogleCalendar(String id) async {
    attempts.add(id);
    if (reconcile != null) return reconcile!.future;
    status = {
      ...status,
      'connected': true,
      'status': 'connected',
      'attempt_id': null,
    };
    return Map.of(status);
  }

  @override
  Future<Json> listGoogleCalendars() async => calendarList != null
      ? calendarList!.future
      : {
          'calendars': [
            {
              'id': 'one',
              'summary':
                  'Personal calendar with a deliberately long private name',
              'primary': true,
            },
            {'id': 'two', 'summary': 'Family', 'primary': false},
          ],
        };
  @override
  Future<Json> connectGoogleCalendar() async {
    if (connecting != null) return connecting!.future;
    status = {
      ...status,
      'status': 'connecting',
      'attempt_id': 'new-attempt',
      'connected': false,
    };
    return {'attempt_id': 'new-attempt', 'connect_link': connectLink};
  }

  @override
  Future<Json> disconnectGoogleCalendar() async {
    if (disconnectFails) throw const PlusApiException('Connection timed out.');
    status = {
      ...status,
      'status': 'disconnected',
      'connected': false,
      'attempt_id': null,
      'generation': 2,
    };
    return {'disconnected': true};
  }

  @override
  Future<Json> retryCalendarSync(Json body) async {
    retried = body;
    status['sync_issues'] = <Json>[];
    return {...body, 'calendar_sync_status': 'pending'};
  }

  @override
  Future<Json> saveCalendarPreferences(Json body) async {
    preferences = body;
    status = {...status, ...body, 'generation': 2};
    return Map.of(status);
  }

  List<Json> lastSlots = [];
  @override
  Future<Json> findCalendarAvailability(Json body) async {
    availabilityQuery = body;
    if (availability != null) return availability!.future;
    final first = DateTime.parse(
      body['time_min'] as String,
    ).toUtc().add(const Duration(hours: 16));
    lastSlots = [
      for (var i = 0; i < 4; i++)
        {
          'start': first.add(Duration(days: i)).toIso8601String(),
          'end': first
              .add(Duration(days: i, minutes: body['duration_minutes'] as int))
              .toIso8601String(),
        },
    ];
    return {
      'slots': lastSlots,
      'generation': status['generation'],
      'time_zone': status['time_zone'],
      'duration_minutes': body['duration_minutes'],
      'checked_at': DateTime.now().toUtc().toIso8601String(),
    };
  }
}

Future<PlusController> calendarController([
  DemoPlusRepository? repository,
]) async {
  final value = PlusController(repository ?? CalendarRepository());
  await value.refresh();
  return value;
}

ThemeData calendarProofTheme() {
  final base = plusTheme();
  return base.copyWith(
    textTheme: base.textTheme.apply(fontFamily: 'Roboto'),
    primaryTextTheme: base.primaryTextTheme.apply(fontFamily: 'Roboto'),
    appBarTheme: base.appBarTheme.copyWith(
      titleTextStyle: base.textTheme.titleLarge!.copyWith(fontFamily: 'Roboto'),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: base.filledButtonTheme.style!.copyWith(
        textStyle: const WidgetStatePropertyAll(
          TextStyle(
            fontFamily: 'Roboto',
            fontSize: 15,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    ),
  );
}

Future<void> mountCalendar(
  WidgetTester tester,
  PlusController controller, {
  double scale = 1,
}) async {
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: calendarProofTheme(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(scale)),
        child: child!,
      ),
      home: RepaintBoundary(
        key: const Key('calendar-proof'),
        child: CalendarScreen(controller: controller),
      ),
    ),
  );
}

Future<void> calendarProof(WidgetTester tester, String name) async {
  const directory = String.fromEnvironment('CALENDAR_CAPTURE_DIR');
  if (directory.isEmpty) return;
  final boundary = tester.renderObject<RenderRepaintBoundary>(
    find.byKey(const Key('calendar-proof')),
  );
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 1);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    await Directory(directory).create(recursive: true);
    await File(
      '$directory/$name.png',
    ).writeAsBytes(bytes!.buffer.asUint8List());
    image.dispose();
  });
}

Future<void> tapCalendar(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  test('sample availability starts at 9 AM in the demo Denver zone', () async {
    final repo = DemoPlusRepository();
    final status = await repo.getCalendarStatus();
    expect(status['time_zone'], 'America/Denver');
    final response = await repo.findCalendarAvailability(
      calendarAvailabilityBody(
        date: DateTime(2026, 9, 14),
        days: 7,
        timeZone: status['time_zone'],
        duration: 60,
        dayStart: 9,
        dayEnd: 17,
      ),
    );
    expect(
      rowsOf(response, 'slots').first['start'],
      '2026-09-14T15:00:00.000Z',
    );
    expect(
      calendarSlotLabel(
        rowsOf(response, 'slots').first['start'],
        response['time_zone'],
      ),
      contains('9:00 AM (America/Denver, UTC-06:00)'),
    );
  });
  for (final (savedZone, expectedZone) in [
    ('', 'America/Denver'),
    ('Etc/UTC', 'Etc/UTC'),
    ('Asia/Kathmandu', 'Asia/Kathmandu'),
  ]) {
    testWidgets(
      'device zone seeds only unconfigured calendar zone: $savedZone',
      (tester) async {
        const channel = MethodChannel('io.estimoto.plus/device_time_zone');
        tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          channel,
          (_) async => 'America/Denver',
        );
        addTearDown(
          () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
            channel,
            null,
          ),
        );
        final repo = CalendarRepository();
        repo.status.addAll({
          'connected': true,
          'status': 'connected',
          'time_zone': savedZone,
        });
        final controller = await calendarController(repo);
        await mountCalendar(tester, controller);
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<TextFormField>(find.byKey(const Key('calendar-zone')))
              .controller!
              .text,
          expectedZone,
        );
        expect(repo.preferences, isNull);
        await tapCalendar(tester, find.byKey(const Key('calendar-choice-one')));
        await tapCalendar(tester, find.byKey(const Key('calendar-save')));
        expect(repo.preferences?['time_zone'], expectedZone);
      },
    );
  }

  testWidgets('unknown device zone requires an explicit valid calendar zone', (
    tester,
  ) async {
    const channel = MethodChannel('io.estimoto.plus/device_time_zone');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      channel,
      (_) async => 'MDT',
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        null,
      ),
    );
    final repo = CalendarRepository();
    repo.status.addAll({
      'connected': true,
      'status': 'connected',
      'time_zone': '',
    });
    final controller = await calendarController(repo);
    await mountCalendar(tester, controller);
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<TextFormField>(find.byKey(const Key('calendar-zone')))
          .controller!
          .text,
      '',
    );
    await tapCalendar(tester, find.byKey(const Key('calendar-choice-one')));
    await tapCalendar(tester, find.byKey(const Key('calendar-save')));
    expect(repo.preferences, isNull);
    expect(find.textContaining('Enter an IANA time zone'), findsOneWidget);
  });

  testWidgets('uncertain disconnect does not claim Google access stopped', (
    tester,
  ) async {
    final repo = CalendarRepository()..disconnectFails = true;
    repo.status.addAll({'connected': true, 'status': 'connected'});
    final owner = await calendarController(repo);
    await mountCalendar(tester, owner);
    await tester.pumpAndSettle();
    await tapCalendar(tester, find.byKey(const Key('calendar-disconnect')));
    expect(
      find.textContaining('Disconnection is not confirmed'),
      findsOneWidget,
    );
    expect(find.text('Connect Google Calendar'), findsNothing);
    expect(find.byKey(const Key('calendar-disconnect')), findsOneWidget);
    expect(repo.status['connected'], true);
    await tapCalendar(tester, find.byTooltip('Refresh Calendar'));
    expect(find.textContaining('Personal calendar'), findsOneWidget);
    expect(find.textContaining('Disconnection is not confirmed'), findsNothing);
  });
  testWidgets(
    'date picker remains usable when its open session crosses a day boundary',
    (tester) async {
      final repo = CalendarRepository();
      repo.status.addAll({
        'connected': true,
        'status': 'connected',
        'selected_calendar_ids': ['one'],
        'time_zone': 'Etc/UTC',
      });
      final owner = await calendarController(repo);
      var now = DateTime.utc(2026, 9, 13, 12);
      await tester.pumpWidget(
        MaterialApp(
          home: CalendarSlotPicker(controller: owner, now: () => now),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Starting 9/14/2026'), findsOneWidget);
      now = DateTime.utc(2026, 9, 17, 12);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.text('Starting 9/18/2026'), findsOneWidget);
      // Also cross a boundary while foregrounded, without a lifecycle event.
      now = DateTime.utc(2026, 9, 20, 12);
      await tapCalendar(tester, find.byKey(const Key('calendar-start-date')));
      expect(find.byType(DatePickerDialog), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tapCalendar(tester, find.text('OK'));
      expect(find.text('Starting 9/21/2026'), findsOneWidget);
    },
  );
  for (final (zone, instant, end) in [
    (
      'America/Denver',
      DateTime.utc(2026, 9, 14, 5, 30),
      '2026-09-21T06:00:00.000Z',
    ),
    ('Etc/UTC', DateTime.utc(2026, 9, 13, 23, 30), '2026-09-21T00:00:00.000Z'),
    (
      'Asia/Kathmandu',
      DateTime.utc(2026, 9, 13, 17, 45),
      '2026-09-20T18:15:00.000Z',
    ),
  ]) {
    testWidgets('late-night $zone search still offers tomorrow', (
      tester,
    ) async {
      final repo = CalendarRepository();
      repo.status.addAll({
        'connected': true,
        'status': 'connected',
        'selected_calendar_ids': ['one'],
        'time_zone': zone,
      });
      final owner = await calendarController(repo);
      await tester.pumpWidget(
        MaterialApp(
          home: CalendarSlotPicker(controller: owner, now: () => instant),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Starting 9/14/2026'), findsOneWidget);
      await tapCalendar(tester, find.byKey(const Key('calendar-find-times')));
      expect(find.byKey(const Key('calendar-slot-0')), findsOneWidget);
      final start = DateTime.parse(
        repo.availabilityQuery!['time_min'] as String,
      );
      expect(start.isAfter(instant.add(const Duration(hours: 1))), isTrue);
      expect(start.isBefore(instant.add(const Duration(hours: 2))), isTrue);
      expect(repo.availabilityQuery!['time_max'], end);
      expect(repo.availabilityQuery!['time_zone'], zone);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets(
    'changed Calendar generation invalidates selected offers before review',
    (tester) async {
      final repo = CalendarRepository();
      repo.status.addAll({
        'connected': true,
        'status': 'connected',
        'selected_calendar_ids': ['one'],
      });
      final controller = await calendarController(repo);
      await tester.pumpWidget(
        MaterialApp(home: CalendarSlotPicker(controller: controller)),
      );
      await tester.pumpAndSettle();
      await tapCalendar(tester, find.byKey(const Key('calendar-find-times')));
      await tapCalendar(tester, find.byKey(const Key('calendar-slot-0')));
      repo.status['generation'] = 5;
      await tapCalendar(tester, find.byKey(const Key('calendar-use-times')));
      expect(find.byKey(const Key('calendar-slot-0')), findsNothing);
      expect(
        find.text('Calendar preferences changed. Find available times again.'),
        findsOneWidget,
      );
    },
  );
  setUpAll(() async {
    const fontDirectory = String.fromEnvironment('CALENDAR_FONT_DIR');
    if (fontDirectory.isNotEmpty) {
      final font = FontLoader('Roboto');
      font.addFont(
        Future.value(
          ByteData.sublistView(
            await File('$fontDirectory/Roboto-Regular.ttf').readAsBytes(),
          ),
        ),
      );
      font.addFont(
        Future.value(
          ByteData.sublistView(
            await File('$fontDirectory/Roboto-Bold.ttf').readAsBytes(),
          ),
        ),
      );
      await font.load();
      final icons = FontLoader('MaterialIcons');
      icons.addFont(
        Future.value(
          ByteData.sublistView(
            await File(
              '$fontDirectory/MaterialIcons-Regular.otf',
            ).readAsBytes(),
          ),
        ),
      );
      await icons.load();
    }
  });
  testWidgets(
    'OAuth opens only the approved system-browser link and resumes current attempt',
    (tester) async {
      final launches = <MethodCall>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/url_launcher'),
        (call) async {
          launches.add(call);
          return true;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          const MethodChannel('plugins.flutter.io/url_launcher'),
          null,
        ),
      );
      final repo = CalendarRepository(),
          controller = await calendarController();
      final owner = await calendarController(repo);
      await mountCalendar(tester, owner);
      await tester.pumpAndSettle();
      await tapCalendar(tester, find.text('Connect Google Calendar'));
      expect(
        launches.single.arguments['url'],
        'https://connect.nango.dev/session',
      );
      expect(launches.single.arguments['useWebView'], false);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(repo.attempts, ['new-attempt']);
      expect(launches, hasLength(1));
      expect(find.textContaining('Personal calendar'), findsOneWidget);
      controller.dispose();
    },
  );
  testWidgets('untrusted OAuth URL is never launched', (tester) async {
    final launches = <MethodCall>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/url_launcher'),
      (call) async {
        launches.add(call);
        return true;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/url_launcher'),
        null,
      ),
    );
    final repo = CalendarRepository()
      ..connectLink = 'https://connect.nango.dev.evil.test/steal';
    await mountCalendar(tester, await calendarController(repo));
    await tester.pumpAndSettle();
    await tapCalendar(tester, find.text('Connect Google Calendar'));
    expect(launches, isEmpty);
    expect(
      find.textContaining('secure Google connection could not be opened'),
      findsOneWidget,
    );
  });
  testWidgets('late OAuth creation after invalidation never launches consent', (
    tester,
  ) async {
    final launches = <MethodCall>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/url_launcher'),
      (call) async {
        launches.add(call);
        return true;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('plugins.flutter.io/url_launcher'),
        null,
      ),
    );
    final repo = CalendarRepository()..connecting = Completer<Json>();
    final controller = await calendarController(repo);
    await mountCalendar(tester, controller);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Connect Google Calendar'));
    await tester.tap(find.text('Connect Google Calendar'));
    await tester.pump();
    controller.invalidateSession();
    repo.connecting!.complete({
      'attempt_id': 'old',
      'connect_link': 'https://connect.nango.dev/session',
    });
    await tester.pumpAndSettle();
    expect(launches, isEmpty);
  });
  testWidgets('disconnect invalidates an in-flight private calendar list', (
    tester,
  ) async {
    final repo = CalendarRepository()..calendarList = Completer<Json>();
    repo.status.addAll({'connected': true, 'status': 'connected'});
    final controller = await calendarController(repo);
    await mountCalendar(tester, controller);
    await tester.pump();
    await tester.ensureVisible(find.byKey(const Key('calendar-disconnect')));
    await tester.tap(find.byKey(const Key('calendar-disconnect')));
    await tester.pumpAndSettle();
    repo.calendarList!.complete({
      'calendars': [
        {'id': 'old', 'summary': 'Old private calendar'},
      ],
    });
    await tester.pumpAndSettle();
    expect(find.text('Old private calendar'), findsNothing);
    expect(find.text('Connect Google Calendar'), findsOneWidget);
  });
  testWidgets('sync issue retry targets just the selected owned booking', (
    tester,
  ) async {
    final repo = CalendarRepository();
    repo.status.addAll({
      'connected': true,
      'status': 'connected',
      'sync_issues': [
        {
          'source_kind': 'outreach',
          'source_id': 'booking-one',
          'status': 'conflict',
        },
      ],
    });
    await mountCalendar(tester, await calendarController(repo), scale: 1.8);
    await tester.pumpAndSettle();
    await tapCalendar(tester, find.text('Retry Calendar copy'));
    expect(repo.retried, {
      'source_kind': 'outreach',
      'source_id': 'booking-one',
    });
    expect(find.text('Google Calendar conflict'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'available-time picker limits choices and clears them when inputs change',
    (tester) async {
      final repo = CalendarRepository();
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
          theme: calendarProofTheme(),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: TextScaler.linear(1.8)),
            child: child!,
          ),
          home: RepaintBoundary(
            key: const Key('calendar-proof'),
            child: CalendarSlotPicker(controller: controller),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tapCalendar(tester, find.byKey(const Key('calendar-find-times')));
      expect(repo.availabilityQuery?['time_zone'], 'America/Denver');
      expect(repo.availabilityQuery?['duration_minutes'], 60);
      for (var i = 0; i < 3; i++) {
        await tapCalendar(tester, find.byKey(ValueKey('calendar-slot-$i')));
      }
      await tapCalendar(tester, find.byKey(const Key('calendar-slot-3')));
      expect(find.text('Choose up to three times.'), findsOneWidget);
      expect(find.text('Use 3 times'), findsOneWidget);
      await tester.ensureVisible(find.byKey(const Key('calendar-slot-0')));
      await tester.pumpAndSettle();
      await calendarProof(tester, 'calendar-slots-large-390');
      await tapCalendar(tester, find.byKey(const Key('calendar-duration')));
      await tapCalendar(tester, find.text('90 minutes').last);
      expect(find.byKey(const Key('calendar-slot-0')), findsNothing);
      expect(find.text('Use 3 times'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('late availability cannot display another account’s slots', (
    tester,
  ) async {
    final repo = CalendarRepository()..availability = Completer<Json>();
    repo.status.addAll({
      'connected': true,
      'status': 'connected',
      'selected_calendar_ids': ['one'],
    });
    final controller = await calendarController(repo);
    await tester.pumpWidget(
      MaterialApp(home: CalendarSlotPicker(controller: controller)),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('calendar-find-times')));
    await tester.tap(find.byKey(const Key('calendar-find-times')));
    await tester.pump();
    controller.invalidateSession();
    repo.availability!.complete({
      'slots': [
        {'start': '2026-11-02T16:00:00Z', 'end': '2026-11-02T17:00:00Z'},
      ],
    });
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('calendar-slot-0')), findsNothing);
    expect(find.text('Sign in to view your saved details.'), findsOneWidget);
  });
  testWidgets('calendar setup explains busy access and offers connection', (
    tester,
  ) async {
    final controller = await calendarController();
    await mountCalendar(tester, controller);
    await tester.pumpAndSettle();
    expect(find.text('Google Calendar'), findsOneWidget);
    expect(find.textContaining('busy'), findsWidgets);
    expect(find.text('Connect Google Calendar'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await calendarProof(tester, 'calendar-setup-390');
  });
  testWidgets(
    'restart recovers the server attempt and saves explicit private preferences',
    (tester) async {
      final repo = CalendarRepository()..status['status'] = 'connecting';
      repo.status['attempt_id'] = 'server-attempt';
      final controller = await calendarController(repo);
      await mountCalendar(tester, controller, scale: 1.8);
      await tester.pumpAndSettle();
      expect(repo.attempts, ['server-attempt']);
      expect(find.textContaining('Personal calendar'), findsOneWidget);
      await calendarProof(tester, 'calendar-preferences-large-390-top');
      await tapCalendar(tester, find.byKey(const Key('calendar-choice-one')));
      await tapCalendar(tester, find.byKey(const Key('calendar-save')));
      expect(repo.preferences, {
        'selected_calendar_ids': ['one'],
        'time_zone': 'Etc/UTC',
        'sync_confirmed': false,
      });
      expect(controller.messages, isEmpty);
      expect(tester.takeException(), isNull);
      await calendarProof(tester, 'calendar-preferences-large-390-bottom');
    },
  );
  testWidgets(
    'late reconcile after account invalidation hides private labels',
    (tester) async {
      final repo = CalendarRepository()..reconcile = Completer<Json>();
      repo.status.addAll({'status': 'connecting', 'attempt_id': 'old-attempt'});
      final controller = await calendarController(repo);
      await mountCalendar(tester, controller);
      await tester.pump();
      controller.invalidateSession();
      repo.reconcile!.complete({
        ...repo.status,
        'connected': true,
        'status': 'connected',
      });
      await tester.pumpAndSettle();
      expect(find.textContaining('Personal calendar'), findsNothing);
      expect(find.text('Sign in to view your saved details.'), findsOneWidget);
    },
  );
  testWidgets('sample Calendar never offers a real OAuth launch', (
    tester,
  ) async {
    final controller = await calendarController(DemoPlusRepository());
    await mountCalendar(tester, controller);
    await tester.pumpAndSettle();
    expect(find.textContaining('Sample'), findsWidgets);
    expect(find.text('Connect Google Calendar'), findsNothing);
  });
}
