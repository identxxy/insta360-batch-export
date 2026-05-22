import copy
import json
from pathlib import Path


POSITIONS = (
    "head",
    "left_wrist",
    "right_wrist",
    "left_ankle",
    "right_ankle",
)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "insta_batch_export_gui" / "config.json"

DEFAULT_PROFILE_NAME = "Default 4K"

DEFAULT_PROFILE = {
    "output_size": "3840x1920",
    "enable_flowstate": True,
    "enable_denoise": True,
    "enable_direction_lock": False,
}

DEFAULT_CONFIG = {
    "positions": {pos: "" for pos in POSITIONS},
    "show_last_n": {pos: 10 for pos in POSITIONS},
    "profiles": {DEFAULT_PROFILE_NAME: copy.deepcopy(DEFAULT_PROFILE)},
    "profile_by_pos": {pos: DEFAULT_PROFILE_NAME for pos in POSITIONS},
    "output_dir": "",
    "overwrite": False,
    "max_parallel_exports": 1,
}


def default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


def load_config(path=None):
    config_path = Path(path).expanduser() if path is not None else DEFAULT_CONFIG_PATH
    config = default_config()

    if not config_path.exists():
        return config

    try:
        with config_path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
    except (OSError, json.JSONDecodeError):
        return config

    if not isinstance(loaded, dict):
        return config

    positions = loaded.get("positions", {})
    if isinstance(positions, dict):
        seen = set()
        for pos in POSITIONS:
            value = positions.get(pos, "")
            if not isinstance(value, str):
                value = ""
            if value and value in seen:
                value = ""
            if value:
                seen.add(value)
            config["positions"][pos] = value

    output_dir = loaded.get("output_dir", "")
    if isinstance(output_dir, str):
        config["output_dir"] = output_dir

    config["overwrite"] = bool(loaded.get("overwrite", config["overwrite"]))

    try:
        max_parallel_exports = int(
            loaded.get("max_parallel_exports", config["max_parallel_exports"])
        )
    except (TypeError, ValueError):
        max_parallel_exports = config["max_parallel_exports"]
    config["max_parallel_exports"] = max(1, max_parallel_exports)

    show_last_n = loaded.get("show_last_n", {})
    if isinstance(show_last_n, dict):
        for pos in POSITIONS:
            config["show_last_n"][pos] = _sanitize_show_last_n(
                show_last_n.get(pos, config["show_last_n"][pos])
            )

    profiles = loaded.get("profiles", {})
    if isinstance(profiles, dict):
        sanitized_profiles = {}
        for name, profile in profiles.items():
            if not isinstance(name, str) or not name.strip():
                continue
            sanitized_profiles[name.strip()] = _sanitize_profile(profile)
        if sanitized_profiles:
            config["profiles"] = sanitized_profiles
        if DEFAULT_PROFILE_NAME not in config["profiles"]:
            config["profiles"][DEFAULT_PROFILE_NAME] = copy.deepcopy(DEFAULT_PROFILE)

    profile_by_pos = loaded.get("profile_by_pos", {})
    if isinstance(profile_by_pos, dict):
        for pos in POSITIONS:
            value = profile_by_pos.get(pos, DEFAULT_PROFILE_NAME)
            if not isinstance(value, str) or value not in config["profiles"]:
                value = DEFAULT_PROFILE_NAME
            config["profile_by_pos"][pos] = value

    return config


def save_config(config, path=None):
    config_path = Path(path).expanduser() if path is not None else DEFAULT_CONFIG_PATH
    sanitized = default_config()

    if isinstance(config, dict):
        positions = config.get("positions", {})
        if isinstance(positions, dict):
            seen = set()
            for pos in POSITIONS:
                value = positions.get(pos, "")
                if not isinstance(value, str):
                    value = ""
                if value and value in seen:
                    value = ""
                if value:
                    seen.add(value)
                sanitized["positions"][pos] = value

        output_dir = config.get("output_dir", "")
        if isinstance(output_dir, str):
            sanitized["output_dir"] = output_dir

        sanitized["overwrite"] = bool(config.get("overwrite", False))

        try:
            max_parallel_exports = int(config.get("max_parallel_exports", 1))
        except (TypeError, ValueError):
            max_parallel_exports = 1
        sanitized["max_parallel_exports"] = max(1, max_parallel_exports)

        show_last_n = config.get("show_last_n", {})
        if isinstance(show_last_n, dict):
            for pos in POSITIONS:
                sanitized["show_last_n"][pos] = _sanitize_show_last_n(
                    show_last_n.get(pos, sanitized["show_last_n"][pos])
                )

        profiles = config.get("profiles", {})
        if isinstance(profiles, dict):
            sanitized_profiles = {}
            for name, profile in profiles.items():
                if not isinstance(name, str) or not name.strip():
                    continue
                sanitized_profiles[name.strip()] = _sanitize_profile(profile)
            if sanitized_profiles:
                sanitized["profiles"] = sanitized_profiles
            if DEFAULT_PROFILE_NAME not in sanitized["profiles"]:
                sanitized["profiles"][DEFAULT_PROFILE_NAME] = copy.deepcopy(DEFAULT_PROFILE)

        profile_by_pos = config.get("profile_by_pos", {})
        if isinstance(profile_by_pos, dict):
            for pos in POSITIONS:
                value = profile_by_pos.get(pos, DEFAULT_PROFILE_NAME)
                if not isinstance(value, str) or value not in sanitized["profiles"]:
                    value = DEFAULT_PROFILE_NAME
                sanitized["profile_by_pos"][pos] = value

    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(sanitized, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp_path.replace(config_path)
    return config_path


def _sanitize_show_last_n(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 10
    return max(1, min(parsed, 999))


def _sanitize_profile(profile):
    sanitized = copy.deepcopy(DEFAULT_PROFILE)
    if not isinstance(profile, dict):
        return sanitized

    output_size = profile.get("output_size", sanitized["output_size"])
    if isinstance(output_size, str) and _valid_output_size(output_size):
        sanitized["output_size"] = output_size.lower()

    sanitized["enable_flowstate"] = bool(
        profile.get("enable_flowstate", sanitized["enable_flowstate"])
    )
    sanitized["enable_denoise"] = bool(
        profile.get("enable_denoise", sanitized["enable_denoise"])
    )
    sanitized["enable_direction_lock"] = bool(
        profile.get("enable_direction_lock", sanitized["enable_direction_lock"])
    )
    if sanitized["enable_direction_lock"]:
        sanitized["enable_flowstate"] = True
    return sanitized


def _valid_output_size(value):
    parts = value.lower().split("x")
    if len(parts) != 2:
        return False
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError:
        return False
    return width > 0 and height > 0
