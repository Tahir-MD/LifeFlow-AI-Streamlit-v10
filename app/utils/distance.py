from math import radians, sin, cos, sqrt, atan2

EARTH_RADIUS_KILOMETERS = 6371.0


def calculate_distance_kilometers(
    latitude_one: float,
    longitude_one: float,
    latitude_two: float,
    longitude_two: float,
) -> float:
    """
    Calculates the straight line distance between two points on the
    earth given their latitude and longitude, in kilometers.
    """
    lat_one_radians = radians(latitude_one)
    lat_two_radians = radians(latitude_two)
    delta_lat = radians(latitude_two - latitude_one)
    delta_lon = radians(longitude_two - longitude_one)

    a = sin(delta_lat / 2) ** 2 + cos(lat_one_radians) * cos(lat_two_radians) * sin(delta_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return EARTH_RADIUS_KILOMETERS * c
