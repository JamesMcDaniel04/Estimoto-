import 'dart:async';
import 'support/receipt_proof.dart';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/screens/history_receipts_screen.dart';
import 'package:estimoto_plus/screens/history_screen.dart';
import 'package:estimoto_plus/services/estimate_capture.dart';
import 'package:estimoto_plus/services/receipt_api.dart';
import 'package:estimoto_plus/services/receipt_pending.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';
import 'package:estimoto_plus/widgets/history_cost_summary.dart';

class _Repo extends DemoPlusRepository {
  bool failFirst = false, failKnowledge = false;
  Completer<Json>? delayedKnowledge;
  int reads = 0;
  @override
  Future<Json> getKnowledge() async {
    reads++;
    if (failKnowledge) throw const PlusApiException("Unavailable", 503);
    final pending = delayedKnowledge;
    delayedKnowledge = null;
    return pending == null ? super.getKnowledge() : pending.future;
  }

  final uploads = <ReceiptPending>[];
  @override
  ReceiptApi openReceiptRecord(
    String recordId, {
    required bool Function() isCurrent,
  }) => _Api(super.openReceiptRecord(recordId, isCurrent: isCurrent), this);
}

class _Api extends ReceiptApi {
  _Api(this.delegate, this.repo);
  final ReceiptApi delegate;
  final _Repo repo;
  @override
  Future<Json> upload(ReceiptPending value) async {
    repo.uploads.add(value);
    if (repo.failFirst && repo.uploads.length == 1) {
      throw const PlusApiException(
        'Connection lost. Retry the saved receipt.',
        408,
      );
    }
    return delegate.upload(value);
  }

  @override
  Future<Uint8List> read(String id) => delegate.read(id);
  @override
  Future<void> delete(String id) => delegate.delete(id);
}

class _Picker extends EstimatePhotoPicker {
  Future<XFile?> Function()? callback;
  XFile? lost;
  int recovered = 0;
  @override
  Future<XFile?> pick(ImageSource source) async => callback?.call();
  @override
  Future<XFile?> recover() async {
    recovered++;
    return lost;
  }
}

Future<(PlusController, Json)> _setup(_Repo repo) async {
  final c = PlusController(repo);
  await c.refresh();
  final entry = await repo.addKnowledgeRecord({
    'vehicle_id': c.selectedVehicle!.id,
    'service_type': 'repair',
    'service_date': '2025-01-03',
    'cost_cents': 12550,
  }, 'history-1');
  return (c, entry);
}

Future<void> mount(WidgetTester t, Widget child) async {
  t.view.physicalSize = const Size(320, 740);
  t.view.devicePixelRatio = 1;
  addTearDown(t.view.resetPhysicalSize);
  addTearDown(t.view.resetDevicePixelRatio);
  await t.pumpWidget(
    MaterialApp(
      theme: const String.fromEnvironment('RECEIPT_FONT_DIR').isEmpty
          ? plusTheme()
          : plusTheme().copyWith(
              textTheme: plusTheme().textTheme.apply(fontFamily: 'Roboto'),
              primaryTextTheme: plusTheme().primaryTextTheme.apply(
                fontFamily: 'Roboto',
              ),
            ),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(1.8)),
        child: RepaintBoundary(
          key: const ValueKey('receipt-proof'),
          child: child!,
        ),
      ),
      home: child,
    ),
  );
  await t.pumpAndSettle();
}

Future<void> tap(WidgetTester t, String text) async {
  final finder = find.text(text);
  await t.ensureVisible(finder);
  await t.tap(finder);
  await t.pumpAndSettle();
}

void main() {
  setUpAll(loadReceiptProofFonts);
  testWidgets(
    'receipt retry at 320px large text uses one immutable upload after resume',
    (t) async {
      final repo = _Repo()..failFirst = true;
      final (c, r) = await _setup(repo);
      final store = MemoryReceiptPendingStore();
      final pdf = XFile.fromData(
        Uint8List.fromList('%PDF-1.4 receipt'.codeUnits),
        name: 'service.pdf',
        mimeType: 'application/pdf',
      );
      await mount(
        t,
        HistoryReceiptsScreen(
          controller: c,
          recordId: r['id'],
          store: store,
          pdfPicker: () async => pdf,
        ),
      );
      await saveReceiptProof(t, 'receipt-entry-320-large');
      await tap(t, 'Choose PDF');
      expect(repo.uploads.length, 1);
      expect(await store.read(c.snapshot!.profile.id), isNotNull);
      expect(find.text('Attachment waiting to finish'), findsOneWidget);
      await t.ensureVisible(find.text('Attachment waiting to finish'));
      await t.pumpAndSettle();
      await saveReceiptProof(t, 'receipt-retry-320-large');
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await t.pumpAndSettle();
      expect(repo.uploads.length, 1);
      await tap(t, 'Retry saved receipt');
      expect(repo.uploads.length, 2);
      expect(repo.uploads.first.samePayload(repo.uploads.last), isTrue);
      expect(await store.read(c.snapshot!.profile.id), isNull);
      expect(find.text('Receipt saved privately.'), findsOneWidget);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets('cancelled PDF chooser leaves no upload or pending bytes', (
    t,
  ) async {
    final repo = _Repo();
    final (c, r) = await _setup(repo);
    final store = MemoryReceiptPendingStore();
    await mount(
      t,
      HistoryReceiptsScreen(
        controller: c,
        recordId: r['id'],
        store: store,
        pdfPicker: () async => null,
      ),
    );
    await tap(t, 'Choose PDF');
    expect(repo.uploads, isEmpty);
    expect(await store.read(c.snapshot!.profile.id), isNull);
  });
  testWidgets(
    'account switch while photo picker is open never uploads its result',
    (t) async {
      final repo = _Repo();
      final (c, r) = await _setup(repo);
      final store = MemoryReceiptPendingStore();
      final selected = Completer<XFile?>();
      final native = MemoryEstimateCaptureStore();
      final picker = _Picker()..callback = () => selected.future;
      final service = EstimateCaptureService(
        store: native,
        picker: picker,
        readBytes: (_) async => Uint8List.fromList([255, 216, 255, 1]),
      );
      await mount(
        t,
        HistoryReceiptsScreen(
          controller: c,
          recordId: r['id'],
          store: store,
          captureService: service,
        ),
      );
      await t.ensureVisible(find.text('Choose photo'));
      await t.tap(find.text('Choose photo'));
      await t.pump();
      c.invalidateSession();
      selected.complete(XFile('/private/receipt.jpg'));
      await t.pumpAndSettle();
      expect(repo.uploads, isEmpty);
      expect(await store.read(c.snapshot!.profile.id), isNull);
      expect(find.text('Sign in again to view your history.'), findsOneWidget);
      expect(native.value!.targetKind, 'receipt');
      expect(native.value!.estimateId, r['id']);
    },
  );
  test(
    'receipt lost data cannot be consumed by vehicle or another owner',
    () async {
      final store = MemoryEstimateCaptureStore()
        ..value = PendingEstimateCapture.fromJson(
          const PendingEstimateCapture(
            id: 'capture',
            customerId: 'alice',
            estimateId: 'record',
            captureKey: '11111111-1111-4111-8111-111111111111',
            targetKind: 'receipt',
          ).toJson(),
        );
      final picker = _Picker()..lost = XFile('/private/receipt.jpg');
      final service = EstimateCaptureService(store: store, picker: picker);
      expect(
        await service.recover(
          customerId: 'alice',
          estimateId: 'record',
          targetKind: 'vehicle',
          isCurrent: () => true,
        ),
        isNull,
      );
      expect(
        await service.recover(
          customerId: 'bob',
          estimateId: 'record',
          targetKind: 'receipt',
          isCurrent: () => true,
        ),
        isNull,
      );
      expect(picker.recovered, 0);
      expect(
        await service.recover(
          customerId: 'alice',
          estimateId: 'record',
          targetKind: 'receipt',
          isCurrent: () => true,
        ),
        isNotNull,
      );
      expect(picker.recovered, 1);
    },
  );
  testWidgets(
    'reusing receipt state for a different history entry hides old receipt actions',
    (t) async {
      final repo = _Repo();
      final (c, r) = await _setup(repo);
      final store = MemoryReceiptPendingStore();
      await mount(
        t,
        HistoryReceiptsScreen(controller: c, recordId: r['id'], store: store),
      );
      expect(find.text('Choose PDF'), findsOneWidget);
      await mount(
        t,
        HistoryReceiptsScreen(
          controller: c,
          recordId: 'different-record',
          store: store,
        ),
      );
      expect(find.text('Choose PDF'), findsNothing);
      expect(find.textContaining('Sign in again'), findsOneWidget);
    },
  );
  testWidgets(
    'cost summary separates saved history categories and missing costs; refreshes after deletion and vehicle switch',
    (t) async {
      final repo = _Repo();
      final (c, _) = await _setup(repo);
      final id = c.selectedVehicle!.id;
      final more = await repo.addKnowledgeRecord({
        'vehicle_id': id,
        'service_type': 'diagnostics',
        'service_date': '2025-01-03',
        'cost_cents': 10000,
      }, 'diag');
      await repo.addKnowledgeRecord({
        'vehicle_id': id,
        'service_type': 'maintenance',
        'service_date': '2025-01-03',
        'cost_cents': 5000,
      }, 'maint');
      await repo.addKnowledgeRecord({
        'vehicle_id': id,
        'service_type': 'modification',
        'service_date': '2025-01-03',
        'cost_cents': 20000,
      }, 'mod');
      await repo.addKnowledgeRecord({
        'vehicle_id': id,
        'service_type': 'other',
        'service_date': '2025-01-03',
        'cost_cents': 123,
      }, 'other');
      await repo.addKnowledgeRecord({
        'vehicle_id': id,
        'service_type': 'repair',
        'service_date': '2025-01-03',
      }, 'unknown');
      await mount(
        t,
        Scaffold(
          body: SingleChildScrollView(child: HistoryCostSummary(controller: c)),
        ),
      );
      expect(find.text('\$225.50'), findsOneWidget);
      expect(find.text('\$476.73'), findsOneWidget);
      expect(find.textContaining('1 missing a cost'), findsOneWidget);
      expect(find.text('Other'), findsOneWidget);
      await saveReceiptProof(t, 'repair-costs-320-large');
      expect(t.takeException(), isNull);
      await repo.deleteKnowledgeRecord(more['id']);
      c.historyChanged();
      await t.pumpAndSettle();
      expect(find.text('\$376.73'), findsOneWidget);
      final other = c.snapshot!.vehicles.firstWhere((v) => v.id != id);
      c.selectVehicle(other.id);
      await t.pumpAndSettle();
      expect(find.text('\$0.00'), findsNWidgets(4));
      expect(find.text('0 saved entries'), findsOneWidget);
      expect(find.text('\$376.73'), findsNothing);
    },
  );
  testWidgets(
    'an Other entry with no cost remains explicit and is excluded from totals',
    (t) async {
      final repo = _Repo();
      final (c, _) = await _setup(repo);
      await repo.addKnowledgeRecord({
        'vehicle_id': c.selectedVehicle!.id,
        'service_type': 'other',
        'service_date': '2025-01-03',
      }, 'unknown-other');
      await mount(
        t,
        Scaffold(
          body: SingleChildScrollView(child: HistoryCostSummary(controller: c)),
        ),
      );
      expect(find.text('Other'), findsOneWidget);
      expect(find.textContaining('1 missing a cost'), findsOneWidget);
      expect(find.text('\$125.50'), findsNWidgets(2));
    },
  );
  testWidgets(
    'returning to Repairs refreshes costs; stale delayed response cannot replace another vehicle',
    (t) async {
      final repo = _Repo();
      final (c, _) = await _setup(repo);
      c.selectTab(3);
      await mount(
        t,
        Scaffold(
          body: SingleChildScrollView(child: HistoryCostSummary(controller: c)),
        ),
      );
      final before = repo.reads;
      c.selectTab(2);
      c.selectTab(3);
      await t.pumpAndSettle();
      expect(repo.reads, before + 1);
      final old = await repo.getKnowledge();
      final delayed = Completer<Json>();
      repo.delayedKnowledge = delayed;
      c.historyChanged();
      await t.pump();
      c.selectVehicle(c.snapshot!.vehicles.last.id);
      await t.pumpAndSettle();
      expect(find.text('0 saved entries'), findsOneWidget);
      delayed.complete(old);
      await t.pumpAndSettle();
      expect(find.text('0 saved entries'), findsOneWidget);
      expect(find.text('\$125.50'), findsNothing);
      repo.failKnowledge = true;
      c.historyChanged();
      await t.pumpAndSettle();
      expect(find.text('Retry cost summary'), findsOneWidget);
      expect(find.text('\$0.00'), findsNothing);
      c.invalidateSession();
      await t.pumpAndSettle();
      expect(find.text('Your recorded costs'), findsNothing);
    },
  );
  testWidgets(
    'history editor saves exact USD cents and offers receipt entry afterward',
    (t) async {
      final repo = _Repo();
      final (c, _) = await _setup(repo);
      await mount(t, HistoryEditor(controller: c));
      final cost = find.byKey(const ValueKey('history-cost_cents'));
      await t.ensureVisible(cost);
      await t.enterText(cost, '81.27');
      await tap(t, 'Save history entry');
      final knowledge = await repo.getKnowledge();
      expect(rowsOf(knowledge, 'records').first['cost_cents'], 8127);
    },
  );
}
