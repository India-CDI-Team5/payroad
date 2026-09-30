from geo import haversine_km
from sampler import sample_route


def gaps_km(points):
    return [haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(points, points[1:])]


def test_samples_are_evenly_spaced_by_distance_not_by_coordinate_index():
    # Dense coordinates at the start, one long straight segment after: index spacing would
    # put every sample in the first 1 km.
    route = [[77.600 + i * 0.001, 12.9] for i in range(10)] + [[77.700, 12.9]]
    pts = sample_route(route, 4)
    assert pts[0] == [77.6, 12.9] and pts[-1] == [77.7, 12.9]
    gaps = gaps_km(pts)
    assert max(gaps) - min(gaps) < 1e-6


def test_short_coordinate_list_still_gives_distinct_points():
    # Two coordinates, four samples: the old index arithmetic gave interval 0 and repeated a point.
    pts = sample_route([[77.60, 12.90], [77.66, 12.90]], 4)
    assert len({tuple(round(v, 6) for v in p) for p in pts}) == 4


def test_zero_length_route():
    assert sample_route([[77.6, 12.9], [77.6, 12.9]], 3) == [[77.6, 12.9]] * 3
