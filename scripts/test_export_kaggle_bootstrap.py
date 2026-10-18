import base64
import re
import unittest

from export_kaggle_bootstrap import build_cell


class ExportKaggleBootstrapTests(unittest.TestCase):
    def test_cell_embeds_pipeline_as_base64(self) -> None:
        source = b'print("hello from pipeline")\n'
        cell = build_cell(source)
        match = re.search(r'b64decode\("([^"]+)"\)', cell)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(base64.b64decode(match.group(1)), source)
        self.assertIn("/kaggle/working/four_player_kaggle_real_pipeline.py", cell)
        self.assertIn("eloi-v4-selfplay-training", cell)
        self.assertIn('"all"', cell)


if __name__ == "__main__":
    unittest.main()
