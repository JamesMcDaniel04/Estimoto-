import 'dart:convert';
import 'dart:math';
import 'package:flutter/services.dart';
import '../domain/models.dart';
import 'demo_seed.dart';
import 'repository.dart';

/// Isolated, fictional workspace. It never calls an external service.
class DemoPlusRepository extends PlusRepository {
  DemoPlusRepository() : _state = jsonDecode(jsonEncode(demoSeed())) as Json;
  final Json _state;
  final _shops = <Json>[];
  final _outreach = <Json>[];
  final _history = <Json>[];
  final _vehicleImages = <String, VehiclePhoto>{};

  @override
  Future<VehiclePhoto?> getVehicleImage(String id) async {
    final vehicle = Vehicle.fromJson(_find('vehicles', id));
    final own = _vehicleImages[id];
    if (own != null) return own;
    final asset = switch ('${vehicle.year} ${vehicle.make} ${vehicle.model}') {
      '2021 Toyota Tacoma' => '2021-toyota-tacoma',
      '2022 Audi Q5' => '2022-audi-q5',
      _ => null,
    };
    if (asset == null) return null;
    final data = await rootBundle.load('assets/vehicles/$asset.webp');
    return VehiclePhoto(
      data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
      source: 'carsxe',
    );
  }

  @override
  Future<Json> uploadVehicleImage(
    String id,
    Uint8List bytes,
    String filename,
  ) async {
    final vehicle = _find('vehicles', id);
    _vehicleImages[id] = VehiclePhoto(
      Uint8List.fromList(bytes),
      source: 'upload',
    );
    vehicle['image_version'] = _id();
    return {'source': 'upload', 'image_version': vehicle['image_version']};
  }

  @override
  Future<void> deleteVehicleImage(String id) async {
    _find('vehicles', id)['image_version'] = null;
    _vehicleImages.remove(id);
  }

  final _workspaceKeys = <String, (String, Json)>{};
  bool _shareInsights = false;
  Json _copy(Json value) => jsonDecode(jsonEncode(value)) as Json;
  Json _workspaceFind(List<Json> rows, String id) =>
      rows.where((r) => r['id'] == id).firstOrNull ??
      (throw const PlusApiException('This item is no longer available.', 404));
  Json _once(String key, Json body, Json Function() create) {
    final previous = _workspaceKeys[key];
    if (previous != null) {
      if (previous.$1 != jsonEncode(body)) {
        throw const PlusApiException('The saved request details changed.', 409);
      }
      return _copy(previous.$2);
    }
    final result = create();
    _workspaceKeys[key] = (jsonEncode(body), result);
    return _copy(result);
  }

  @override
  Future<List<Json>> listMyShops() async => _shops.map(_copy).toList();
  @override
  Future<Json> saveMyShop(Json body, {String? id}) async {
    if (textOf(body, 'name').trim().isEmpty ||
        (textOf(body, 'email').trim().isEmpty &&
            textOf(body, 'phone').trim().isEmpty)) {
      throw const PlusApiException(
        'Add a shop name and an email or phone.',
        422,
      );
    }
    if (body['vehicle_id'] != null) {
      _find('vehicles', body['vehicle_id'] as String);
    }
    final record = id == null
        ? <String, dynamic>{'id': _id()}
        : _workspaceFind(_shops, id);
    record.addAll(_copy(body));
    if (id == null) _shops.add(record);
    return _copy(record);
  }

  @override
  Future<void> deleteMyShop(String id) async {
    _workspaceFind(_shops, id);
    _shops.removeWhere((r) => r['id'] == id);
  }

  @override
  Future<List<Json>> listShopOutreach() async =>
      _outreach.reversed.map(_copy).toList();
  @override
  Future<Json> getShopOutreach(String id) async =>
      _copy(_workspaceFind(_outreach, id));
  @override
  Future<Json> createShopOutreach(
    Json body,
    String idempotencyKey,
  ) async => _once('draft:$idempotencyKey', body, () {
    final shop = _workspaceFind(_shops, body['shop_id'] as String);
    final vehicleId = body['vehicle_id'] ?? shop['vehicle_id'];
    final vehicle = vehicleId == null
        ? ''
        : Vehicle.fromJson(_find('vehicles', vehicleId as String)).title;
    final profile = _state['profile'] as Json;
    final record = <String, dynamic>{
      'id': _id(),
      'shop_id': shop['id'],
      'shop_name': shop['name'],
      'vehicle_id': vehicleId,
      'recipient_email': shop['email'] ?? '',
      'recipient_phone': shop['phone'] ?? '',
      'subject': 'Service availability request from Estimoto +',
      'message':
          'Service request: ${body['service_summary']}\nVehicle: $vehicle\n${body['customer_message'] ?? ''}',
      'shared_contact': {
        'name': profile['name'],
        'email': profile['email'],
        'phone': profile['phone'],
      },
      'vehicle_summary': vehicle,
      'proposed_slots': body['proposed_slots'],
      'review_hash': List.filled(64, 'd').join(),
      'status': 'draft',
      'delivery_status': 'draft',
    };
    _outreach.add(record);
    return record;
  });
  @override
  Future<Json> authorizeShopOutreach(
    String id,
    Json body,
    String idempotencyKey,
  ) async => _once('authorize:$idempotencyKey', body, () {
    final row = _workspaceFind(_outreach, id);
    if (body['share_contact'] != true ||
        body['review_hash'] != row['review_hash']) {
      throw const PlusApiException(
        'Review and authorize these details first.',
        422,
      );
    }
    row['status'] = 'draft';
    row['delivery_status'] = 'local_preview';
    return row;
  });
  @override
  Future<Json> getKnowledge() async => {
    'records': _history.reversed.map(_copy).toList(),
    'preferences': {'share_aggregate_insights': _shareInsights},
  };
  @override
  Future<Json> addKnowledgeRecord(Json body, String idempotencyKey) async =>
      _once('history:$idempotencyKey', body, () {
        _find('vehicles', body['vehicle_id'] as String);
        final record = <String, dynamic>{
          ..._copy(body),
          'id': _id(),
          'source': 'customer_reported',
          'created_at': DateTime.now().toIso8601String(),
        };
        _history.add(record);
        return record;
      });
  @override
  Future<void> deleteKnowledgeRecord(String id) async {
    _workspaceFind(_history, id);
    _history.removeWhere((r) => r['id'] == id);
  }

  @override
  Future<Json> saveKnowledgePreferences(Json body) async {
    _shareInsights = body['share_aggregate_insights'] == true;
    return {'share_aggregate_insights': _shareInsights};
  }

  final Map<String, (String, String)> _requestsByKey = {};
  final _photoBytes = <String, Uint8List>{};
  final Random _random = Random.secure();
  @override
  bool get isDemo => true;
  String _id() =>
      'demo-${DateTime.now().microsecondsSinceEpoch}-${_random.nextInt(1 << 30)}';
  List<Json> _rows(String key) => (_state[key] as List).cast<Json>();
  Json _find(String key, String id) =>
      _rows(key).where((row) => row['id'] == id).firstOrNull ??
      (throw const PlusApiException('This item is no longer available.', 404));
  @override
  Future<PlusSnapshot> bootstrap() async =>
      PlusSnapshot.fromJson(jsonDecode(jsonEncode(_state)) as Json);
  @override
  Future<Json> saveProfile(Json body) async {
    (_state['profile'] as Json).addAll(body);
    return _state['profile'] as Json;
  }

  @override
  Future<Json> saveVehicle(Json body, {String? id}) async {
    if ((body['make'] as String? ?? '').trim().isEmpty ||
        (body['model'] as String? ?? '').trim().isEmpty) {
      throw const PlusApiException('Add your vehicle make and model.');
    }
    final record = id == null
        ? <String, dynamic>{'id': _id()}
        : _find('vehicles', id);
    record.addAll(body);
    if (id == null) _rows('vehicles').add(record);
    return record;
  }

  @override
  Future<void> deleteVehicle(String id) async {
    _find('vehicles', id);
    if ([
      'estimates',
      'repairs',
      'requests',
      'reminders',
    ].any((key) => _rows(key).any((row) => row['vehicle_id'] == id))) {
      throw const PlusApiException(
        'This vehicle has saved history. Keep it in your garage to preserve those records.',
        409,
      );
    }
    _rows('vehicles').removeWhere((row) => row['id'] == id);
  }

  @override
  Future<Json> createEstimate(Json body) async {
    _find('vehicles', body['vehicle_id'] as String);
    final record = <String, dynamic>{
      ...body,
      'id': _id(),
      'status': 'draft',
      'amount_cents': null,
      'provider_name': '',
      'updated_at': DateTime.now().toIso8601String(),
      'photos': <Json>[],
    };
    _rows('estimates').insert(0, record);
    return record;
  }

  @override
  Future<Json> uploadPhoto(
    String estimateId,
    Uint8List bytes,
    String filename,
    String label,
  ) async {
    final estimate = _find('estimates', estimateId);
    if (estimate['status'] != 'draft') {
      throw const PlusApiException('Photos can only be added to a draft.');
    }
    if (bytes.isEmpty || bytes.length > 10 * 1024 * 1024) {
      throw const PlusApiException('Choose a photo smaller than 10 MB.');
    }
    final photo = <String, dynamic>{'id': _id(), 'label': label};
    _photoBytes['$estimateId/${photo['id']}'] = Uint8List.fromList(bytes);
    (estimate['photos'] as List).add(photo);
    return photo;
  }

  @override
  Future<Uint8List> getPhoto(String estimateId, String photoId) async =>
      _photoBytes['$estimateId/$photoId'] ??
      (throw const PlusApiException('This sample photo is unavailable.', 404));

  @override
  Future<Json> submitEstimate(
    String id,
    Json body,
    String idempotencyKey,
  ) async => throw const PlusApiException(
    'Your demo draft is saved. Live estimating will be available when your shop connects.',
    503,
  );
  @override
  Future<Json> createRequest(Json body, String idempotencyKey) async {
    final fingerprint = jsonEncode(body);
    final existing = _requestsByKey[idempotencyKey];
    if (existing != null) {
      if (existing.$1 != fingerprint) {
        throw const PlusApiException(
          'The request details changed. Review them before sending.',
          409,
        );
      }
      return _find('requests', existing.$2);
    }
    _find('vehicles', body['vehicle_id'] as String);
    final provider = ProviderProfile.fromJson(
      _find('providers', body['provider_id'] as String),
    );
    if (!RegExp(
      r'^\d{5}$',
    ).hasMatch((_state['profile'] as Json)['postal_code'] as String)) {
      throw const PlusApiException(
        'Add your service ZIP code in your profile before sending.',
      );
    }
    if (!provider.matches(
      specialty: body['specialty'] as String,
      postalCode: (_state['profile'] as Json)['postal_code'] as String,
    )) {
      throw const PlusApiException(
        'This provider is not available for that request.',
      );
    }
    if (body['share_contact'] != true) {
      throw const PlusApiException(
        'Choose to share your contact details before sending.',
      );
    }
    final now = DateTime.now().toIso8601String();
    final record = <String, dynamic>{
      ...body,
      'id': _id(),
      'status': 'requested',
      'delivery_status': 'local_preview',
      'created_at': now,
      'updated_at': now,
      'scheduled_at': null,
      'events': <Json>[
        {
          'status': 'requested',
          'message': 'Demo request saved. No provider was contacted.',
          'created_at': now,
        },
      ],
    };
    _rows('requests').add(record);
    _requestsByKey[idempotencyKey] = (fingerprint, record['id'] as String);
    return record;
  }

  @override
  Future<Json> cancelRequest(String id) async {
    final record = _find('requests', id);
    if (!ServiceRequest.fromJson(record).canCancel) {
      throw const PlusApiException(
        'This request can no longer be cancelled here.',
        409,
      );
    }
    record['status'] = 'cancelled';
    record['delivery_status'] = 'cancelled';
    record['updated_at'] = DateTime.now().toIso8601String();
    (record['events'] as List).add({
      'status': 'cancelled',
      'message': 'Request cancelled.',
      'created_at': record['updated_at'],
    });
    return record;
  }

  @override
  Future<Json> addReminder(Json body) async {
    _find('vehicles', body['vehicle_id'] as String);
    if (body['due_date'] == null && body['due_mileage'] == null) {
      throw const PlusApiException('Add a date or mileage for this reminder.');
    }
    final record = <String, dynamic>{...body, 'id': _id(), 'completed': false};
    _rows('reminders').add(record);
    return record;
  }

  @override
  Future<Json> completeReminder(String id) async {
    final row = _find('reminders', id);
    row['completed'] = true;
    return row;
  }

  @override
  Future<AssistantAnswer> askAssistant(Json body) async {
    final message = (body['message'] as String).toLowerCase();
    final vehicleId = body['vehicle_id'] as String?;
    if (vehicleId != null) _find('vehicles', vehicleId);
    final urgent = RegExp(
      r'brakes? (fail(ed|ure)?|not working)|smoke|overheat|fuel leak|burning smell|airbag|high voltage|unsafe|oil pressure',
    ).hasMatch(message);
    if (urgent) {
      return AssistantAnswer.fromJson({
        'reply':
            'That may need urgent professional attention. If you are driving, stop somewhere safe and arrange professional help. I can help you find a repair shop; tell me your ZIP code and what happened.',
        'intent': 'clarify',
        'specialty': 'mechanical',
      });
    }
    if (RegExp(r'schedul|appointment|book').hasMatch(message) &&
        RegExp(r'my shop|saved shop').hasMatch(message)) {
      return AssistantAnswer.fromJson({
        'reply':
            'Choose your saved shop and preferred times, then review the exact request before authorizing it. This demo will not contact a shop.',
        'intent': 'shop_outreach',
      });
    }
    if (RegExp(r'history|last service|parts source').hasMatch(message)) {
      final records = _history
          .where((r) => vehicleId == null || r['vehicle_id'] == vehicleId)
          .toList();
      return AssistantAnswer.fromJson({
        'reply': records.isEmpty
            ? 'You have no service history saved for this car yet. Open Service history to add work you have already had done.'
            : 'Your personal history includes ${records.length} service records. Open Service history to review the dates, shops and parts details you added.',
        'intent': 'history',
      });
    }
    final requested = body['specialty'] as String?;
    final specialty =
        requested ??
        (RegExp(r'dent|ding|hail|pdr').hasMatch(message)
            ? 'pdr'
            : RegExp(
                r'collision|bumper|accident|bodywork|paint',
              ).hasMatch(message)
            ? 'collision'
            : RegExp(
                r'oil|tire|tyre|filter|maintenance|service',
              ).hasMatch(message)
            ? 'maintenance'
            : RegExp(
                r'brake|noise|engine|light|battery|mechanic',
              ).hasMatch(message)
            ? 'mechanical'
            : null);
    final wantsProvider = RegExp(
      r'find|connect|someone|technician|tech\b|shop|book|request|come |repair|fix',
    ).hasMatch(message);
    if (wantsProvider) {
      if (specialty == null) {
        return AssistantAnswer.fromJson({
          'reply':
              'What would you like help with: a dent, collision damage, routine maintenance, or a mechanical issue?',
          'intent': 'clarify',
        });
      }
      final postal = body['postal_code'] as String? ?? '';
      if (postal.isEmpty || vehicleId == null) {
        return AssistantAnswer.fromJson({
          'reply':
              'Choose your vehicle and add a ZIP code in your profile so I can find providers who cover your area.',
          'intent': 'clarify',
          'specialty': specialty,
        });
      }
      final mobile =
          body['mobile_only'] == true ||
          RegExp(
            r'at (my )?(home|house|work)|mobile|driveway|come to',
          ).hasMatch(message);
      final providers = _rows('providers')
          .map(ProviderProfile.fromJson)
          .where(
            (p) => p.matches(
              specialty: specialty,
              postalCode: postal,
              mobileOnly: mobile,
            ),
          )
          .toList();
      return AssistantAnswer.fromJson({
        'reply': providers.isEmpty
            ? 'I could not find a participating provider for that service and ZIP code. You can adjust the service or look for a shop instead of mobile help.'
            : 'These ${mobile ? 'mobile ' : ''}providers cover $postal and handle ${specialtyLabel(specialty).toLowerCase()}. Choose one to review your request. Your preferred time will need their confirmation.',
        'intent': 'find_provider',
        'specialty': specialty,
        'providers': providers.map((p) => p.json).toList(),
      });
    }
    final reply = RegExp(r'oil').hasMatch(message)
        ? 'Your owner’s manual gives the correct oil specification and service interval for your engine. Check the date and mileage of your last service, then save a reminder in your garage. Tell me your vehicle and I can help you find service.'
        : RegExp(r'tire|tyre|pressure').hasMatch(message)
        ? 'Use the cold tire pressure on the driver-door placard or in your owner’s manual. Check with a gauge when the tires are cold. If a tire keeps losing pressure or has visible damage, have a technician inspect it.'
        : RegExp(r'estimate|cost|price').hasMatch(message)
        ? 'An estimate separates the work, parts and labor needed for your repair. Your Estimates tab holds the shop’s figures and review status. I can help you find a PDR technician or collision shop for a specific concern.'
        : 'I can help you understand an estimate, plan routine maintenance, or find a technician. Try “Find mobile dent repair for my car” or “How do I check tire pressure?”';
    final videos =
        RegExp(r'how|video|tutorial').hasMatch(message) &&
            RegExp(r'oil|tire|tyre|pressure|filter').hasMatch(message)
        ? <Json>[
            {
              'title': 'Search YouTube for this maintenance topic',
              'url': Uri.https('www.youtube.com', '/results', {
                'search_query':
                    '${vehicleId == null ? '' : Vehicle.fromJson(_find('vehicles', vehicleId)).title} ${RegExp(r'tire|tyre|pressure').hasMatch(message)
                        ? 'check tire pressure'
                        : message.contains('oil')
                        ? 'oil service'
                        : 'air filter replacement'}',
              }).toString(),
              'source': 'YouTube search · review vehicle compatibility',
            },
          ]
        : <Json>[];
    return AssistantAnswer.fromJson({
      'reply': reply,
      'intent': 'advice',
      'specialty': specialty,
      'videos': videos,
    });
  }
}
