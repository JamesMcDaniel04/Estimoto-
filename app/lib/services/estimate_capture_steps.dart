import '../domain/models.dart';

const requiredEstimateViews = [
  'odometer',
  'vin',
  'engine_bay',
  'interior',
  'tire_tread',
  'front',
  'driver',
  'rear',
  'passenger',
];
const pdrDamagePanels = [
  'hood',
  'fender_left',
  'front_door_left',
  'rear_door_left',
  'quarter_left',
  'trunk',
  'quarter_right',
  'rear_door_right',
  'front_door_right',
  'fender_right',
  'roof',
];
const collisionDamagePanels = [
  'front_bumper',
  'grille',
  'headlamps',
  'hood',
  'fender_left',
  'front_door_left',
  'mirrors',
  'rear_door_left',
  'quarter_left',
  'rear_bumper',
  'tail_lamps',
  'trunk',
  'quarter_right',
  'rear_door_right',
  'front_door_right',
  'fender_right',
  'windshield',
  'roof',
];
const _labels = {
  'odometer': 'Odometer',
  'vin': 'Driver-door VIN label',
  'engine_bay': 'Engine bay',
  'interior': 'Interior',
  'tire_tread': 'Tire tread',
  'front': 'Front of vehicle',
  'driver': 'Driver side',
  'rear': 'Rear of vehicle',
  'passenger': 'Passenger side',
  'hood': 'Hood',
  'fender_left': 'Left front fender',
  'front_door_left': 'Left front door',
  'rear_door_left': 'Left rear door',
  'quarter_left': 'Left rear quarter',
  'trunk': 'Trunk / liftgate',
  'quarter_right': 'Right rear quarter',
  'rear_door_right': 'Right rear door',
  'front_door_right': 'Right front door',
  'fender_right': 'Right front fender',
  'roof': 'Roof',
  'front_bumper': 'Front bumper',
  'grille': 'Grille',
  'headlamps': 'Headlamps',
  'mirrors': 'Mirrors',
  'rear_bumper': 'Rear bumper',
  'tail_lamps': 'Tail lamps',
  'windshield': 'Windshield',
};
String captureLabel(String key) {
  for (final prefix in ['hail_close_', 'hail_raking_', 'panel_']) {
    if (key.startsWith(prefix)) {
      final panel = _labels[key.substring(prefix.length)] ?? 'Damage';
      return prefix == 'hail_raking_'
          ? '$panel · angled view'
          : prefix == 'hail_close_'
          ? '$panel · close view'
          : panel;
    }
  }
  return _labels[key] ?? 'Additional photo';
}

String captureGuidance(String key) => switch (key) {
  'vin' =>
    'Photograph the VIN label inside the driver door jamb. Confirm the characters yourself before updating your saved VIN.',
  'odometer' =>
    'Park safely and photograph the dashboard with the mileage clearly visible.',
  'engine_bay' =>
    'With the engine off and cool, open the hood and include the whole engine bay. Do not touch hot or moving parts.',
  'interior' =>
    'Photograph the seats and dashboard from an open door. Remove personal papers from view.',
  'tire_tread' =>
    'With the car parked, photograph the tread grooves on a tire in good light.',
  'front' =>
    'Stand back and include the entire front of the vehicle, from bumper to roof.',
  'driver' =>
    'Include the whole driver side, with both wheels and the roof visible.',
  'rear' =>
    'Stand back and include the entire rear of the vehicle, from bumper to roof.',
  'passenger' =>
    'Include the whole passenger side, with both wheels and the roof visible.',
  _ =>
    'Show the damage on the selected panel in good light. Angle the camera so the dents are visible. You can add another close or wider view afterward.',
};
List<String> estimateRequiredKeys(PlusSnapshot snapshot) {
  final keys = snapshot.capabilities.json['required_estimate_photo_keys'];
  return keys is List && keys.isNotEmpty
      ? keys.cast<String>()
      : requiredEstimateViews;
}

List<String> estimatePanelTypes(PlusSnapshot snapshot, String discipline) {
  final keys =
      snapshot.capabilities.json[discipline == 'pdr'
          ? 'pdr_damage_panel_types'
          : 'collision_damage_panel_types'];
  return keys is List && keys.isNotEmpty
      ? keys.cast<String>()
      : discipline == 'pdr'
      ? pdrDamagePanels
      : collisionDamagePanels;
}

Set<String> savedCaptureKeys(CustomerEstimate estimate) =>
    estimate.photos.map((p) => textOf(p, 'label')).toSet();
List<String> missingEstimateViews(
  PlusSnapshot snapshot,
  CustomerEstimate estimate,
) => estimateRequiredKeys(
  snapshot,
).where((key) => !savedCaptureKeys(estimate).contains(key)).toList();
bool hasDamagePhoto(PlusSnapshot snapshot, CustomerEstimate estimate) =>
    estimatePanelTypes(snapshot, estimate.discipline).any((panel) {
      final saved = savedCaptureKeys(estimate);
      return saved.contains('panel_$panel') ||
          (saved.contains('hail_close_$panel') &&
              saved.contains('hail_raking_$panel'));
    });
bool estimatePhotosReady(PlusSnapshot snapshot, CustomerEstimate estimate) =>
    missingEstimateViews(snapshot, estimate).isEmpty &&
    (estimate.discipline != 'pdr' || hasDamagePhoto(snapshot, estimate));
