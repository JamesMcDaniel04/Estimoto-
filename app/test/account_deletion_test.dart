import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/data/demo_repository.dart';
import 'package:estimoto_plus/data/repository.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/links.dart';
import 'package:estimoto_plus/screens/settings_screen.dart';
import 'package:estimoto_plus/screens/welcome_screen.dart';
import 'package:estimoto_plus/state/plus_controller.dart';
import 'package:estimoto_plus/theme.dart';

class _LiveRepository extends DemoPlusRepository {
  _LiveRepository({this.fail = false});
  final bool fail;
  int deletions = 0;
  @override
  bool get isDemo => false;
  @override
  Future<PlusSnapshot> bootstrap() async {
    final demo = await super.bootstrap();
    return PlusSnapshot.fromJson({
      'profile': demo.profile.json,
      'vehicles': demo.vehicles.map((v) => v.json).toList(),
      'capabilities': {'demo': false},
    });
  }

  @override
  Future<Json> deleteAccount() async {
    deletions++;
    if (fail) throw const PlusApiException('Please try again later.', 503);
    return {'deleted': true, 'identity_deleted': true};
  }
}

Future<void> _mount(
  WidgetTester tester,
  PlusRepository repository, {
  Future<void> Function()? onAccountDeleted,
}) async {
  final controller = PlusController(repository);
  await controller.refresh();
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: plusTheme(),
      home: SettingsScreen(
        controller: controller,
        onExit: () {},
        onAccountDeleted: onAccountDeleted,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('deleting the account asks first, then ends the session', (
    tester,
  ) async {
    final repository = _LiveRepository();
    var ended = 0;
    await _mount(tester, repository, onAccountDeleted: () async => ended++);
    final button = find.byKey(const Key('settings-delete-account'));
    await _tap(tester, button);
    expect(find.text('Delete your account?'), findsOneWidget);
    await _tap(tester, find.text('Keep my account'));
    expect(repository.deletions, 0);
    await _tap(tester, button);
    await _tap(
      tester,
      find.byKey(const Key('settings-delete-account-confirm')),
    );
    expect(repository.deletions, 1);
    expect(ended, 1);
    expect(find.text('Your account has been deleted.'), findsOneWidget);
  });

  testWidgets('a failed deletion keeps the session and explains', (
    tester,
  ) async {
    var ended = 0;
    await _mount(
      tester,
      _LiveRepository(fail: true),
      onAccountDeleted: () async => ended++,
    );
    await _tap(tester, find.byKey(const Key('settings-delete-account')));
    await _tap(
      tester,
      find.byKey(const Key('settings-delete-account-confirm')),
    );
    expect(ended, 0);
    expect(find.text('Please try again later.'), findsOneWidget);
  });

  testWidgets('the demo has no account to delete', (tester) async {
    await _mount(tester, DemoPlusRepository());
    expect(find.byKey(const Key('settings-delete-account')), findsNothing);
  });

  testWidgets('settings links the public policy pages', (tester) async {
    await _mount(tester, DemoPlusRepository());
    for (final label in ['Privacy policy', 'Terms of use', 'Support']) {
      expect(find.text(label), findsOneWidget);
    }
    expect(PlusLinks.privacy, startsWith('https://estimoto.io/'));
    expect(PlusLinks.terms, startsWith('https://estimoto.io/'));
    expect(PlusLinks.deleteAccount, startsWith('https://estimoto.io/'));
  });

  testWidgets('the welcome screen states the terms before sign-in', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: plusTheme(),
        home: WelcomeScreen(authAvailable: false, onDemo: () {}),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.textContaining('terms of use and privacy policy'),
      findsOneWidget,
    );
    expect(find.widgetWithText(TextButton, 'Terms of use'), findsOneWidget);
    expect(find.widgetWithText(TextButton, 'Privacy policy'), findsOneWidget);
  });
}
