/// Public Estimoto pages linked from the app. Override at build time with
/// `--dart-define=PLUS_PRIVACY_URL=…` and friends when a page moves.
abstract final class PlusLinks {
  static const privacy = String.fromEnvironment(
    'PLUS_PRIVACY_URL',
    defaultValue: 'https://estimoto.io/privacy',
  );
  static const terms = String.fromEnvironment(
    'PLUS_TERMS_URL',
    defaultValue: 'https://estimoto.io/terms',
  );
  static const support = String.fromEnvironment(
    'PLUS_SUPPORT_URL',
    defaultValue: 'https://estimoto.io/support',
  );

  /// Google Play requires a public page describing account deletion.
  static const deleteAccount = String.fromEnvironment(
    'PLUS_DELETE_ACCOUNT_URL',
    defaultValue: 'https://estimoto.io/plus/delete-account',
  );
}
