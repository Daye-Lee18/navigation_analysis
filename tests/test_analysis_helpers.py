import sys
import types
import unittest

try:
    import pandas as pd
except ModuleNotFoundError:
    pd = None


def _install_import_stubs() -> None:
    folium = types.ModuleType("folium")
    sys.modules.setdefault("folium", folium)

    matplotlib = types.ModuleType("matplotlib")
    matplotlib.rcParams = {}
    pyplot = types.ModuleType("matplotlib.pyplot")
    pyplot.subplots = lambda *args, **kwargs: (None, None)
    pyplot.tight_layout = lambda: None
    pyplot.savefig = lambda *args, **kwargs: None
    pyplot.close = lambda *args, **kwargs: None
    matplotlib.pyplot = pyplot
    sys.modules.setdefault("matplotlib", matplotlib)
    sys.modules.setdefault("matplotlib.pyplot", pyplot)

    psycopg2 = types.ModuleType("psycopg2")
    sys.modules.setdefault("psycopg2", psycopg2)

    requests = types.ModuleType("requests")
    sys.modules.setdefault("requests", requests)

    shapely = types.ModuleType("shapely")
    shapely_wkt = types.ModuleType("shapely.wkt")
    shapely_geometry = types.ModuleType("shapely.geometry")
    shapely_geometry.LineString = type("LineString", (), {})
    shapely_geometry.MultiLineString = type("MultiLineString", (), {})
    shapely.wkt = shapely_wkt
    shapely.geometry = shapely_geometry
    sys.modules.setdefault("shapely", shapely)
    sys.modules.setdefault("shapely.wkt", shapely_wkt)
    sys.modules.setdefault("shapely.geometry", shapely_geometry)


if pd is not None:
    _install_import_stubs()
    from navigation_analysis import voc1_analysis, voc2_analysis
else:
    voc1_analysis = None
    voc2_analysis = None


@unittest.skipUnless(pd is not None, "pandas is required for navigation_analysis tests")
class FilterPeakTests(unittest.TestCase):
    def test_filter_peak_filters_hours_weekdays_and_function_types(self) -> None:
        df = pd.DataFrame(
            [
                {"링크아이디": "A", "시간": 7, "요일": "월", "기능유형구분": "주간선도로"},
                {"링크아이디": "B", "시간": 8, "요일": "토", "기능유형구분": "주간선도로"},
                {"링크아이디": "C", "시간": 11, "요일": "화", "기능유형구분": "주간선도로"},
                {"링크아이디": "D", "시간": 9, "요일": "수", "기능유형구분": "지선도로"},
                {"링크아이디": "E", "시간": 9, "요일": "목", "기능유형구분": "보조간선도로"},
            ]
        )

        result = voc1_analysis.filter_peak(df)

        self.assertEqual(result["링크아이디"].tolist(), ["A", "E"])

    def test_filter_peak_skips_function_filter_when_column_missing(self) -> None:
        df = pd.DataFrame(
            [
                {"링크아이디": "A", "시간": 7, "요일": "월"},
                {"링크아이디": "B", "시간": 7, "요일": "일"},
                {"링크아이디": "C", "시간": 12, "요일": "화"},
            ]
        )

        result = voc1_analysis.filter_peak(df)

        self.assertEqual(result["링크아이디"].tolist(), ["A"])


@unittest.skipUnless(pd is not None, "pandas is required for navigation_analysis tests")
class Voc2HelperTests(unittest.TestCase):
    def test_calc_route_time_returns_minutes_by_hour(self) -> None:
        route_df = pd.DataFrame(
            [
                {"시간": 7, "속도_kmh": 60.0},
                {"시간": 7, "속도_kmh": 30.0},
                {"시간": 8, "속도_kmh": 45.0},
            ]
        )

        result = voc2_analysis.calc_route_time(route_df, dist_km=9.0)

        self.assertAlmostEqual(result.loc[7], 12.0)
        self.assertAlmostEqual(result.loc[8], 12.0)

    def test_load_routes_limits_route_members_by_road_name(self) -> None:
        olympic_ids = [f"A{i:02d}" for i in range(20)]
        detour_ids = [f"B{i:02d}" for i in range(50)]

        rows = []
        for idx, link_id in enumerate(olympic_ids):
            rows.append({"링크아이디": link_id, "도로명": "올림픽대로", "시간": idx % 3 + 7, "속도_kmh": 60.0})
        for idx, link_id in enumerate(detour_ids[:25]):
            rows.append({"링크아이디": link_id, "도로명": "동일로", "시간": idx % 3 + 7, "속도_kmh": 35.0})
        for idx, link_id in enumerate(detour_ids[25:]):
            rows.append({"링크아이디": link_id, "도로명": "천호대로", "시간": idx % 3 + 7, "속도_kmh": 40.0})
        rows.append({"링크아이디": "Z99", "도로명": "강변북로", "시간": 8, "속도_kmh": 70.0})

        main_df = pd.DataFrame(rows)

        route_a, route_b = voc2_analysis.load_routes(main_df)

        self.assertEqual(route_a["링크아이디"].nunique(), 15)
        self.assertTrue((route_a["도로명"] == "올림픽대로").all())
        self.assertEqual(route_b["링크아이디"].nunique(), 40)
        self.assertTrue(route_b["도로명"].isin(["동일로", "천호대로"]).all())


if __name__ == "__main__":
    unittest.main()
