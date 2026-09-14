import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/pending_request_store.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/services/calendar_time.dart';
import 'package:estimoto_plus/services/customer_workspace.dart';

class DelayedPendingStore extends MemoryPendingRequestStore {
  Completer<void>? writing;
  @override
  Future<void> write(String customerId, PendingRequest request) async {
    await writing?.future;
    await super.write(customerId, request);
  }
}

class RequestRepository extends DemoPlusRepository {
  int sends = 0;
  final bodies = <Json>[];
  final keys = <String>[];
  PlusApiException? failure;
  @override
  Future<Json> createRequest(Json body, String key) async {
    sends++;
    bodies.add(jsonDecode(jsonEncode(body)) as Json);
    keys.add(key);
    if (failure != null) throw failure!;
    return {'id': 'request'};
  }
}

void main() {
  test(
    'outreach pending review freezes slots and keeps its zone outside the send body',
    () {
      final body = <String, dynamic>{
        'proposed_slots': ['2026-11-02T16:00:00Z'],
        'calendar_check': true,
      };
      final pending = PendingWorkspaceWrite(
        body: body,
        key: 'draft',
        reviewTimeZone: 'America/Denver',
      );
      (body['proposed_slots'] as List)[0] = 'changed';
      final restored = PendingWorkspaceWrite.fromJson(
        jsonDecode(jsonEncode(pending.toJson())) as Json,
      );
      expect(restored.body['proposed_slots'], ['2026-11-02T16:00:00Z']);
      expect(restored.reviewTimeZone, 'America/Denver');
      expect(restored.body.containsKey('review_time_zone'), false);
      expect(
        () => (restored.body['proposed_slots'] as List).add('another'),
        throwsUnsupportedError,
      );
    },
  );
  test(
    'checked selection carries exact immutable instants without calendar names',
    () {
      final response = <String, dynamic>{
        'slots': [
          {'start': '2026-11-02T16:00:00Z', 'end': '2026-11-02T17:00:00Z'},
        ],
        'time_zone': 'America/Denver',
        'duration_minutes': 60,
        'generation': 4,
        'checked_at': '2026-11-01T12:00:00Z',
      };
      final choice = CalendarSelection.fromResponse(
        response,
        rowsOf(response, 'slots'),
      );
      (response['slots'] as List).clear();
      expect(choice.requestFields, {
        'calendar_check': true,
        'duration_minutes': 60,
        'calendar_generation': 4,
        'proposed_slots': ['2026-11-02T16:00:00Z'],
      });
      expect(choice.label, contains('America/Denver, UTC-07:00'));
      expect(choice.preferredTime.length, lessThanOrEqualTo(200));
      expect(
        () => choice.slots.first['start'] = 'changed',
        throwsUnsupportedError,
      );
    },
  );
  test(
    'IANA labels follow DST and non-hour offsets, independent of device zone',
    () {
      expect(
        calendarSlotLabel('2026-10-30T15:00:00Z', 'America/Denver'),
        contains('9:00 AM'),
      );
      expect(
        calendarSlotLabel('2026-11-02T16:00:00Z', 'America/Denver'),
        contains('UTC-07:00'),
      );
      expect(
        calendarSlotLabel('2026-10-30T15:00:00Z', 'America/Phoenix'),
        contains('8:00 AM'),
      );
      expect(
        calendarSlotLabel('2026-11-02T16:00:00Z', 'Asia/Kathmandu'),
        contains('UTC+05:45'),
      );
      expect(
        calendarSlotLabel('2026-11-02T16:00:00Z', 'Etc/UTC'),
        contains('4:00 PM'),
      );
      expect(validCalendarZone('MST'), isFalse);
    },
  );
  test('date window uses chosen IANA midnight across DST', () {
    final body = calendarAvailabilityBody(
      date: DateTime(2026, 10, 30),
      days: 5,
      timeZone: 'America/Denver',
      duration: 90,
      dayStart: 9,
      dayEnd: 17,
    );
    expect(body['time_min'], '2026-10-30T06:00:00.000Z');
    expect(body['time_max'], '2026-11-04T07:00:00.000Z');
    expect(body['duration_minutes'], 90);
  });
  test(
    'a 14-day fall-DST query stays within the server elapsed-time limit',
    () {
      final body = calendarAvailabilityBody(
        date: DateTime(2026, 11, 1),
        days: 14,
        timeZone: 'America/Denver',
        duration: 60,
        dayStart: 9,
        dayEnd: 17,
      );
      expect(
        calendarInstant(
          body['time_max'] as String,
        ).difference(calendarInstant(body['time_min'] as String)),
        lessThanOrEqualTo(const Duration(days: 14)),
      );
    },
  );

  test('Calendar repository uses eight exact private API contracts', () async {
    final received = <(String, String, Object?)>[];
    final dynamic api = ApiPlusRepository(
      baseUrl: 'https://plus.example.test',
      token: () async => 'customer-token',
      client: MockClient((request) async {
        expect(request.headers['Authorization'], 'Bearer customer-token');
        expect(request.followRedirects, isFalse);
        received.add((
          request.method,
          request.url.path,
          request.body.isEmpty ? null : jsonDecode(request.body),
        ));
        return http.Response('{"calendars":[],"slots":[]}', 200);
      }),
    );
    await api.getCalendarStatus();
    await api.connectGoogleCalendar();
    await api.reconcileGoogleCalendar('attempt-id');
    await api.listGoogleCalendars();
    await api.saveCalendarPreferences({'time_zone': 'Etc/UTC'});
    await api.findCalendarAvailability({'duration_minutes': 60});
    await api.disconnectGoogleCalendar();
    await api.retryCalendarSync({'source_kind': 'request', 'source_id': 'one'});
    expect(received.map((v) => [v.$1, v.$2, v.$3]).toList(), [
      ['GET', '/v1/calendar/google/status', null],
      ['POST', '/v1/calendar/google/connect', null],
      [
        'POST',
        '/v1/calendar/google/reconcile',
        {'attempt_id': 'attempt-id'},
      ],
      ['GET', '/v1/calendar/google/calendars', null],
      [
        'PUT',
        '/v1/calendar/google/preferences',
        {'time_zone': 'Etc/UTC'},
      ],
      [
        'POST',
        '/v1/calendar/google/availability',
        {'duration_minutes': 60},
      ],
      ['DELETE', '/v1/calendar/google/connection', null],
      [
        'POST',
        '/v1/calendar/google/sync/retry',
        {'source_kind': 'request', 'source_id': 'one'},
      ],
    ]);
  });

  test(
    'Calendar rejection exposes safe recovery but never provider text',
    () async {
      for (final (status, detail, expected) in [
        (
          422,
          'A proposed time is now busy. Choose new appointment times.',
          'A proposed time is now busy. Choose new appointment times.',
        ),
        (
          503,
          'Calendar availability could not be verified. Try again.',
          'Calendar availability could not be verified. Try again.',
        ),
        (
          422,
          'Private calendar: medical appointment token=secret',
          'Check the details and try again.',
        ),
      ]) {
        final api = ApiPlusRepository(
          baseUrl: 'https://plus.example.test',
          token: () async => 'token',
          client: MockClient(
            (_) async => http.Response(jsonEncode({'detail': detail}), status),
          ),
        );
        await expectLater(
          api.createRequest({}, 'one'),
          throwsA(
            isA<PlusApiException>().having(
              (e) => e.message,
              'safe message',
              expected,
            ),
          ),
        );
      }
    },
  );

  test('pending request detaches and freezes nested selected slots', () {
    final slots = ['2026-11-02T16:00:00Z'];
    final pending = PendingRequest(
      body: {'proposed_slots': slots},
      key: 'one',
      provider: ProviderProfile.fromJson({'id': 'shop'}),
    );
    slots[0] = '2026-11-02T17:00:00Z';
    expect(pending.body['proposed_slots'], ['2026-11-02T16:00:00Z']);
    expect(
      () => (pending.body['proposed_slots'] as List).add('later'),
      throwsUnsupportedError,
    );
    expect(() => pending.body['calendar_check'] = true, throwsUnsupportedError);
  });

  test('account invalidation while persisting prevents request send', () async {
    final repository = RequestRepository(), store = DelayedPendingStore();
    final controller = PlusController(repository, pendingStore: store);
    await controller.refresh();
    store.writing = Completer<void>();
    final result = controller.sendRequest({
      'description': 'Repair',
    }, controller.snapshot!.providers.first);
    await Future<void>.delayed(Duration.zero);
    controller.invalidateSession();
    store.writing!.complete();
    await expectLater(result, throwsA(isA<PlusApiException>()));
    expect(repository.sends, 0);
    controller.dispose();
  });

  test(
    'uncertain legacy retry keeps exact body and key; 422 clears it',
    () async {
      final repository = RequestRepository()
        ..failure = const PlusApiException('Unavailable', 503);
      final store = MemoryPendingRequestStore();
      final controller = PlusController(repository, pendingStore: store);
      await controller.refresh();
      final body = <String, dynamic>{
        'description': 'Existing request',
        'preferred_time': 'Next week',
      };
      final provider = controller.snapshot!.providers.first;
      await expectLater(
        controller.sendRequest(body, provider),
        throwsA(isA<PlusApiException>()),
      );
      final original = controller.pendingRequest!;
      repository.failure = const PlusApiException('Choose new times.', 422);
      await expectLater(
        controller.sendRequest(original.body, provider),
        throwsA(isA<PlusApiException>()),
      );
      expect(repository.keys[0], repository.keys[1]);
      expect(repository.bodies, [body, body]);
      expect(repository.bodies.last.containsKey('calendar_check'), isFalse);
      expect(controller.pendingRequest, isNull);
      expect(await store.read(controller.snapshot!.profile.id), isNull);
      controller.dispose();
    },
  );
}
