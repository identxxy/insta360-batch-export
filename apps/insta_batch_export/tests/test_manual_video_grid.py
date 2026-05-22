import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from apps.insta_batch_export.gui_app import (
    POSITIONS,
    PROFILE_RESOLUTION_PRESETS,
    GuiMediaItem,
    _build_manual_video_grid,
    _build_output_path,
    _default_exporter_path,
    _video_cell_label,
    _video_item_colors,
    _video_cell_key,
)


def make_item(pos, index, timestamp):
    return GuiMediaItem(
        mount_id="CARD_" + pos,
        mount_path="/media/vox/CARD_" + pos,
        video_path="/media/vox/CARD_%s/DCIM/Camera01/VID_%s_00_%03d.insv"
        % (pos, timestamp.strftime("%Y%m%d_%H%M%S"), index),
        timestamp=timestamp,
        seq_id="%03d" % index,
        basename="VID_%s_00_%03d.insv"
        % (timestamp.strftime("%Y%m%d_%H%M%S"), index),
        has_lrv=True,
    )


class ManualVideoGridTests(unittest.TestCase):
    def test_resolution_presets_include_4k_8k_smoke_and_preview_without_5_7k(self):
        self.assertEqual(PROFILE_RESOLUTION_PRESETS[0], "3840x1920")
        self.assertIn("7680x3840", PROFILE_RESOLUTION_PRESETS)
        self.assertIn("1920x960", PROFILE_RESOLUTION_PRESETS)
        self.assertIn("960x480", PROFILE_RESOLUTION_PRESETS)
        self.assertNotIn("5760x2880", PROFILE_RESOLUTION_PRESETS)

    def test_default_exporter_path_can_be_overridden_for_bundles(self):
        previous = os.environ.get("INSTA_EXPORTER_PATH")
        os.environ["INSTA_EXPORTER_PATH"] = "/opt/insta-bundle/bin/insta_media_exporter"
        try:
            self.assertEqual(
                _default_exporter_path(),
                Path("/opt/insta-bundle/bin/insta_media_exporter"),
            )
        finally:
            if previous is None:
                os.environ.pop("INSTA_EXPORTER_PATH", None)
            else:
                os.environ["INSTA_EXPORTER_PATH"] = previous

    def test_build_manual_video_grid_uses_recent_n_per_position_independently(self):
        base = datetime(2026, 5, 21, 19, 12, 37)
        head_items = [make_item("head", idx, base + timedelta(seconds=idx)) for idx in range(3)]
        wrist_items = [make_item("left_wrist", 8, base - timedelta(seconds=60))]
        items_by_pos = {pos: [] for pos in POSITIONS}
        items_by_pos["head"] = head_items
        items_by_pos["left_wrist"] = wrist_items

        rows = _build_manual_video_grid(
            items_by_pos,
            {"head": 2, "left_wrist": 10},
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["head"].seq_id, "002")
        self.assertEqual(rows[1]["head"].seq_id, "001")
        self.assertEqual(rows[0]["left_wrist"].seq_id, "008")
        self.assertNotIn("left_wrist", rows[1])

    def test_video_cell_key_is_stable_and_position_scoped(self):
        timestamp = datetime(2026, 5, 21, 19, 12, 37)
        item = make_item("head", 1, timestamp)

        self.assertEqual(_video_cell_key("head", item), "head|/media/vox/CARD_head/DCIM/Camera01/VID_20260521_191237_00_001.insv")
        self.assertNotEqual(
            _video_cell_key("head", item),
            _video_cell_key("left_wrist", item),
        )

    def test_video_item_colors_keep_dark_text_on_light_backgrounds(self):
        cases = [
            ("", False),
            ("", True),
            ("pending", True),
            ("running", True),
            ("done", True),
            ("failed", True),
            ("skipped", True),
        ]

        for status, selected in cases:
            with self.subTest(status=status, selected=selected):
                background, foreground = _video_item_colors(status, selected)
                self.assertTrue(background.startswith("#"))
                self.assertEqual(foreground, "#111827")

    def test_gui_output_path_uses_position_directory_without_date_dir(self):
        timestamp = datetime(2026, 5, 21, 19, 12, 37)
        item = make_item("head", 1, timestamp)

        self.assertEqual(
            _build_output_path("/tmp/out", "head", item),
            Path("/tmp/out") / "head" / "20260521_191237_CARD_head_001.mp4",
        )

    def test_video_cell_label_includes_source_recording_metadata(self):
        timestamp = datetime(2026, 5, 21, 19, 12, 37)
        item = GuiMediaItem(
            mount_id="CARD_head",
            mount_path="/media/vox/CARD_head",
            video_path="/media/vox/CARD_head/DCIM/Camera01/VID_20260521_191237_00_001.insv",
            timestamp=timestamp,
            seq_id="001",
            basename="VID_20260521_191237_00_001.insv",
            has_lrv=True,
            recording_label="2x 1920x1920 @ 29.97fps",
        )

        self.assertIn("2x 1920x1920 @ 29.97fps", _video_cell_label(item))


if __name__ == "__main__":
    unittest.main()
