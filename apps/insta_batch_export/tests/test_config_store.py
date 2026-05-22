import json
import tempfile
import unittest
from pathlib import Path

from apps.insta_batch_export.core import config_store


class ConfigStoreTests(unittest.TestCase):
    def test_default_config_has_show_last_n_for_each_position(self):
        config = config_store.default_config()

        self.assertEqual(
            config["show_last_n"],
            {pos: 10 for pos in config_store.POSITIONS},
        )
        self.assertEqual(
            config["profile_by_pos"],
            {pos: config_store.DEFAULT_PROFILE_NAME for pos in config_store.POSITIONS},
        )
        self.assertEqual(
            config["profiles"][config_store.DEFAULT_PROFILE_NAME],
            {
                "output_size": "3840x1920",
                "enable_flowstate": True,
                "enable_denoise": True,
                "enable_direction_lock": False,
            },
        )

    def test_load_and_save_sanitizes_show_last_n(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "show_last_n": {
                            "head": "3",
                            "left_wrist": 0,
                            "right_wrist": "bad",
                            "left_ankle": 12,
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = config_store.load_config(config_path)

            self.assertEqual(config["show_last_n"]["head"], 3)
            self.assertEqual(config["show_last_n"]["left_wrist"], 1)
            self.assertEqual(config["show_last_n"]["right_wrist"], 10)
            self.assertEqual(config["show_last_n"]["left_ankle"], 12)
            self.assertEqual(config["show_last_n"]["right_ankle"], 10)

            saved_path = config_store.save_config(config, config_path)
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["show_last_n"], config["show_last_n"])

    def test_load_and_save_sanitizes_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "Fast 2K": {
                                "output_size": "1920x960",
                                "enable_flowstate": False,
                                "enable_denoise": False,
                                "enable_direction_lock": True,
                            },
                            "Bad": {"output_size": "bad"},
                        },
                        "profile_by_pos": {
                            "head": "Fast 2K",
                            "left_wrist": "missing",
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = config_store.load_config(config_path)

            self.assertEqual(config["profiles"]["Fast 2K"]["output_size"], "1920x960")
            self.assertTrue(config["profiles"]["Fast 2K"]["enable_flowstate"])
            self.assertFalse(config["profiles"]["Fast 2K"]["enable_denoise"])
            self.assertTrue(config["profiles"]["Fast 2K"]["enable_direction_lock"])
            self.assertEqual(config["profiles"]["Bad"]["output_size"], "3840x1920")
            self.assertEqual(config["profile_by_pos"]["head"], "Fast 2K")
            self.assertEqual(
                config["profile_by_pos"]["left_wrist"],
                config_store.DEFAULT_PROFILE_NAME,
            )


if __name__ == "__main__":
    unittest.main()
