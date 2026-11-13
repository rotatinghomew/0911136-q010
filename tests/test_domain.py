"""验证现有领域摘要的业务边界。"""
import copy
import json
import unittest
from pathlib import Path

from dispatch_scenarios.analysis import tile_areas


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.tables = json.loads((Path(__file__).resolve().parents[1]/'fixtures/dataset.json').read_text())['tables']

    def test_unknown_area_is_not_dry_area(self):
        tables = copy.deepcopy(self.tables)
        tables['tiles'] = [dict(tables['tiles'][0],rows=1,cols=2,values=[[1,None]],cell_size=10)]
        result = tile_areas(tables)[0]
        self.assertEqual(100,result['wet_area_m2'])
        self.assertEqual(100,result['unknown_area_m2'])
        self.assertEqual(200,result['total_area_m2'])

    def test_nonpositive_resolution_fails(self):
        tables = copy.deepcopy(self.tables)
        tables['tiles'][0]['cell_size'] = 0
        with self.assertRaises(ValueError):
            tile_areas(tables)

    def test_ragged_rows_fail(self):
        tables = copy.deepcopy(self.tables)
        tables['tiles'][0]['values'][0].pop()
        with self.assertRaises(ValueError):
            tile_areas(tables)

    def test_unknown_class_is_not_coerced_to_dry(self):
        tables = copy.deepcopy(self.tables)
        tables['tiles'][0]['values'][0][0] = 9
        with self.assertRaises(ValueError):
            tile_areas(tables)
