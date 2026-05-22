import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from apps.insta_batch_export.core.media_scan import (
    find_lrv_for_video,
    parse_media_filename,
    scan_mounts,
)


class MediaScanTests(unittest.TestCase):
    def test_parse_vid_filename_extracts_timestamp_sequence_and_mount(self):
        path = Path("/media/vox/3234-3330/DCIM/Camera01/VID_20260521_191237_00_006.insv")

        item = parse_media_filename(path)

        self.assertEqual(item.timestamp, datetime(2026, 5, 21, 19, 12, 37))
        self.assertEqual(item.seq_id, "006")
        self.assertEqual(item.stem, "VID_20260521_191237_00_006")
        self.assertEqual(item.basename, "VID_20260521_191237_00_006.insv")
        self.assertEqual(item.mount_id, "3234-3330")
        self.assertEqual(item.mount_path, Path("/media/vox/3234-3330"))
        self.assertEqual(item.video_path, path)

    def test_parse_vid_filename_rejects_non_vid_names(self):
        path = Path("/media/vox/3234-3330/DCIM/Camera01/LRV_20260521_191237_01_006.lrv")

        with self.assertRaises(ValueError):
            parse_media_filename(path)

    def test_find_lrv_for_video_uses_matching_timestamp_and_sequence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            camera_dir = Path(tmpdir) / "3234-3330" / "DCIM" / "Camera01"
            camera_dir.mkdir(parents=True)
            video_path = camera_dir / "VID_20260521_191237_00_006.insv"
            lrv_path = camera_dir / "LRV_20260521_191237_01_006.lrv"
            video_path.touch()
            lrv_path.touch()

            self.assertEqual(find_lrv_for_video(video_path), lrv_path)

    def test_find_lrv_for_video_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            camera_dir = Path(tmpdir) / "3234-3330" / "DCIM" / "Camera01"
            camera_dir.mkdir(parents=True)
            video_path = camera_dir / "VID_20260521_191237_00_006.insv"
            video_path.touch()

            self.assertIsNone(find_lrv_for_video(video_path))

    def test_scan_mounts_returns_media_items_grouped_by_mount(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cam_a = root / "3234-3330" / "DCIM" / "Camera01"
            cam_b = root / "3832-3630" / "DCIM" / "Camera01"
            cam_a.mkdir(parents=True)
            cam_b.mkdir(parents=True)
            video_a = cam_a / "VID_20260521_191237_00_006.insv"
            lrv_a = cam_a / "LRV_20260521_191237_01_006.lrv"
            video_b = cam_b / "VID_20260521_191240_00_003.insv"
            ignored = cam_b / "LRV_20260521_191240_01_004.lrv"
            for path in (video_a, lrv_a, video_b, ignored):
                path.touch()

            items_by_mount = scan_mounts(root)

            self.assertEqual(sorted(items_by_mount), ["3234-3330", "3832-3630"])
            self.assertEqual([item.basename for item in items_by_mount["3234-3330"]], [video_a.name])
            self.assertTrue(items_by_mount["3234-3330"][0].has_lrv)
            self.assertEqual(items_by_mount["3234-3330"][0].lrv_path, lrv_a)
            self.assertEqual([item.basename for item in items_by_mount["3832-3630"]], [video_b.name])
            self.assertFalse(items_by_mount["3832-3630"][0].has_lrv)


if __name__ == "__main__":
    unittest.main()
