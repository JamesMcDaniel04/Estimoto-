import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/services/guided_capture_api.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/services/guided_capture_document.dart';
import 'package:estimoto_plus/services/guided_capture_pending.dart';
import 'guided_capture_session_test.dart' as fake;

class TokenCaptureRepository extends fake.CaptureRepositoryFake {
  TokenCaptureRepository(this.transport);
  final ApiPlusRepository transport;
  @override
  GuidedCaptureApi openGuidedCapture(
    String estimateId, {
    required bool Function() isCurrent,
  }) => transport.openGuidedCapture(estimateId, isCurrent: isCurrent);
}

void main() {
  test(
    'document replacement during token loading prevents POST before new load or ready',
    () async {
      final token = Completer<String?>();
      var posts = 0, tokenReads = 0;
      final transport = ApiPlusRepository(
        baseUrl: 'https://plus.example.test',
        token: () {
          tokenReads++;
          return token.future;
        },
        client: MockClient((request) async {
          posts++;
          return http.Response('{}', 200);
        }),
      );
      final session = await fake.session(
        TokenCaptureRepository(transport),
        MemoryGuidedCapturePendingStore(),
      );
      Object? visible = Object();
      final page = GuidedCaptureDocument(session, () => visible);
      page.synchronize();
      final pending = session.receive(
        fake.rpc('pending', 'confirmVin', {
          'photo_id': 'photo-1',
          'photo_sha256': 'a' * 64,
          'expected_vin': '',
          'vin': '1HGBH41JXMN109186',
        }),
      );
      while (tokenReads == 0) {
        await Future<void>.delayed(Duration.zero);
      }
      visible = Object(); // No ready/load has happened yet.
      token.complete('test-token');
      expect(await pending, isNull);
      expect(posts, 0);
      page.dispose();
      transport.close();
    },
  );
  test(
    'same-path replacement drops old replies before load and accepts reused IDs only in the new document',
    () async {
      final repo = fake.CaptureRepositoryFake();
      final session = await fake.session(
        repo,
        MemoryGuidedCapturePendingStore(),
      );
      Object? visibleDocument = Object();
      final page = GuidedCaptureDocument(session, () => visibleDocument);
      expect(page.synchronize(), isTrue);
      final oldRun = session.epoch;
      final oldResponse = Completer<Json>();
      repo.api.saving = oldResponse;
      final pending = session.receive(
        fake.rpc('same-id', 'saveCapture', fake.photoBody()),
      );
      while (repo.api.saves.isEmpty) {
        await Future<void>.delayed(Duration.zero);
      }
      // WindowProxy and URL stay fixed, but the Document changes before load.
      visibleDocument = Object();
      expect(session.valid(oldRun), isFalse);
      expect(page.current, isFalse);
      expect(page.synchronize(), isTrue); // ready before load
      final newRun = session.epoch;
      expect(page.synchronize(), isFalse); // later load of that same document
      expect(session.epoch, newRun);
      final current = await session.receive(
        fake.rpc('same-id', 'captureState'),
      );
      expect(current?['result'], isNotNull);
      expect(
        await session.receive(fake.rpc('same-id', 'captureState')),
        isNull,
      );
      session.pause();
      session.activate(); // same-document resume keeps IDs
      expect(
        await session.receive(fake.rpc('same-id', 'captureState')),
        isNull,
      );
      final photo = repo.api.saves.single;
      oldResponse.complete({
        'id': 'old-photo',
        'label': photo.captureKey,
        'sha256': photo.sha256,
      });
      expect(await pending, isNull);
      expect(
        (await session.store.read(session.ownerId))?.operationId,
        photo.operationId,
      );
      page.dispose();
    },
  );
  test(
    'foreign or unavailable document never activates a message channel',
    () async {
      final session = await fake.session(
        fake.CaptureRepositoryFake(),
        MemoryGuidedCapturePendingStore(),
      );
      session.pause();
      Object? visible;
      final page = GuidedCaptureDocument(session, () => visible);
      expect(page.synchronize(), isFalse);
      expect(session.enabled, isFalse);
      visible = Object();
      session.foreground = false;
      expect(page.synchronize(), isFalse);
      session.foreground = true;
      expect(page.synchronize(), isTrue);
      visible = null;
      expect(session.valid(session.epoch), isFalse);
      page.dispose();
      expect(session.enabled, isFalse);
    },
  );
}
