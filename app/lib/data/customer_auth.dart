import 'package:supabase_flutter/supabase_flutter.dart';
import 'repository.dart';

/// Identity changes are distinct from token refreshes for the same customer.
abstract class CustomerAuth {
  String? get userId;
  Stream<String?> get identities;
  Future<String?> accessToken();
  Future<void> signOut();
}

class SupabaseCustomerAuth extends CustomerAuth {
  GoTrueClient get _auth => Supabase.instance.client.auth;
  @override
  String? get userId => _auth.currentUser?.id;
  @override
  Stream<String?> get identities =>
      _auth.onAuthStateChange.map((event) => event.session?.user.id);
  @override
  Future<String?> accessToken() async {
    final owner = userId;
    var session = _auth.currentSession;
    if (session != null &&
        (session.expiresAt ?? 0) <=
            DateTime.now().millisecondsSinceEpoch ~/ 1000 + 60) {
      try {
        session = (await _auth.refreshSession()).session;
      } catch (_) {
        throw const PlusApiException('Please sign in again to continue.', 401);
      }
    }
    if (userId != owner) {
      throw const PlusApiException(
        'Your account changed. Please try again.',
        401,
      );
    }
    return session?.accessToken;
  }

  @override
  Future<void> signOut() => _auth.signOut(scope: SignOutScope.local);
}
