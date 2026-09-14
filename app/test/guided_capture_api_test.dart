import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/services/guided_capture_pending.dart';

void main() {
  test(
    'capture transport binds path and auth outside the page and preserves exact multipart operation',
    () async {
      final requests = <http.Request>[];
      final dynamic repository = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () async => 'private-token',
        client: MockClient((r) async {
          requests.add(r);
          return http.Response('{}', 200);
        }),
      );
      final dynamic api = repository.openGuidedCapture(
        'estimate-1',
        isCurrent: () => true,
      );
      expect(api.pageUri.toString(), 'https://plus.example.test/capture/');
      await api.state();
      final pending = GuidedCapturePending(
        ownerId: 'customer-1',
        estimateId: 'estimate-1',
        operationId: '11111111-1111-4111-8111-111111111111',
        captureKey: 'vin',
        bodyStyle: 'suv',
        mimeType: 'image/png',
        bytes: Uint8List.fromList([1, 2, 3]),
      );
      await api.save(pending);
      await api.recognize('photo-1');
      await api.confirm({
        'photo_id': 'photo-1',
        'photo_sha256': 'a' * 64,
        'expected_vin': '',
        'vin': '1HGBH41JXMN109186',
      });
      expect(requests.map((r) => r.url.path), [
        '/v1/estimates/estimate-1/capture',
        '/v1/estimates/estimate-1/capture/photos',
        '/v1/estimates/estimate-1/capture/vin/recognize',
        '/v1/estimates/estimate-1/capture/vin/confirm',
      ]);
      for (final request in requests) {
        expect(request.headers['Authorization'], 'Bearer private-token');
        expect(request.url.hasQuery, isFalse);
        expect(request.followRedirects, isFalse);
      }
      expect(requests[1].body, contains(pending.operationId));
      expect(requests[1].body, contains('name="photo"'));
      expect(requests[1].body, contains('image/png'));
      expect(jsonDecode(requests[2].body), {'photo_id': 'photo-1'});
      expect(jsonDecode(requests[3].body)['photo_sha256'], 'a' * 64);
    },
  );
  test(
    'capture account or page invalidation while auth resolves prevents network I/O',
    () async {
      var current = true, sends = 0;
      final token = Completer<String?>();
      final dynamic repository = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () => token.future,
        client: MockClient((r) async {
          sends++;
          return http.Response('{}', 200);
        }),
      );
      final dynamic api = repository.openGuidedCapture(
        'estimate-1',
        isCurrent: () => current,
      );
      final Future<dynamic> request = api.state();
      current = false;
      token.complete('new-account-token');
      await expectLater(request, throwsA(isA<PlusApiException>()));
      expect(sends, 0);
    },
  );
  test(
    'capture errors preserve status and allow only safe known recovery text',
    () async {
      var response = http.Response('{"detail":"secret provider headers"}', 503);
      final dynamic repository = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () async => 'owner',
        client: MockClient((r) async => response),
      );
      final dynamic api = repository.openGuidedCapture(
        'estimate-1',
        isCurrent: () => true,
      );
      await expectLater(
        api.state(),
        throwsA(
          isA<PlusApiException>()
              .having((e) => e.statusCode, 'status', 503)
              .having((e) => e.message, 'message', isNot(contains('secret'))),
        ),
      );
      response = http.Response(
        '{"detail":"This capture expired. Take the photo again."}',
        422,
      );
      await expectLater(
        api.state(),
        throwsA(
          isA<PlusApiException>()
              .having((e) => e.statusCode, 'status', 422)
              .having(
                (e) => e.message,
                'message',
                'This capture expired. Take the photo again.',
              ),
        ),
      );
    },
  );
}
