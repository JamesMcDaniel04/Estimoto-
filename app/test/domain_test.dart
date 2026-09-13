import 'package:flutter_test/flutter_test.dart';
import 'package:estimoto_plus/domain/models.dart';

void main() {
  test(
    'bootstrap preserves unknown prices and customer request delivery state',
    () {
      final snapshot = PlusSnapshot.fromJson({
        'profile': {'id': 'customer', 'email': 'driver@example.com'},
        'vehicles': [
          {
            'id': 'v1',
            'year': 2024,
            'make': 'Toyota',
            'model': 'Camry',
            'mileage': 12500,
          },
        ],
        'estimates': [
          {
            'id': 'e1',
            'vehicle_id': 'v1',
            'discipline': 'pdr',
            'status': 'draft',
            'amount_cents': null,
          },
        ],
        'requests': [
          {
            'id': 'r1',
            'vehicle_id': 'v1',
            'provider_id': 'p1',
            'status': 'requested',
            'delivery_status': 'queued',
          },
        ],
        'capabilities': {'demo': false, 'live_requests': false},
      });
      expect(snapshot.vehicles.single.title, '2024 Toyota Camry');
      expect(snapshot.estimates.single.amountCents, isNull);
      expect(snapshot.requests.single.statusLabel, 'Waiting for a response');
      expect(snapshot.requests.single.deliveryLabel, 'Waiting to send');
      expect(snapshot.capabilities.liveRequests, isFalse);
    },
  );

  test('provider eligibility requires service, locality and availability', () {
    final provider = ProviderProfile.fromJson({
      'id': 'p1',
      'name': 'Example PDR',
      'specialties': ['pdr'],
      'postal_codes': ['80202'],
      'mobile_service': true,
      'accepting_requests': true,
    });
    expect(
      provider.matches(specialty: 'pdr', postalCode: '80202', mobileOnly: true),
      isTrue,
    );
    expect(
      provider.matches(specialty: 'collision', postalCode: '80202'),
      isFalse,
    );
    expect(provider.matches(specialty: 'pdr', postalCode: '99999'), isFalse);
  });
}
