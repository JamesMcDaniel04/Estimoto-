"""Official business profiles for shops missing or stale in public map data.

Coordinates are explicitly ZIP centroids, not invented storefront locations.
Contact and service evidence is reviewed separately from map completeness.
"""
from .reviewed_shops import current

ENTRIES = [
    {'source_id': 'bluewater-performance-denver', 'name': 'Bluewater Performance',
     'address': '6425 Washington St. #18, Denver, CO 80229', 'city': 'Denver',
     'postal_code': '80229', 'point': [39.8671, -104.9227],
     'phone': '+13038007193', 'email': 'sales@bwperformance.com',
     'website': 'https://bwperformance.com/',
     'verification_url': 'https://bwperformance.com/about-us/',
     'service_source_url': 'https://bwperformance.com/audi-service-repair-denver/',
     'checked_at': '2026-09-14', 'listed_makes': ['Audi', 'BMW', 'Porsche', 'Volkswagen'],
     'description': 'European vehicle maintenance, diagnostics, repair and performance upgrades. Audi, BMW, Porsche and Volkswagen services listed on the official website.',
     'service_details': ['European vehicle repair', 'Audi maintenance and repair', 'Diagnostics', 'Performance upgrades'],
     'superseded_osm_ids': []},
    {'source_id': 'eurowerkz-motorsport-denver', 'name': 'EuroWerkz Motorsport',
     'address': '1465 South Cherokee Street, Denver, CO 80223', 'city': 'Denver',
     'postal_code': '80223', 'point': [39.7002, -105.0028],
     'phone': '+13034210365', 'email': 'info@Eurowerkzms.com',
     'website': 'https://www.eurowerkzmotorsport.com/',
     'verification_url': 'https://www.eurowerkzmotorsport.com/',
     'service_source_url': 'https://www.eurowerkzmotorsport.com/',
     'checked_at': '2026-09-14', 'listed_makes': ['Audi', 'BMW', 'Mini', 'Porsche', 'Volkswagen'],
     'description': 'European vehicle maintenance, diagnostics, repair and performance upgrades. Audi, BMW, Mini, Porsche and Volkswagen services listed on the official website.',
     'service_details': ['European vehicle repair', 'Audi maintenance and repair', 'Diagnostics', 'Performance upgrades'],
     'superseded_osm_ids': ['way:902832475']},
]


def catalog():
    return {entry['source_id']: entry for entry in ENTRIES if current(entry)}


def listing(entry):
    return {**entry, 'id': 'official:' + entry['source_id'], 'source': 'official_website',
            'source_url': entry['verification_url'], 'kind': 'shop', 'postal_codes': [],
            'specialties': ['maintenance', 'mechanical'],
            'specialty_evidence': [{'specialty': s, 'basis': 'official_website',
                                   'source_url': entry['service_source_url']} for s in ['maintenance', 'mechanical']],
            'make_evidence_basis': 'official_website',
            'vehicle_match': {'status': 'not_verified', 'make': None, 'basis': None},
            'verification': {'status': 'contact_confirmed', 'checked_at': entry['checked_at'],
                             'address': entry['address'], 'source_url': entry['verification_url'],
                             'scope': 'Published address, contact and services checked on the official website.'},
            'distance_basis': 'zip_centroid', 'coordinate_source': 'https://api.zippopotam.us/us/' + entry['postal_code'],
            'mobile_service': False, 'mobile_status': 'unknown', 'accepting_requests': False,
            'request_modes': [], 'favorite': False, 'media': None}
