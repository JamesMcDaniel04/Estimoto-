import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/pending_request_store.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/state/plus_controller.dart';

class ReceiptRepository extends DemoPlusRepository {
  bool loseResponse = true;
  final keys = <String>[];
  final bodies = <Json>[];
  @override
  Future<Json> submitEstimate(
    String id,
    Json body,
    String idempotencyKey,
  ) async {
    keys.add(idempotencyKey);
    bodies.add(Map.of(body));
    if (loseResponse) {
      loseResponse = false;
      throw const PlusApiException('The response was lost.');
    }
    return {
      'id': id,
      'status': 'submitted',
      'provider_id': body['provider_id'],
    };
  }
}

class PausingStore extends MemoryPendingRequestStore {
  final started = Completer<void>();
  final resume = Completer<void>();
  @override
  Future<void> write(String customerId, PendingRequest request) async {
    started.complete();
    await resume.future;
    await super.write(customerId, request);
  }
}

void main() {
  test(
    'lost estimate receipt retains approved provider and key across restart',
    () async {
      final repository = ReceiptRepository();
      final store = MemoryPendingRequestStore();
      final first = PlusController(repository, pendingStore: store);
      await first.refresh();
      final estimate = first.snapshot!.estimates.first;
      final provider = first.snapshot!.providers.first;
      final body = {'provider_id': provider.id, 'share_contact': true};
      await expectLater(
        first.submitEstimate(estimate.id, body, provider),
        throwsA(isA<PlusApiException>()),
      );
      expect(first.pendingEstimate(estimate.id)?.body, body);

      final restored = PlusController(repository, pendingStore: store);
      await restored.refresh();
      expect(
        restored.pendingEstimate(estimate.id)?.key,
        'estimate:${estimate.id}',
      );
      final other = restored.snapshot!.providers.last;
      await expectLater(
        restored.submitEstimate(estimate.id, {
          'provider_id': other.id,
          'share_contact': true,
        }, other),
        throwsA(isA<PlusApiException>()),
      );
      expect(repository.keys, hasLength(1));
      final result = await restored.submitEstimate(estimate.id, body, provider);
      expect(result['status'], 'submitted');
      expect(repository.keys.toSet(), {'estimate:${estimate.id}'});
      expect(restored.pendingEstimate(estimate.id), isNull);
      final again = PlusController(repository, pendingStore: store);
      await again.refresh();
      expect(again.pendingEstimate(estimate.id), isNull);
      first.dispose();
      restored.dispose();
      again.dispose();
    },
  );

  test(
    'sign-out invalidates a paused submission before it can use credentials',
    () async {
      final repository = ReceiptRepository();
      final store = PausingStore();
      final controller = PlusController(repository, pendingStore: store);
      await controller.refresh();
      final provider = controller.snapshot!.providers.first;
      final id = controller.snapshot!.estimates.first.id;
      final customer = controller.snapshot!.profile.id;
      final send = controller.submitEstimate(id, {
        'provider_id': provider.id,
        'share_contact': true,
      }, provider);
      final check = expectLater(send, throwsA(isA<PlusApiException>()));
      await store.started.future;
      controller.invalidateSession();
      expect(controller.isCurrentCustomer(customer), isFalse);
      store.resume.complete();
      await check;
      expect(repository.keys, isEmpty);
      controller.dispose();
    },
  );
}
