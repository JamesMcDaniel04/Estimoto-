import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/domain/models.dart';
import 'package:estimoto_plus/theme.dart';
import 'package:estimoto_plus/widgets/discovery_results.dart';
import 'package:estimoto_plus/widgets/shop_media.dart';

const sourceId = '516c3543-cf4e-43ca-b6b4-a505e1f67bd5';
const logoUrl =
    'https://pdr-estimating-api.fly.dev/public/plus/providers/$sourceId/logo';

Json logo() => {
  'url': logoUrl,
  'kind': 'logo',
  'attribution': 'Synthetic shop owner',
  'source_url': 'https://www.estimoto.io',
};

Json reviewedLogo() => {
  'url':
      'https://estimoto-plus-api.fly.dev/public/shop-media/node/123/${'a' * 64}.png',
  'kind': 'logo',
  'attribution': 'Synthetic repair shop · Official website',
  'source_url': 'https://shop.example/',
};

ProviderProfile mergedShop({
  Object? identity = const {'source': 'openstreetmap', 'source_id': 'node:123'},
}) => ProviderProfile.fromJson({
  ...shop(media: reviewedLogo()).json,
  'media_identity': identity,
});

ProviderProfile shop({Object? media, String name = 'Synthetic Dent Shop'}) =>
    ProviderProfile.fromJson({
      'id': 'synthetic-provider',
      'source': 'estimoto',
      'source_id': sourceId,
      'name': name,
      'kind': 'shop',
      'specialties': ['pdr', 'collision'],
      'distance_miles': 6.2,
      'address': '1 Synthetic Road, Denver CO 80221',
      'accepting_requests': true,
      'request_modes': ['shop_visit'],
      'media': media,
    });

ProviderProfile publicShop({
  String filename = 'Synthetic_shop.jpg',
}) => ProviderProfile.fromJson({
  'source': 'openstreetmap',
  'source_id': 'node:123',
  'name': 'Synthetic repair shop',
  'media': {
    'url':
        'https://commons.wikimedia.org/wiki/Special:Redirect/file/${Uri.encodeComponent(filename)}?width=320',
    'kind': 'photo',
    'attribution': 'Synthetic creator · CC BY-SA 4.0',
    'source_url':
        'https://commons.wikimedia.org/wiki/File:${Uri.encodeComponent(filename)}',
  },
});

Future<void> mount(
  WidgetTester tester,
  Widget child, {
  double width = 390,
  double scale = 1,
}) async {
  tester.view.physicalSize = Size(width, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: plusTheme(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(scale)),
        child: child!,
      ),
      home: Scaffold(
        body: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: child,
        ),
      ),
    ),
  );
}

class ImageClient extends Fake implements HttpClient {
  final calls = <Uri>[];
  final headers = <String>[];
  final responses = <Completer<HttpClientResponse>>[];
  bool fail = false;

  @override
  Future<HttpClientRequest> getUrl(Uri url) async {
    calls.add(url);
    if (fail) throw const SocketException('Synthetic image failure');
    final response = Completer<HttpClientResponse>();
    responses.add(response);
    return ImageRequest(response, headers);
  }
}

class ImageRequest extends Fake implements HttpClientRequest {
  ImageRequest(this.response, List<String> names)
    : headers = ImageHeaders(names);
  final Completer<HttpClientResponse> response;
  @override
  final HttpHeaders headers;
  @override
  Future<HttpClientResponse> close() => response.future;
}

class ImageHeaders extends Fake implements HttpHeaders {
  ImageHeaders(this.names);
  final List<String> names;
  @override
  void add(String name, Object value, {bool preserveHeaderCase = false}) =>
      names.add(name.toLowerCase());
}

class ImageResponse extends Stream<List<int>> implements HttpClientResponse {
  // A synthetic 2x2 raster fixture; no downloaded shop artwork.
  final bytes = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGMUTT3AwMDAxAAGAA43AT5DleqKAAAAAElFTkSuQmCC',
  );
  @override
  int get statusCode => 200;
  @override
  int get contentLength => bytes.length;
  @override
  HttpClientResponseCompressionState get compressionState =>
      HttpClientResponseCompressionState.notCompressed;
  @override
  StreamSubscription<List<int>> listen(
    void Function(List<int>)? onData, {
    Function? onError,
    void Function()? onDone,
    bool? cancelOnError,
  }) => Stream<List<int>>.value(bytes).listen(
    onData,
    onError: onError,
    onDone: onDone,
    cancelOnError: cancelOnError,
  );
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  late ImageClient client;
  setUp(() {
    client = ImageClient();
  });
  tearDown(() {
    debugNetworkImageHttpClientProvider = null;
    PaintingBinding.instance.imageCache.clear();
    PaintingBinding.instance.imageCache.clearLiveImages();
  });
  void imageTest(String description, WidgetTesterCallback body) {
    testWidgets(description, (tester) async {
      debugNetworkImageHttpClientProvider = () => client;
      try {
        await body(tester);
      } finally {
        debugNetworkImageHttpClientProvider = null;
      }
    });
  }

  test(
    'media binds published logo to this provider and rejects unsafe URLs',
    () {
      expect(shop(media: logo()).media?.kind, 'logo');
      for (final bad in [
        null,
        'not a map',
        {...logo(), 'kind': 'illustration'},
        {...logo(), 'attribution': ''},
        {...logo(), 'source_url': 'https://user:secret@www.estimoto.io'},
        {...logo(), 'url': '$logoUrl?token=secret'},
        {...logo(), 'url': '$logoUrl#secret'},
        {...logo(), 'url': logoUrl.replaceFirst('https:', 'http:')},
        {...logo(), 'url': logoUrl.replaceFirst('/logo', '/private')},
        {...logo(), 'url': logoUrl.replaceFirst(sourceId, 'x' * 36)},
        {...logo(), 'url': 'https://pdr-estimating-api.fly.dev.evil.test/logo'},
        {
          ...logo(),
          'url': 'https://user:secret@pdr-estimating-api.fly.dev/logo',
        },
      ]) {
        expect(shop(media: bad).media, isNull);
      }
    },
  );

  test('Commons photos need fixed thumbnail and matching file attribution', () {
    final value = {
      'source': 'openstreetmap',
      'source_id': 'node:123',
      'media': {
        'url':
            'https://commons.wikimedia.org/wiki/Special:Redirect/file/Synthetic_shop.jpg?width=320',
        'kind': 'photo',
        'attribution': 'Synthetic creator · CC BY-SA 4.0',
        'source_url':
            'https://commons.wikimedia.org/wiki/File:Synthetic_shop.jpg',
      },
    };
    expect(ProviderProfile.fromJson(value).media?.kind, 'photo');
    expect(
      publicShop(filename: 'Synthetic café shop.jpg').media?.kind,
      'photo',
    );
    for (final url in [
      'https://commons.wikimedia.org/wiki/Special:Redirect/file/Synthetic_shop.jpg?width=320&token=secret',
      'https://commons.wikimedia.org/wiki/Special:Redirect/file/Other.jpg?width=320',
      'https://commons.wikimedia.org/wiki/Special:Redirect/file/%2Fprivate.jpg?width=320',
      'https://images.example.test/Synthetic_shop.jpg',
    ]) {
      expect(
        ProviderProfile.fromJson({
          ...value,
          'media': {...value['media'] as Json, 'url': url},
        }).media,
        isNull,
      );
    }
  });

  test('reviewed artwork binds the fixed Plus route to the public listing', () {
    final digest = 'a' * 64;
    final url =
        'https://estimoto-plus-api.fly.dev/public/shop-media/way/123/$digest.png';
    final media = {
      'url': url,
      'kind': 'logo',
      'attribution': 'Example Auto · Official website',
      'source_url': 'https://example-auto.test/',
    };
    ProviderMedia? parse(Object? value, {String source = 'way:123'}) =>
        ProviderMedia.fromJson(
          value,
          providerSource: 'openstreetmap',
          providerSourceId: source,
        );
    expect(parse(media)?.kind, 'logo');
    expect(parse({...media, 'background': 'dark'})?.darkBackground, isTrue);
    expect(parse(media)?.darkBackground, isFalse);
    expect(parse({...media, 'kind': 'photo'})?.kind, 'photo');
    expect(parse(media, source: 'node:123'), isNull);
    expect(parse(media, source: 'way:124'), isNull);
    for (final badUrl in [
      '$url?url=https://private.test',
      '$url#fragment',
      url.replaceFirst('estimoto-plus-api.fly.dev', 'evil.test'),
      url.replaceFirst('/shop-media/', '/private/'),
      url.replaceFirst(digest, 'not-a-content-hash'),
      url.replaceFirst('.png', '.svg'),
      url.replaceFirst('/123/', '/0123/'),
      url.replaceFirst('https:', 'http:'),
    ]) {
      expect(parse({...media, 'url': badUrl}), isNull);
    }
  });

  test(
    'merged artwork uses its preserved listing identity without overriding other providers',
    () {
      expect(mergedShop().media?.kind, 'logo');
      expect(mergedShop().sourceId, sourceId);
      expect(mergedShop().requestModes, ['shop_visit']);
      expect(
        ProviderProfile.fromJson({
          ...mergedShop().json,
          'media': publicShop().json['media'],
        }).media?.kind,
        'photo',
      );
      for (final invalid in [
        null,
        'node:123',
        {},
        {'source': 'openstreetmap'},
        {'source': 'openstreetmap', 'source_id': 'node:124'},
        {'source': 'openstreetmap', 'source_id': 'node:0123'},
        {'source': 'openstreetmap', 'source_id': '../123'},
        {'source': 'estimoto', 'source_id': sourceId},
        {'source': 'other', 'source_id': 'node:123'},
      ]) {
        expect(mergedShop(identity: invalid).media, isNull, reason: '$invalid');
      }
      expect(
        ProviderProfile.fromJson({
          ...mergedShop().json,
          'source': 'openstreetmap',
          'source_id': 'node:124',
        }).media,
        isNull,
      );
      expect(
        ProviderProfile.fromJson({
          ...mergedShop().json,
          'source': 'untrusted',
        }).media,
        isNull,
      );
      expect(
        ProviderProfile.fromJson({
          ...shop(media: logo()).json,
          'media_identity': {
            'source': 'estimoto',
            'source_id': '00000000-0000-0000-0000-000000000000',
          },
        }).media,
        isNull,
      );
    },
  );

  imageTest(
    'merged reviewed logo renders anonymously and preserves request and save actions',
    (tester) async {
      var requested = false, saved = false;
      await mount(
        tester,
        DiscoveryProviderCard(
          provider: mergedShop(),
          onRequest: () => requested = true,
          onSave: () => saved = true,
        ),
      );
      await tester.pump();
      expect(client.calls, [Uri.parse(reviewedLogo()['url'] as String)]);
      final image = tester.widget<Image>(find.byType(Image));
      final decoded = Completer<void>();
      final stream = image.image.resolve(ImageConfiguration.empty);
      final listener = ImageStreamListener(
        (_, _) => decoded.complete(),
        onError: (Object error, StackTrace? stack) =>
            decoded.completeError(error, stack),
      );
      stream.addListener(listener);
      client.responses.single.complete(ImageResponse());
      for (var i = 0; i < 100 && !decoded.isCompleted; i++) {
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 10)),
        );
        await tester.pump();
      }
      expect(decoded.isCompleted, isTrue);
      stream.removeListener(listener);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('shop-media-fallback')), findsNothing);
      expect(client.headers, isNot(contains('authorization')));
      expect(client.headers, isNot(contains('referer')));
      await tester.ensureVisible(find.text('Request help'));
      await tester.tap(find.text('Request help'));
      await tester.ensureVisible(find.text('Save as my dedicated shop'));
      await tester.tap(find.text('Save as my dedicated shop'));
      expect(requested && saved, isTrue);
      expect(tester.takeException(), isNull);
    },
  );

  imageTest('missing or rejected media never starts an image request', (
    tester,
  ) async {
    await mount(tester, ShopMediaThumbnail(provider: shop()));
    expect(find.byKey(const Key('shop-media-fallback')), findsOneWidget);
    expect(client.calls, isEmpty);
    await mount(
      tester,
      ShopMediaThumbnail(
        provider: shop(media: {...logo(), 'url': 'https://evil.test/image'}),
      ),
    );
    expect(find.byKey(const Key('shop-media-fallback')), findsOneWidget);
    expect(client.calls, isEmpty);
  });

  imageTest('failed logo keeps its fallback, credit and shop actions usable', (
    tester,
  ) async {
    client.fail = true;
    var requested = false, saved = false;
    await mount(
      tester,
      DiscoveryProviderCard(
        provider: shop(media: logo()),
        onRequest: () => requested = true,
        onSave: () => saved = true,
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('shop-media-fallback')), findsOneWidget);
    expect(client.calls, [Uri.parse(logoUrl)]);
    expect(client.headers, isNot(contains('authorization')));
    expect(client.headers, isNot(contains('referer')));
    await tester.ensureVisible(find.text('View shop profile'));
    await tester.tap(find.text('View shop profile'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Logo credit'));
    await tester.tap(find.text('Logo credit'));
    await tester.pumpAndSettle();
    expect(find.text('Synthetic shop owner'), findsOneWidget);
    expect(find.text('View image source'), findsOneWidget);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byTooltip('Close shop profile'));
    await tester.tap(find.byTooltip('Close shop profile'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Request help'));
    await tester.tap(find.text('Request help'));
    await tester.ensureVisible(find.text('Save as my dedicated shop'));
    await tester.tap(find.text('Save as my dedicated shop'));
    expect(requested && saved, isTrue);
    expect(tester.takeException(), isNull);
  });

  imageTest('replacing a listing discards its still-loading image', (
    tester,
  ) async {
    await mount(tester, ShopMediaThumbnail(provider: shop(media: logo())));
    await tester.pump();
    final image = tester.widget<Image>(find.byType(Image));
    expect(image.fit, BoxFit.contain);
    expect(client.responses, hasLength(1));
    await mount(tester, ShopMediaThumbnail(provider: shop(name: 'Other shop')));
    client.responses.single.complete(ImageResponse());
    await tester.runAsync(() async => Future<void>.delayed(Duration.zero));
    await tester.pumpAndSettle();
    expect(find.byType(Image), findsNothing);
    expect(find.byKey(const Key('shop-media-fallback')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  imageTest('a decoded public photo crops and exposes its accessible label', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    await mount(tester, ShopMediaThumbnail(provider: publicShop()));
    await tester.pump();
    final image = tester.widget<Image>(find.byType(Image));
    expect(image.fit, BoxFit.cover);
    final decoded = Completer<void>();
    final stream = image.image.resolve(ImageConfiguration.empty);
    final listener = ImageStreamListener(
      (_, _) => decoded.complete(),
      onError: (Object error, StackTrace? stack) =>
          decoded.completeError(error, stack),
    );
    stream.addListener(listener);
    client.responses.single.complete(ImageResponse());
    await tester.pump();
    // Image decoding crosses the engine and FakeAsync queues. Advance both
    // until the decoded frame arrives, rather than awaiting a fake-zone
    // completer while its queue cannot run.
    for (var i = 0; i < 100 && !decoded.isCompleted; i++) {
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 10)),
      );
      await tester.pump();
    }
    expect(decoded.isCompleted, isTrue);
    stream.removeListener(listener);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('shop-media-fallback')), findsNothing);
    expect(
      find.bySemanticsLabel('Synthetic repair shop photo'),
      findsOneWidget,
    );
    expect(client.calls, hasLength(1));
    expect(tester.takeException(), isNull);
    semantics.dispose();
  });

  imageTest('long shop name and image credit fit narrow large-text cards', (
    tester,
  ) async {
    client.fail = true;
    await mount(
      tester,
      DiscoveryProviderCard(
        provider: shop(
          name: 'A long synthetic collision and paintless dent repair shop',
          media: logo(),
        ),
        onRequest: () {},
        onSave: () {},
        favorites: const ['PDR'],
      ),
      width: 320,
      scale: 1.8,
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Change or remove saved choice'));
    expect(find.text('Your dedicated shop: PDR'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
