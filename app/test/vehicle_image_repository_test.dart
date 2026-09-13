import 'dart:typed_data';

import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test(
    'vehicle images use private authenticated bytes and a source label',
    () async {
      final repo = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () async => 'customer-token',
        client: MockClient((request) async {
          expect(request.url.path, '/v1/vehicles/vehicle-a/image');
          expect(request.headers['Authorization'], 'Bearer customer-token');
          expect(request.followRedirects, isFalse);
          return http.Response.bytes(
            [1, 2, 3],
            200,
            headers: {
              'content-type': 'image/webp',
              'x-vehicle-image-source': 'carsxe',
            },
          );
        }),
      );
      final image = await repo.getVehicleImage('vehicle-a');
      expect(image!.source, 'carsxe');
      expect(image.bytes, [1, 2, 3]);
      repo.close();
    },
  );

  test('no representative image is an empty result, never demo data', () async {
    final repo = ApiPlusRepository(
      baseUrl: 'https://plus.example.test',
      token: () async => 'customer-token',
      client: MockClient((_) async => http.Response('', 204)),
    );
    expect(await repo.getVehicleImage('vehicle-a'), isNull);
    repo.close();
  });

  test('HTML and unauthorized image responses are rejected', () async {
    for (final status in [200, 401]) {
      final repo = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () async => 'customer-token',
        client: MockClient(
          (_) async => http.Response(
            '<html/>',
            status,
            headers: {'content-type': 'text/html'},
          ),
        ),
      );
      await expectLater(
        repo.getVehicleImage('vehicle-a'),
        throwsA(isA<PlusApiException>()),
      );
      repo.close();
    }
  });

  test('oversized and unsupported uploads never leave the client', () async {
    var calls = 0;
    final repo = ApiPlusRepository(
      baseUrl: 'https://plus.example.test',
      token: () async => 'customer-token',
      client: MockClient((_) async {
        calls++;
        return http.Response('{}', 200);
      }),
    );
    await expectLater(
      repo.uploadVehicleImage('vehicle-a', Uint8List(1), 'image.svg'),
      throwsA(isA<PlusApiException>()),
    );
    await expectLater(
      repo.uploadVehicleImage(
        'vehicle-a',
        Uint8List(10 * 1024 * 1024 + 1),
        'image.jpg',
      ),
      throwsA(isA<PlusApiException>()),
    );
    expect(calls, 0);
    repo.close();
  });
}
