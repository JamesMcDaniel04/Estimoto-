import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'app.dart';
import 'data/api_repository.dart';
import 'data/auth_storage.dart';
import 'data/demo_repository.dart';
import 'data/repository.dart';
import 'screens/welcome_screen.dart';
import 'state/plus_controller.dart';
import 'theme.dart';

const apiUrl = String.fromEnvironment('PLUS_API_URL');
const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
const supabaseKey = String.fromEnvironment('SUPABASE_PUBLISHABLE_KEY');
const autoDemo = bool.fromEnvironment('PLUS_DEMO', defaultValue: false);
const devToken = String.fromEnvironment('PLUS_DEV_TOKEN');
bool get authConfigured =>
    supabaseUrl.isNotEmpty && supabaseKey.isNotEmpty && apiUrl.isNotEmpty;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  String? setupError;
  if (authConfigured) {
    try {
      final uri = Uri.parse(supabaseUrl);
      if (uri.scheme != 'https' ||
          uri.userInfo.isNotEmpty ||
          uri.hasQuery ||
          uri.hasFragment) {
        throw const FormatException();
      }
      await Supabase.initialize(
        url: supabaseUrl,
        publishableKey: supabaseKey,
        authOptions: FlutterAuthClientOptions(
          localStorage: kIsWeb
              ? const EmptyLocalStorage()
              : const SecureAuthStorage(),
        ),
      );
    } catch (_) {
      setupError =
          'Sign-in could not start. You can try again later or explore the demo.';
    }
  }
  runApp(PlusLauncher(setupError: setupError));
}

class PlusLauncher extends StatefulWidget {
  const PlusLauncher({super.key, this.setupError});
  final String? setupError;
  @override
  State<PlusLauncher> createState() => _PlusLauncherState();
}

class _PlusLauncherState extends State<PlusLauncher> {
  PlusController? controller;
  StreamSubscription<AuthState>? authSubscription;
  String? error;
  @override
  void initState() {
    super.initState();
    error = widget.setupError;
    if (autoDemo) {
      controller = PlusController(DemoPlusRepository());
    } else if (!kReleaseMode && devToken.isNotEmpty && apiUrl.isNotEmpty) {
      controller = PlusController(
        ApiPlusRepository(baseUrl: apiUrl, token: () async => devToken),
      );
    }
    if (authConfigured && widget.setupError == null) {
      authSubscription = Supabase.instance.client.auth.onAuthStateChange.listen(
        (state) {
          if (!mounted || controller?.repository.isDemo == true) return;
          if (state.session != null && controller == null) _openLive();
          if (state.event == AuthChangeEvent.signedOut) _clearController();
        },
      );
      if (Supabase.instance.client.auth.currentSession != null &&
          controller == null) {
        _openLive();
      }
    }
  }

  void _openLive() {
    try {
      final repository = ApiPlusRepository(
        baseUrl: apiUrl,
        token: () async {
          final auth = Supabase.instance.client.auth;
          var session = auth.currentSession;
          if (session != null &&
              (session.expiresAt ?? 0) <=
                  DateTime.now().millisecondsSinceEpoch ~/ 1000 + 60) {
            try {
              session = (await auth.refreshSession()).session;
            } catch (_) {
              throw const PlusApiException(
                'Please sign in again to continue.',
                401,
              );
            }
          }
          return session?.accessToken;
        },
      );
      setState(() => controller = PlusController(repository));
    } catch (_) {
      setState(
        () => error =
            'Sign-in is not available in this preview. You can explore the demo.',
      );
    }
  }

  void _clearController() {
    final previous = controller;
    if (mounted) setState(() => controller = null);
    WidgetsBinding.instance.addPostFrameCallback((_) => previous?.dispose());
  }

  Future<void> _exit() async {
    final isDemo = controller?.repository.isDemo == true;
    if (!isDemo && authConfigured && widget.setupError == null) {
      try {
        await Supabase.instance.client.auth.signOut(scope: SignOutScope.local);
      } catch (_) {
        setState(
          () => error = 'Sign-out could not complete. Please try again.',
        );
        return;
      }
    }
    if (controller != null) _clearController();
  }

  @override
  void dispose() {
    authSubscription?.cancel();
    controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (controller != null) {
      return EstimotoPlusApp(
        key: ObjectKey(controller),
        controller: controller!,
        onExit: _exit,
      );
    }
    return MaterialApp(
      title: 'Estimoto +',
      debugShowCheckedModeBanner: false,
      theme: plusTheme(),
      home: WelcomeScreen(
        authAvailable: authConfigured && widget.setupError == null,
        setupError: error,
        onDemo: () =>
            setState(() => controller = PlusController(DemoPlusRepository())),
      ),
    );
  }
}
