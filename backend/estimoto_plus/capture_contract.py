"""Customer evidence keys: documentation never becomes a pricing panel."""
DOCUMENT_KEYS = ('vin', 'odometer', 'engine_bay', 'interior', 'tire_tread',
                 'front', 'driver', 'rear', 'passenger')
PDR_PANELS = ('hood', 'fender_left', 'front_door_left', 'rear_door_left',
              'quarter_left', 'trunk', 'quarter_right', 'rear_door_right',
              'front_door_right', 'fender_right', 'roof')
COLLISION_PANELS = ('front_bumper', 'grille', 'headlamps', 'hood', 'fender_left',
                    'front_door_left', 'mirrors', 'rear_door_left', 'quarter_left',
                    'rear_bumper', 'tail_lamps', 'trunk', 'quarter_right',
                    'rear_door_right', 'front_door_right', 'fender_right', 'windshield', 'roof')
BODY_STYLES = {'sedan', 'coupe', 'hatchback', 'wagon', 'suv', 'pickup', 'van', 'convertible'}
HINTS = {
    'vin': 'Park safely, open the driver’s door, and find the VIN label on the door jamb near the hinges or latch. Photograph the whole label straight on, with all 17 VIN characters legible. If the label is elsewhere, check your owner’s manual; do not remove trim.',
    'odometer': 'Park safely and photograph the dashboard mileage display with the mileage clearly visible.',
    'engine_bay': 'With the engine off and cool, open the hood and photograph the whole engine bay from the front. Do not touch hot or moving parts.',
    'interior': 'Open the driver’s door. Hold the camera outside the doorway and include the front seats and dashboard.',
    'tire_tread': 'With the car parked, move close to a tire and aim at the tread grooves. Do not crawl under the vehicle.',
    'front': 'Stand back in a safe place and center the whole front of the vehicle in the frame.',
    'driver': 'Stand back safely and photograph the full driver side with both wheels visible.',
    'rear': 'Center the whole rear of the vehicle in the frame from a safe distance.',
    'passenger': 'Stand back safely and photograph the full passenger side with both wheels visible.',
}


def allowed_keys(discipline):
    panels = PDR_PANELS if discipline == 'pdr' else COLLISION_PANELS
    keys = set(DOCUMENT_KEYS) | {'corner_fl', 'corner_fr', 'corner_rl', 'corner_rr', 'roof'}
    keys |= {'panel_' + panel for panel in panels}
    if discipline == 'pdr':
        keys |= {prefix + panel for prefix in ('hail_close_', 'hail_raking_') for panel in PDR_PANELS}
    return keys


def capture_hint(key):
    if key in HINTS:
        return HINTS[key]
    if key.startswith('hail_raking_'):
        return 'Move to a shallow angle across the damaged panel so reflected light reveals the dents. Keep the panel in frame and your footing safe.'
    return 'Photograph the damaged panel with enough surrounding bodywork to identify it. Add a closer view from a safe angle; avoid glare and heavy shadow.'
