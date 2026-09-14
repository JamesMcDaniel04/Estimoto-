import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/services/receipt_pending.dart';

ReceiptPending fixture() => ReceiptPending(
  ownerId: 'owner',
  recordId: 'record-1',
  operationId: '11111111-1111-4111-8111-111111111111',
  filename: 'work.pdf',
  mimeType: 'application/pdf',
  bytes: Uint8List.fromList('%PDF-1.4'.codeUnits),
);
void main() {
  test(
    'receipt bytes use private guarded requests and a stable multipart key',
    () async {
      final calls = <http.Request>[];
      final repository = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () async => 'secret-test-token',
        client: MockClient((r) async {
          calls.add(r);
          return http.Response(
            r.method == 'GET' ? '%PDF-1.4' : '{"id":"receipt-1"}',
            200,
          );
        }),
      );
      final api = repository.openReceiptRecord(
        'record-1',
        isCurrent: () => true,
      );
      await api.upload(fixture());
      await api.read('receipt-1');
      await api.delete('receipt-1');
      await api.parseTotal('receipt-1');
      await api.applyTotal('receipt-1', 12500);
      expect(calls.map((r) => r.method), [
        'POST',
        'GET',
        'DELETE',
        'POST',
        'POST',
      ]);
      expect(
        calls[3].url.path,
        '/v1/knowledge/records/record-1/receipts/receipt-1/parse-total',
      );
      expect(
        calls[4].url.path,
        '/v1/knowledge/records/record-1/receipts/receipt-1/apply-total',
      );
      expect(calls[4].body, '{"expected_cost_cents":12500}');
      expect(calls.first.url.path, '/v1/knowledge/records/record-1/receipts');
      expect(calls.first.headers['Idempotency-Key'], fixture().operationId);
      expect(calls.first.body, contains('filename="work.pdf"'));
      expect(calls.first.body, contains('application/pdf'));
      expect(calls.first.body, contains('%PDF-1.4'));
      for (final call in calls) {
        expect(call.url.hasQuery, isFalse);
        expect(call.followRedirects, isFalse);
        expect(call.headers['Authorization'], 'Bearer secret-test-token');
      }
    },
  );
  test(
    'sign-out while auth resolves blocks upload, read and delete before I/O',
    () async {
      for (final method in ['upload', 'read', 'delete', 'parse', 'apply']) {
        var active = true, calls = 0;
        final auth = Completer<String?>();
        final repo = ApiPlusRepository(
          baseUrl: 'https://plus.example.test',
          token: () => auth.future,
          client: MockClient((r) async {
            calls++;
            return http.Response('{}', 200);
          }),
        );
        final api = repo.openReceiptRecord('record-1', isCurrent: () => active);
        final Future<dynamic> result = switch (method) {
          'upload' => api.upload(fixture()),
          'read' => api.read('receipt-1'),
          'parse' => api.parseTotal('receipt-1'),
          'apply' => api.applyTotal('receipt-1', null),
          _ => api.delete('receipt-1'),
        };
        active = false;
        auth.complete('another-account');
        await expectLater(result, throwsA(isA<PlusApiException>()));
        expect(calls, 0);
      }
    },
  );
  test(
    'receipt errors preserve definitive status without echoing provider text',
    () async {
      for (final status in [404, 409, 410, 413, 415, 422, 503]) {
        final repo = ApiPlusRepository(
          baseUrl: 'https://plus.example.test',
          token: () async => 'token',
          client: MockClient(
            (r) async => http.Response('{"detail":"PRIVATE SECRET"}', status),
          ),
        );
        await expectLater(
          repo
              .openReceiptRecord('record-1', isCurrent: () => true)
              .upload(fixture()),
          throwsA(
            isA<PlusApiException>()
                .having((e) => e.statusCode, 'status', status)
                .having(
                  (e) => e.message,
                  'safe message',
                  isNot(contains('SECRET')),
                ),
          ),
        );
      }
    },
  );
}
