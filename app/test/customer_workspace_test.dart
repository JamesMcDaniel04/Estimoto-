import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/services/customer_workspace.dart';
import 'package:estimoto_plus/state/plus_controller.dart';

class _BlockedStore extends MemoryWorkspaceWriteStore {
  final entered = Completer<void>(), release = Completer<void>();
  @override
  Future<void> write(String scope, PendingWorkspaceWrite value) async {
    entered.complete();
    await release.future;
    await super.write(scope, value);
  }
}

class _BrokenStore extends MemoryWorkspaceWriteStore {
  @override
  Future<void> write(String scope, PendingWorkspaceWrite value) async =>
      throw StateError('Storage unavailable');
}

Future<PlusController> _controller() async {
  final controller = PlusController(DemoPlusRepository());
  await controller.refresh();
  return controller;
}

void main() {
  test(
    'API collection, draft, authorize and knowledge use exact contracts',
    () async {
      final requests = <http.Request>[];
      final repository = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () async => 'account-token',
        client: MockClient((request) async {
          requests.add(request);
          if (request.method == 'GET' &&
              ['/v1/my-shops', '/v1/shop-outreach'].contains(request.url.path)) {
            return http.Response('[{"id":"owned"}]', 200);
          }
          return http.Response('{"id":"receipt"}', 200);
        }),
      );
      expect((await repository.listMyShops()).single['id'], 'owned');
      expect((await repository.listShopOutreach()).single['id'], 'owned');
      await repository.createShopOutreach({
        'shop_id': 's1',
        'proposed_slots': ['2026-10-01T09:00:00-06:00'],
      }, 'draft-key');
      await repository.authorizeShopOutreach('draft/id', {
        'share_contact': true,
        'review_hash': 'hash',
      }, 'authorize-key');
      await repository.addKnowledgeRecord({'vehicle_id': 'v1'}, 'history-key');
      await repository.saveKnowledgePreferences({
        'share_aggregate_insights': false,
      });
      expect(requests[2].headers['Idempotency-Key'], 'draft-key');
      expect(requests[3].url.toString(), contains('draft%2Fid/authorize'));
      expect(requests[3].headers['Idempotency-Key'], 'authorize-key');
      expect(jsonDecode(requests[3].body), {
        'share_contact': true,
        'review_hash': 'hash',
      });
      expect(requests[4].headers['Idempotency-Key'], 'history-key');
      expect(requests.last.method, 'PUT');
      expect(jsonDecode(requests.last.body), {
        'share_aggregate_insights': false,
      });
      expect(
        requests.every(
          (r) => r.headers['Authorization'] == 'Bearer account-token',
        ),
        isTrue,
      );
    },
  );

  test(
    'collection support does not accept an array as an account bootstrap',
    () async {
      final repository = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () async => 'token',
        client: MockClient((_) async => http.Response('[]', 200)),
      );
      await expectLater(
        repository.bootstrap(),
        throwsA(isA<PlusApiException>()),
      );
    },
  );

  test(
    'lost receipt replays frozen body and UUID after service recreation',
    () async {
      final controller = await _controller();
      final store = MemoryWorkspaceWriteStore();
      var service = CustomerWorkspace(controller, store: store);
      final sent = <(Json, String)>[];
      Future<Json> send(Json body, String key) async {
        sent.add((body, key));
        if (sent.length == 1) throw const PlusApiException('Connection lost');
        return {'id': 'saved-once'};
      }

      final body = <String, dynamic>{
        'vehicle_id': 'demo-audi',
        'notes': 'Keep this exact text',
        'items': ['a'],
      };
      await expectLater(
        service.write('history-record', body, send),
        throwsA(isA<PlusApiException>()),
      );
      body['notes'] = 'changed after failure';
      service = CustomerWorkspace(controller, store: store);
      final pending = (await service.pending('history-record'))!;
      expect(pending.body['notes'], 'Keep this exact text');
      await expectLater(
        service.write('history-record', body, send),
        throwsA(isA<PlusApiException>()),
      );
      expect(sent.length, 1);
      await service.write('history-record', pending.body, send);
      expect(sent[0].$1, sent[1].$1);
      expect(sent[0].$2, sent[1].$2);
      expect(
        sent[0].$2,
        matches(
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
          ),
        ),
      );
      expect(await service.pending('history-record'), isNull);
    },
  );

  test('secure storage failure prevents a network mutation', () async {
    final service = CustomerWorkspace(
      await _controller(),
      store: _BrokenStore(),
    );
    var calls = 0;
    await expectLater(
      service.write('draft', {}, (_, _) async {
        calls++;
        return {};
      }),
      throwsStateError,
    );
    expect(calls, 0);
  });

  test(
    'auth switch during persistence prevents mutation for new account',
    () async {
      final controller = await _controller();
      final store = _BlockedStore();
      final service = CustomerWorkspace(controller, store: store);
      var calls = 0;
      final future = service.write('draft', {'private': 'old customer'}, (
        _,
        _,
      ) async {
        calls++;
        return {};
      });
      final failure = expectLater(future, throwsA(isA<PlusApiException>()));
      await store.entered.future;
      controller.invalidateSession();
      store.release.complete();
      await failure;
      expect(calls, 0);
      expect(service.current, isFalse);
    },
  );

  test(
    'late old-account receipt is not returned and other account pending stays private',
    () async {
      final controller = await _controller();
      final store = MemoryWorkspaceWriteStore();
      final service = CustomerWorkspace(controller, store: store);
      final sent = Completer<void>(), receipt = Completer<Json>();
      final future = service.write('draft', {'private': 'old customer'}, (
        _,
        _,
      ) {
        sent.complete();
        return receipt.future;
      });
      final failure = expectLater(future, throwsA(isA<PlusApiException>()));
      await sent.future;
      controller.invalidateSession();
      receipt.complete({'private_receipt': 'old customer'});
      await failure;
      expect(await store.read('new-customer/draft'), isNull);
    },
  );

  test(
    'concurrent screens cannot authorize the same operation twice',
    () async {
      final controller = await _controller(),
          store = MemoryWorkspaceWriteStore();
      final first = CustomerWorkspace(controller, store: store),
          second = CustomerWorkspace(controller, store: store);
      final entered = Completer<void>(), result = Completer<Json>();
      var calls = 0;
      final future = first.write('authorize/x', {}, (_, _) {
        calls++;
        entered.complete();
        return result.future;
      });
      await entered.future;
      await expectLater(
        second.write('authorize/x', {}, (_, _) async {
          calls++;
          return {};
        }),
        throwsA(isA<PlusApiException>()),
      );
      result.complete({'id': 'x'});
      await future;
      expect(calls, 1);
    },
  );

  test(
    'definite rejection permits corrected body while ambiguity retains identity',
    () async {
      final service = CustomerWorkspace(
        await _controller(),
        store: MemoryWorkspaceWriteStore(),
      );
      await expectLater(
        service.write('record', {
          'bad': true,
        }, (_, _) async => throw const PlusApiException('Invalid', 422)),
        throwsA(isA<PlusApiException>()),
      );
      expect(await service.pending('record'), isNull);
      await expectLater(
        service.write('record', {
          'corrected': true,
        }, (_, _) async => throw const PlusApiException('Unknown', 503)),
        throwsA(isA<PlusApiException>()),
      );
      expect((await service.pending('record'))!.body, {'corrected': true});
    },
  );

  test(
    'demo saved shop edits never mutate an existing review and never send',
    () async {
      final repository = DemoPlusRepository();
      final shop = await repository.saveMyShop({
        'name': 'Original shop',
        'email': 'original@example.test',
        'phone': '',
        'address': '',
      });
      final body = <String, dynamic>{
        'shop_id': shop['id'],
        'vehicle_id': 'demo-audi',
        'service_summary': 'Oil change',
        'proposed_slots': [
          offsetTimestamp(DateTime.now().add(const Duration(days: 2))),
        ],
      };
      final draft = await repository.createShopOutreach(body, 'draft');
      await repository.saveMyShop({
        'name': 'Changed shop',
        'email': 'changed@example.test',
        'phone': '',
        'address': '',
      }, id: shop['id'] as String);
      await repository.saveProfile({'name': 'Changed customer'});
      final saved = await repository.getShopOutreach(draft['id'] as String);
      expect(saved['recipient_email'], 'original@example.test');
      expect((saved['shared_contact'] as Map)['name'], 'Alex Morgan');
      final authorized = await repository.authorizeShopOutreach(
        draft['id'] as String,
        {'share_contact': true, 'review_hash': draft['review_hash']},
        'auth',
      );
      expect(authorized['delivery_status'], 'local_preview');
      expect(authorized['status'], 'draft');
      await repository.deleteMyShop(shop['id'] as String);
      expect(await repository.listMyShops(), isEmpty);
      expect(await repository.listShopOutreach(), hasLength(1));
    },
  );

  test(
    'insights default off and revocation leaves personal history available',
    () async {
      final repository = DemoPlusRepository();
      expect((await repository.getKnowledge())['preferences'], {
        'share_aggregate_insights': false,
      });
      final record = await repository.addKnowledgeRecord({
        'vehicle_id': 'demo-audi',
        'service_type': 'oil_change',
        'service_date': '2026-09-01',
        'parts_source': 'Local parts store',
      }, 'history');
      await repository.addKnowledgeRecord({
        'vehicle_id': 'demo-audi',
        'service_type': 'oil_change',
        'service_date': '2026-09-01',
        'parts_source': 'Local parts store',
      }, 'history');
      await repository.saveKnowledgePreferences({
        'share_aggregate_insights': true,
      });
      await repository.saveKnowledgePreferences({
        'share_aggregate_insights': false,
      });
      final data = await repository.getKnowledge();
      expect(data['preferences'], {'share_aggregate_insights': false});
      expect(data['records'], hasLength(1));
      expect((data['records'] as List).single['source'], 'customer_reported');
      await repository.deleteKnowledgeRecord(record['id'] as String);
      expect((await repository.getKnowledge())['records'], isEmpty);
    },
  );

  test(
    'offered timestamps are timezone qualified and retain the same instant',
    () {
      final time = DateTime(2026, 10, 14, 9, 30);
      final encoded = offsetTimestamp(time);
      expect(encoded, matches(RegExp(r'[+-]\d\d:\d\d$')));
      expect(DateTime.parse(encoded).isAtSameMomentAs(time), isTrue);
      expect(localSlotLabel(encoded), contains('UTC'));
      expect(
        offsetTimestamp(DateTime.utc(2026, 10, 14, 9, 30)),
        '2026-10-14T09:30:00.000+00:00',
      );
    },
  );
}
