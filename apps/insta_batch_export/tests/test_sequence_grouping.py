import unittest
from datetime import datetime, timedelta
from pathlib import Path

from apps.insta_batch_export.core.media_scan import MediaItem
from apps.insta_batch_export.core.sequence_grouping import group_sequences


def make_item(pos, timestamp, mount_id, seq_id):
    basename = "VID_%s_00_%s.insv" % (timestamp.strftime("%Y%m%d_%H%M%S"), seq_id)
    video_path = Path("/media/vox") / mount_id / "DCIM" / "Camera01" / basename
    return MediaItem(
        video_path=video_path,
        timestamp=timestamp,
        seq_id=seq_id,
        stem=Path(basename).stem,
        basename=basename,
        mount_id=mount_id,
        mount_path=Path("/media/vox") / mount_id,
        lrv_path=None,
        has_lrv=False,
    )


class SequenceGroupingTests(unittest.TestCase):
    def test_group_sequences_matches_timestamps_across_positions_even_when_seq_ids_differ(self):
        base = datetime(2026, 5, 21, 19, 12, 37)
        items_by_pos = {
            "head": [make_item("head", base, "3234-3330", "006")],
            "left_wrist": [make_item("left_wrist", base + timedelta(seconds=1), "3832-3630", "003")],
            "right_wrist": [make_item("right_wrist", base + timedelta(seconds=2), "3934-3330", "017")],
        }

        rows = group_sequences(items_by_pos, tolerance_seconds=3)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.label, "20260521_191237")
        self.assertEqual(row.date, "2026-05-21")
        self.assertTrue(row.complete)
        self.assertEqual(row.missing_positions, [])
        self.assertEqual(set(row.items_by_pos), {"head", "left_wrist", "right_wrist"})
        self.assertEqual(row.items_by_pos["left_wrist"].seq_id, "003")

    def test_group_sequences_reports_missing_positions(self):
        base = datetime(2026, 5, 21, 19, 12, 37)
        items_by_pos = {
            "head": [make_item("head", base, "3234-3330", "006")],
            "left_wrist": [],
            "right_wrist": [make_item("right_wrist", base + timedelta(seconds=2), "3934-3330", "017")],
        }

        rows = group_sequences(items_by_pos, tolerance_seconds=3)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertFalse(row.complete)
        self.assertEqual(row.missing_positions, ["left_wrist"])
        self.assertEqual(set(row.items_by_pos), {"head", "right_wrist"})

    def test_group_sequences_splits_rows_outside_tolerance(self):
        base = datetime(2026, 5, 21, 19, 12, 37)
        items_by_pos = {
            "head": [
                make_item("head", base, "3234-3330", "006"),
                make_item("head", base + timedelta(seconds=10), "3234-3330", "007"),
            ],
            "left_wrist": [
                make_item("left_wrist", base + timedelta(seconds=1), "3832-3630", "003"),
                make_item("left_wrist", base + timedelta(seconds=11), "3832-3630", "004"),
            ],
        }

        rows = group_sequences(items_by_pos, tolerance_seconds=3)

        self.assertEqual([row.label for row in rows], ["20260521_191237", "20260521_191247"])
        self.assertTrue(all(row.complete for row in rows))


if __name__ == "__main__":
    unittest.main()
