// Run through scripts/smoke_api.py --flutter-client against its isolated API.
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:estimoto_plus/data/api_repository.dart';
import 'package:estimoto_plus/data/repository.dart';

void check(bool condition, String message) {
  if (!condition) throw StateError(message);
}

Future<void> main() async {
  final origin = Platform.environment['PLUS_SMOKE_API'];
  if (origin == null || Uri.parse(origin).host != '127.0.0.1') {
    throw StateError('The isolated loopback smoke server is required.');
  }
  final session = await http.post(Uri.parse('$origin/v1/dev/session'));
  check(session.statusCode == 200, 'Local demo session failed.');
  final token = (jsonDecode(session.body) as Map)['access_token'] as String;
  final api = ApiPlusRepository(baseUrl: origin, token: () async => token);
  try {
    final initial = await api.bootstrap();
    check(initial.capabilities.demo, 'Expected explicitly isolated API demo.');
    final vehicle = await api.saveVehicle({
      'year': 2024,
      'make': 'Toyota',
      'model': 'Camry',
      'nickname': 'Flutter socket car',
      'vin': '',
      'mileage': 8200,
      'insurer': '',
      'policy_number': '',
    });
    final vehicleId = vehicle['id'] as String;
    final updated = await api.saveVehicle({'mileage': 8300}, id: vehicleId);
    check(updated['mileage'] == 8300, 'Vehicle edit did not persist.');
    final draft = await api.createEstimate({
      'vehicle_id': vehicleId,
      'discipline': 'collision',
      'description': 'Socket test bumper damage.',
      'claim_number': '',
      'date_of_loss': null,
    });
    check(
      draft['amount_cents'] == null && draft['status'] == 'draft',
      'Draft invented a quote.',
    );
    final answer = await api.askAssistant({
      'message': 'Find dent repair',
      'vehicle_id': vehicleId,
      'postal_code': '80202',
      'mobile_only': false,
    });
    check(
      answer.providers.isNotEmpty,
      'Assistant did not return the seeded provider.',
    );
    final body = <String, dynamic>{
      'vehicle_id': vehicleId,
      'provider_id': answer.providers.first.id,
      'specialty': 'pdr',
      'description': 'Repair my door dent.',
      'preferred_time': 'Next week',
      'share_contact': true,
    };
    final key = 'flutter-socket-${DateTime.now().microsecondsSinceEpoch}';
    try {
      await api.createRequest({
        ...body,
        'provider_id': 'missing-provider',
      }, '$key-rejected');
      throw StateError('Unknown provider accepted a request.');
    } on PlusApiException catch (error) {
      check(
        error.statusCode == 409 && error.code == 'request_not_created',
        'Definitive rejection lost its recovery code.',
      );
    }
    final request = await api.createRequest(body, key);
    final replay = await api.createRequest(body, key);
    check(request['id'] == replay['id'], 'Request replay created a duplicate.');
    check(
      request['status'] == 'requested' &&
          request['delivery_status'] == 'local_preview',
      'Demo request claimed a real delivery or booking.',
    );
    await api.cancelRequest(request['id'] as String);
    final reminder = await api.addReminder({
      'vehicle_id': vehicleId,
      'title': 'Check tire pressure',
      'due_date': null,
      'due_mileage': 10000,
    });
    await api.completeReminder(reminder['id'] as String);
    final finalState = await api.bootstrap();
    check(
      finalState.vehicle(vehicleId)?.mileage == 8300,
      'Bootstrap lost garage data.',
    );
    check(
      finalState.requests.firstWhere((r) => r.id == request['id']).status ==
          'cancelled',
      'Bootstrap lost cancellation.',
    );
    check(
      finalState.reminders.firstWhere((r) => r.id == reminder['id']).completed,
      'Bootstrap lost reminder completion.',
    );
    try {
      await api.submitEstimate(draft['id'] as String);
      throw StateError('Unconnected estimator accepted submission.');
    } on PlusApiException catch (error) {
      check(
        error.statusCode == 503,
        'Unexpected unavailable estimator response.',
      );
    }
    stdout.writeln(
      'Flutter HTTP client: garage, draft, matching, consented request replay/cancel and reminder persistence passed.',
    );
  } finally {
    api.close();
  }
}
