/// Release identity shown to customers and support.
///
/// Build scripts pass `PLUS_VERSION_NAME` and `PLUS_BUILD_NUMBER` from
/// `pubspec.yaml`; the defaults keep local runs and tests meaningful.
class PlusBuildInfo {
  static const versionName = String.fromEnvironment(
    'PLUS_VERSION_NAME',
    defaultValue: '0.1.0',
  );
  static const buildNumber = String.fromEnvironment(
    'PLUS_BUILD_NUMBER',
    defaultValue: '9',
  );
  static const sourceSha = String.fromEnvironment('SOURCE_SHA');
  static String get label => 'Version $versionName ($buildNumber)';
}
