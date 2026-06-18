"""Dedupe thresholds and Salesforce field defaults."""

DUPLICATE_THRESHOLD = 85
REVIEW_THRESHOLD = 60
DEFAULT_RADIUS_METERS = 250

# Urbanicity tiers from ZCTA population (nationwide CSV — see ZIP_POPULATION_CSV).
URBAN_POPULATION_MIN = 25_000
SUBURBAN_POPULATION_MIN = 2_500
URBAN_RADIUS_M = 100
SUBURBAN_RADIUS_M = 150
RURAL_RADIUS_M = 250
URBANICITY_DEFAULT_TIER = "suburban"

# Combined dedupe score weights (address fuzzy match + in-radius proximity).
ADDRESS_SCORE_WEIGHT = 0.65
PROXIMITY_SCORE_WEIGHT = 0.35

# Strong address match — duplicate despite geocoder distance noise (same street, different pins).
STRONG_ADDRESS_DUPLICATE_MIN = 95
STRONG_ADDRESS_DUPLICATE_MAX_M = 200

# Geocoder collision — very close pins but clearly different addresses.
GEOCODER_COLLISION_MAX_M = 25
GEOCODER_COLLISION_MAX_ADDRESS = 60

# Outside-radius fuzzy matches never promote to review/duplicate (in-radius only).
OUTSIDE_RADIUS_REVIEW_MAX_M = 0

# Only fuzzy-score Salesforce candidates within this distance of the incoming pin.
FUZZY_PREFILTER_MAX_M = 500

# Flag net-new rows that are close and moderately similar for manual calibration.
POTENTIAL_DUPLICATE_MIN_COMBINED = 50
POTENTIAL_DUPLICATE_MAX_DISTANCE_M = 100

# Proximity-aware promotion when address match is weak but coordinates agree.
PROX_DUPLICATE_MAX_M = 25
PROX_DUPLICATE_MIN_ADDRESS = 75
PROX_REVIEW_MAX_M = 50
PROX_REVIEW_MIN_ADDRESS = 70
PROX_REVIEW_EXTENDED_MAX_M = 100
PROX_REVIEW_EXTENDED_MIN_ADDRESS = 80

SF_OBJECT_NAME = "Site__c"
SF_LAT_FIELD = "Site_Latitude__c"
SF_LNG_FIELD = "Site_Longitude__c"
SF_ZIP_FIELD = "Site_Zip_Code__c"
SF_ADDRESS_FIELD = "Site_Address__c"
SF_CITY_FIELD = "Site_City__c"
SF_STATE_FIELD = "Site_State__c"
