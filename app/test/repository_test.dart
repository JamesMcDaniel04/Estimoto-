import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/repository.dart';

void main() {
  test(
    'API sends bearer and idempotency key to the configured origin',
    () async {
      final repository = ApiPlusRepository(
        baseUrl: 'https://plus.example.com',
        token: () async => 'verified-token',
        client: MockClient((request) async {
          expect(
            request.url.toString(),
            'https://plus.example.com/v1/requests',
          );
          expect(request.headers['Authorization'], 'Bearer verified-token');
          expect(request.headers['Idempotency-Key'], 'request-one');
          expect(jsonDecode(request.body)['share_contact'], isTrue);
          return http.Response('{"id":"r1"}', 201);
        }),
      );
      await repository.createRequest({'share_contact': true}, 'request-one');
    },
  );

  test(
    'API rejects expired sessions and does not return sample data',
    () async {
      final repository = ApiPlusRepository(
        baseUrl: 'https://plus.example.com',
        token: () async => 'expired',
        client: MockClient(
          (_) async => http.Response('{"detail":"Unauthorized"}', 401),
        ),
      );
      expect(repository.bootstrap(), throwsA(isA<PlusApiException>()));
    },
  );

  test(
    'demo request is idempotent and cannot pretend to book a technician',
    () async {
      final repository = DemoPlusRepository();
      final snapshot = await repository.bootstrap();
      final body = <String, dynamic>{
        'vehicle_id': snapshot.vehicles.first.id,
        'provider_id': snapshot.providers.first.id,
        'specialty': 'pdr',
        'description': 'A small dent in the door.',
        'preferred_time': 'Next week',
        'share_contact': true,
      };
      final first = await repository.createRequest(body, 'request-one');
      final second = await repository.createRequest(body, 'request-one');
      expect(first['id'], second['id']);
      expect(first['status'], 'requested');
      expect(first['delivery_status'], 'local_preview');
      expect(first['scheduled_at'], isNull);
      await repository.cancelRequest(first['id'] as String);
      expect((await repository.bootstrap()).requests.last.status, 'cancelled');
    },
  );

  test('demo saves vehicle and reminder within a session', () async {
    final repository = DemoPlusRepository();
    final created = await repository.saveVehicle({
      'year': 2023,
      'make': 'Honda',
      'model': 'Civic',
      'mileage': 18000,
    });
    final reminder = await repository.addReminder({
      'vehicle_id': created['id'],
      'title': 'Oil change',
      'due_mileage': 20000,
    });
    expect(
      (await repository.bootstrap()).vehicles.any((v) => v.id == created['id']),
      isTrue,
    );
    await repository.completeReminder(reminder['id'] as String);
    expect((await repository.bootstrap()).reminders.last.completed, isTrue);
  });
  test('only explicit request rejection decodes as safe to replace', () async {
    for (final code in [null, 'request_not_created']) {
      final api = ApiPlusRepository(
        baseUrl: 'https://plus.example.com',
        token: () async => 'token',
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({'detail': 'Conflict', 'code': code}),
            409,
          ),
        ),
      );
      await expectLater(
        api.createRequest({'share_contact': true}, 'one'),
        throwsA(isA<PlusApiException>().having((e) => e.code, 'code', code)),
      );
      api.close();
    }
  });
  test(
    'demo quick prompts include common care and urgent repair guidance',
    () async {
      final repo = DemoPlusRepository();
      final vehicleId = (await repo.bootstrap()).vehicles.first.id;
      final care = await repo.askAssistant({
        'message': 'How do I check tire pressure?',
        'vehicle_id': vehicleId,
      });
      expect(care.reply, contains('placard'));
      expect(care.reply, contains('gauge'));
      for (final phrase in [
        'Find repair for brake failure',
        'Find repair because my brakes failed',
      ]) {
        final urgent = await repo.askAssistant({
          'message': phrase,
          'vehicle_id': vehicleId,
          'postal_code': '80202',
        });
        expect(urgent.reply, contains('professional'));
        expect(urgent.videos, isEmpty);
      }
    },
  );
}
