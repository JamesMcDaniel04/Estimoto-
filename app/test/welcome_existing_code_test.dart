import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:estimoto_plus/screens/welcome_screen.dart';

void main() {
  final authRequests = <http.Request>[];

  setUpAll(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('plugins.flutter.io/shared_preferences'),
          (call) async => call.method == 'getAll' ? <String, Object>{} : true,
        );
    await Supabase.initialize(
      url: 'https://qa.example.test',
      publishableKey: 'qa-publishable-key',
      debug: false,
      httpClient: MockClient((request) async {
        authRequests.add(request);
        return http.Response(
          jsonEncode({'code': 'otp_expired', 'msg': 'Invalid code'}),
          400,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
  });

  setUp(authRequests.clear);

  Future<void> showWelcome(WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(home: WelcomeScreen(authAvailable: true, onDemo: () {})),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'existing-code action opens editable email and code without sending',
    (tester) async {
      await showWelcome(tester);
      await tester.ensureVisible(find.text('I already have a code'));
      await tester.tap(find.text('I already have a code'));
      await tester.pumpAndSettle();

      expect(find.text('Email code'), findsOneWidget);
      expect(find.text('Verify & sign in'), findsOneWidget);
      expect(
        tester
            .widget<TextField>(find.widgetWithText(TextField, 'Email address'))
            .enabled,
        isTrue,
      );
      expect(authRequests, isEmpty);
    },
  );

  for (final (email, message) in [
    ('', 'Enter your email address.'),
    ('notanemail', 'Enter a valid email address, such as name@example.com.'),
  ]) {
    testWidgets('email validation distinguishes empty from invalid: $email', (
      tester,
    ) async {
      await showWelcome(tester);
      await tester.enterText(
        find.widgetWithText(TextField, 'Email address'),
        email,
      );
      await tester.ensureVisible(find.text('Continue with email'));
      await tester.tap(find.text('Continue with email'));
      await tester.pumpAndSettle();
      expect(find.text(message), findsOneWidget);
      expect(authRequests, isEmpty);
    });
  }

  testWidgets(
    'existing code requires eight digits and verifies without sending',
    (tester) async {
      await showWelcome(tester);
      await tester.ensureVisible(find.text('I already have a code'));
      await tester.tap(find.text('I already have a code'));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextField, 'Email address'),
        'qa@example.invalid',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Email code'),
        '1234567',
      );
      await tester.ensureVisible(find.text('Verify & sign in'));
      await tester.tap(find.text('Verify & sign in'));
      await tester.pumpAndSettle();
      expect(
        find.text('Enter the 8-digit code from your email.'),
        findsOneWidget,
      );
      expect(authRequests, isEmpty);

      await tester.enterText(
        find.widgetWithText(TextField, 'Email code'),
        '12345678',
      );
      await tester.tap(find.text('Verify & sign in'));
      await tester.pumpAndSettle();

      expect(authRequests, hasLength(1));
      expect(authRequests.single.url.path, '/auth/v1/verify');
      final body = jsonDecode(authRequests.single.body) as Map<String, dynamic>;
      expect(body['email'], 'qa@example.invalid');
      expect(body['token'], '12345678');
      expect(body['type'], 'email');
      expect(find.textContaining('could not be verified'), findsOneWidget);
    },
  );
}
