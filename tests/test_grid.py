import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from test_panel import demo
from panel import Panel
from selection import CELLS, COLUMNS, Selection, parse_entities
from views import editor_page, render


class GridTests(unittest.TestCase):
    def test_legacy_size_migrates_and_vertical_widgets_persist(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'selection.json'
            path.write_text('[{"id":"sensor.a","width":2,"cell":4}]')
            selection = Selection((), path)
            self.assertEqual((selection.entities[0].cell, selection.entities[0].width, selection.entities[0].height), (4, 2, 1))
            selection.save([{'id': 'sensor.a', 'width': 2, 'height': 2, 'cell': 4},
                            {'id': 'sensor.b', 'height': 2, 'cell': 6}], '')
            self.assertEqual([(e.width, e.height) for e in Selection((), path).entities], [(2, 2), (1, 2)])

    def test_overlap_on_second_row_and_overflow_are_rejected(self):
        for cell in (4, 5):
            for widgets in ([{'id': 'sensor.a', 'width': 2, 'height': 2, 'cell': 0}, {'id': 'sensor.b', 'cell': cell}],
                            [{'id': 'sensor.b', 'cell': cell}, {'id': 'sensor.a', 'width': 2, 'height': 2, 'cell': 0}]):
                with self.assertRaisesRegex(ValueError, 'overlap'):
                    parse_entities(widgets)
        with self.assertRaises(ValueError):
            parse_entities([{'id': 'sensor.a', 'cell': CELLS - COLUMNS, 'height': 2}])
        with self.assertRaises(ValueError):
            parse_entities([{'id': 'sensor.a', 'height': True}])
        selection = Selection(())
        selection.save([{'id': 'sensor.a', 'width': 2, 'height': 2}], '')
        selection.add('sensor.b', 'B')
        self.assertEqual(selection.entities[1].cell, 2)

    def test_climate_mode_chooser_is_explicit_and_does_not_need_apply(self):
        panel = Panel(demo())
        panel.selection.save([{'id': 'climate.demo_hall', 'cell': 0, 'height': 2},
                              {'id': 'sensor.demo_temperature', 'cell': 1}], '', demo=True)
        panel.poll()
        page = render(panel.settings, panel.snapshot, datetime.now(timezone.utc), panel.entities, 'csrf')
        self.assertIn('data-size="1x2"', page)
        self.assertIn('class="climate-disclosure"', page)
        self.assertIn('name="value" value="cool"', page)
        self.assertNotIn('>Apply</button>', page)
        editor = editor_page(panel, 'csrf')
        for width, height in ((1, 1), (2, 1), (1, 2), (2, 2)):
            self.assertIn(f'data-width="{width}" data-height="{height}"', editor)
