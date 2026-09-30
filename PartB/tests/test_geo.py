from geo import haversine_km, in_bbox, nearest_cell, offset, resample


def test_offset_travels_requested_distance():
    lat, lon = offset(12.97, 77.59, 10.0, 45)
    assert abs(haversine_km(12.97, 77.59, lat, lon) - 10.0) < 1e-6


def test_resample_spacing_and_ends():
    line = [(12.90, 77.60), (13.00, 77.60)]            # ~11.1 km due north
    pts = resample(line, 0.5)
    assert pts[0][:2] == line[0] and abs(pts[-1][0] - 13.00) < 1e-9
    gaps = [b[2] - a[2] for a, b in zip(pts, pts[1:])]
    assert all(abs(g - 0.5) < 1e-6 for g in gaps[:-1]) and 0 < gaps[-1] <= 0.5


def test_nearest_cell_and_bbox():
    cells = [(12.90, 77.60), (13.00, 77.60)]
    assert nearest_cell(12.94, 77.60, cells) == 0
    assert nearest_cell(12.96, 77.60, cells) == 1
    assert in_bbox(12.97, 77.59) and not in_bbox(14.0, 77.59)
