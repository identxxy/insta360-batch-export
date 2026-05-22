import importlib
import inspect
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path


try:
    from PySide6.QtCore import Qt, QThread, Signal
    from PySide6.QtGui import QBrush, QColor
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        print(
            "PySide6 is required for the Insta360 batch export GUI.\n"
            "Install it with:\n"
            "  python3 -m pip install -r apps/insta_batch_export/requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core import config_store


POSITIONS = tuple(config_store.POSITIONS)
MEDIA_ROOT = Path("/media/vox")
TIMESTAMP_TOLERANCE_SECONDS = 3
DEFAULT_EXPORTER_PATH = APP_DIR / "cpp_exporter" / "build" / "insta_media_exporter"
PROFILE_RESOLUTION_PRESETS = ("3840x1920", "1920x960", "5760x2880")


def _default_model_root():
    env_value = os.environ.get("INSTA_MEDIA_MODELS_DIR")
    if env_value:
        return str(Path(env_value).expanduser())
    local_models = REPO_ROOT / "libMediaSDK-dev-3.1.1.0-20250922_191110-amd64" / "models"
    if local_models.exists():
        return str(local_models)
    return None


def _try_import_core_module(module_name):
    try:
        return importlib.import_module("core." + module_name), None
    except ImportError as exc:
        return None, exc


media_scan, MEDIA_SCAN_IMPORT_ERROR = _try_import_core_module("media_scan")
sequence_grouping, SEQUENCE_GROUPING_IMPORT_ERROR = _try_import_core_module(
    "sequence_grouping"
)
export_jobs, EXPORT_JOBS_IMPORT_ERROR = _try_import_core_module("export_jobs")


class GuiMediaItem:
    def __init__(
        self,
        mount_id,
        mount_path,
        video_path,
        timestamp,
        seq_id,
        basename,
        has_lrv,
    ):
        self.mount_id = mount_id
        self.mount_path = mount_path
        self.video_path = video_path
        self.timestamp = timestamp
        self.seq_id = seq_id
        self.basename = basename
        self.has_lrv = has_lrv


VIDEO_RE = re.compile(
    r"^VID_(?P<date>\d{8})_(?P<time>\d{6})_(?P<part>\d{2})_(?P<seq>\d+)\.insv$",
    re.IGNORECASE,
)


def _item_value(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _row_value(row, key, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _coerce_datetime(value, basename=None):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        candidates = (
            (text[:19], "%Y-%m-%d %H:%M:%S"),
            (text[:15], "%Y%m%d_%H%M%S"),
            (text[:19], "%Y-%m-%dT%H:%M:%S"),
        )
        for candidate, fmt in candidates:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                pass
    if basename:
        match = VIDEO_RE.match(Path(str(basename)).name)
        if match:
            return datetime.strptime(
                match.group("date") + match.group("time"), "%Y%m%d%H%M%S"
            )
    return None


def _item_timestamp(item):
    return _coerce_datetime(_item_value(item, "timestamp"), _item_basename(item))


def _item_basename(item):
    basename = _item_value(item, "basename")
    if basename:
        return str(basename)
    video_path = _item_video_path(item)
    return Path(video_path).name if video_path else ""


def _item_video_path(item):
    for key in ("video_path", "path", "input_path"):
        value = _item_value(item, key)
        if value:
            return str(value)
    return ""


def _item_mount_id(item):
    mount_id = _item_value(item, "mount_id")
    if mount_id:
        return str(mount_id)
    video_path = _item_video_path(item)
    try:
        rel = Path(video_path).resolve().relative_to(MEDIA_ROOT.resolve())
        return rel.parts[0]
    except (OSError, ValueError, IndexError):
        return ""


def _item_mount_path(item):
    mount_path = _item_value(item, "mount_path")
    if mount_path:
        return str(mount_path)
    mount_id = _item_mount_id(item)
    if mount_id:
        return str(MEDIA_ROOT / mount_id)
    return ""


def _item_seq_id(item):
    seq_id = _item_value(item, "seq_id")
    if seq_id is not None:
        return str(seq_id)
    match = VIDEO_RE.match(_item_basename(item))
    return match.group("seq") if match else ""


def _normalize_media_item(item):
    timestamp = _item_timestamp(item)
    video_path = _item_video_path(item)
    basename = _item_basename(item)
    if not timestamp or not video_path:
        return None
    return GuiMediaItem(
        mount_id=_item_mount_id(item),
        mount_path=_item_mount_path(item),
        video_path=video_path,
        timestamp=timestamp,
        seq_id=_item_seq_id(item),
        basename=basename,
        has_lrv=bool(_item_value(item, "has_lrv", False)),
    )


def _flatten_scan_result(scan_result):
    if scan_result is None:
        return []
    if isinstance(scan_result, dict):
        items = []
        for value in scan_result.values():
            if isinstance(value, dict) and "items" in value:
                items.extend(value.get("items") or [])
            elif isinstance(value, (list, tuple, set)):
                items.extend(value)
            else:
                items.append(value)
        return items
    if isinstance(scan_result, (list, tuple, set)):
        return list(scan_result)
    return [scan_result]


def _find_lrv_for_video(video_path):
    video_path = Path(video_path)
    match = VIDEO_RE.match(video_path.name)
    if not match:
        return False
    pattern = "LRV_{date}_{time}_*_{seq}.lrv".format(
        date=match.group("date"),
        time=match.group("time"),
        seq=match.group("seq"),
    )
    return any(video_path.parent.glob(pattern))


def _fallback_scan_mounts(root):
    root = Path(root)
    items = []
    for video_path in sorted(root.glob("*/DCIM/Camera01/VID_*.insv")):
        match = VIDEO_RE.match(video_path.name)
        if not match:
            continue
        try:
            timestamp = datetime.strptime(
                match.group("date") + match.group("time"), "%Y%m%d%H%M%S"
            )
        except ValueError:
            continue
        mount_path = video_path.parents[2]
        items.append(
            GuiMediaItem(
                mount_id=mount_path.name,
                mount_path=str(mount_path),
                video_path=str(video_path),
                timestamp=timestamp,
                seq_id=match.group("seq"),
                basename=video_path.name,
                has_lrv=_find_lrv_for_video(video_path),
            )
        )
    return items


def _fallback_group_sequences(items_by_pos, tolerance_seconds):
    entries = []
    for pos, items in items_by_pos.items():
        for item in items:
            timestamp = _item_timestamp(item)
            if timestamp:
                entries.append((timestamp, pos, item))
    entries.sort(key=lambda row: row[0])

    clusters = []
    for timestamp, pos, item in entries:
        if not clusters:
            clusters.append({"anchor": timestamp, "entries": [(timestamp, pos, item)]})
            continue
        cluster = clusters[-1]
        delta = abs((timestamp - cluster["anchor"]).total_seconds())
        if delta <= tolerance_seconds:
            cluster["entries"].append((timestamp, pos, item))
        else:
            clusters.append({"anchor": timestamp, "entries": [(timestamp, pos, item)]})

    rows = []
    for cluster in clusters:
        anchor = cluster["anchor"]
        grouped = {}
        for pos in POSITIONS:
            candidates = [entry for entry in cluster["entries"] if entry[1] == pos]
            if candidates:
                grouped[pos] = min(
                    candidates,
                    key=lambda entry: abs((entry[0] - anchor).total_seconds()),
                )[2]
        missing = [pos for pos in POSITIONS if pos not in grouped]
        rows.append(
            {
                "label": anchor.strftime("%Y-%m-%d %H:%M:%S"),
                "date": anchor.date().isoformat(),
                "items_by_pos": grouped,
                "complete": not missing,
                "missing_positions": missing,
            }
        )
    return rows


def _sequence_items(row):
    items_by_pos = _row_value(row, "items_by_pos", {})
    if not isinstance(items_by_pos, dict):
        return {}
    return items_by_pos


def _sequence_label(row):
    label = _row_value(row, "label")
    if label:
        return str(label)
    items_by_pos = _sequence_items(row)
    timestamps = [_item_timestamp(item) for item in items_by_pos.values()]
    timestamps = [timestamp for timestamp in timestamps if timestamp]
    if timestamps:
        return min(timestamps).strftime("%Y-%m-%d %H:%M:%S")
    return "unknown"


def _sequence_complete(row):
    complete = _row_value(row, "complete")
    if complete is not None:
        return bool(complete)
    items_by_pos = _sequence_items(row)
    return all(pos in items_by_pos and items_by_pos[pos] for pos in POSITIONS)


def _sequence_completeness(row):
    items_by_pos = _sequence_items(row)
    count = sum(1 for pos in POSITIONS if items_by_pos.get(pos))
    return "{}/{}".format(count, len(POSITIONS))


def _sanitize_show_last_n(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 10
    return max(1, min(parsed, 999))


def _build_manual_video_grid(items_by_pos, show_last_n_by_pos=None):
    show_last_n_by_pos = show_last_n_by_pos or {}
    columns = {}
    for pos in POSITIONS:
        items = list(items_by_pos.get(pos, []))
        items.sort(key=lambda item: _item_timestamp(item) or datetime.min, reverse=True)
        columns[pos] = items[: _sanitize_show_last_n(show_last_n_by_pos.get(pos, 10))]

    row_count = max((len(items) for items in columns.values()), default=0)
    rows = []
    for row_index in range(row_count):
        row = {}
        for pos in POSITIONS:
            if row_index < len(columns[pos]):
                row[pos] = columns[pos][row_index]
        rows.append(row)
    return rows


def _video_cell_key(pos, item):
    return "{}|{}".format(pos, _item_video_path(item))


def _video_cell_label(item):
    timestamp = _item_timestamp(item)
    first_line = timestamp.strftime("%Y-%m-%d %H:%M:%S") if timestamp else "unknown time"
    seq_id = _item_seq_id(item) or "unknown_seq"
    return "{}\nseq {}\n{}".format(first_line, seq_id, _item_basename(item))


def _video_item_colors(status, selected):
    if status == "done":
        return "#dcfce7", "#111827"
    if status == "failed":
        return "#fee2e2", "#111827"
    if status == "skipped":
        return "#dbeafe", "#111827"
    if status in ("pending", "running"):
        return "#fef3c7", "#111827"
    if selected:
        return "#bfdbfe", "#111827"
    return "#ffffff", "#111827"


def _profile_names(config):
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict) or not profiles:
        return [config_store.DEFAULT_PROFILE_NAME]
    names = sorted(str(name) for name in profiles if str(name).strip())
    if config_store.DEFAULT_PROFILE_NAME in names:
        names.remove(config_store.DEFAULT_PROFILE_NAME)
        names.insert(0, config_store.DEFAULT_PROFILE_NAME)
    return names or [config_store.DEFAULT_PROFILE_NAME]


def _profile_for_pos(config, pos):
    profiles = config.get("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
    profile_by_pos = config.get("profile_by_pos", {})
    if not isinstance(profile_by_pos, dict):
        profile_by_pos = {}
    name = profile_by_pos.get(pos, config_store.DEFAULT_PROFILE_NAME)
    profile = profiles.get(name) or profiles.get(config_store.DEFAULT_PROFILE_NAME)
    if not isinstance(profile, dict):
        profile = config_store.DEFAULT_PROFILE
    output_size = profile.get("output_size", "3840x1920")
    enable_direction_lock = bool(profile.get("enable_direction_lock", False))
    return {
        "name": name if name in profiles else config_store.DEFAULT_PROFILE_NAME,
        "output_size": output_size if isinstance(output_size, str) else "3840x1920",
        "enable_flowstate": bool(profile.get("enable_flowstate", True)) or enable_direction_lock,
        "enable_denoise": bool(profile.get("enable_denoise", True)),
        "enable_direction_lock": enable_direction_lock,
    }


def _build_output_path(output_dir, pos, item):
    timestamp = _item_timestamp(item)
    if timestamp is None:
        timestamp = datetime.now()
    mount_id = _item_mount_id(item) or "unknown_mount"
    seq_id = _item_seq_id(item) or "unknown_seq"
    filename = "{}_{}_{}.mp4".format(
        timestamp.strftime("%Y%m%d_%H%M%S"),
        mount_id,
        seq_id,
    )
    return Path(output_dir) / pos / filename


def _extract_result_value(result, key, default=None):
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _extract_result_status(result):
    status = _extract_result_value(result, "status")
    if status:
        return str(status)
    returncode = _extract_result_value(result, "returncode")
    if returncode == 0:
        return "done"
    if returncode is not None:
        return "failed"
    return "done"


class ExportWorker(QThread):
    status_changed = Signal(str, str)
    message = Signal(str)
    queue_finished = Signal(object)
    queue_failed = Signal(str)

    def __init__(self, task_records, max_parallel_exports, overwrite, parent=None):
        super().__init__(parent)
        self.task_records = task_records
        self.max_parallel_exports = max_parallel_exports
        self.overwrite = overwrite

    def run(self):
        if export_jobs is None or not hasattr(export_jobs, "run_export_queue"):
            self.queue_failed.emit(
                "core.export_jobs.run_export_queue is unavailable; export backend is not ready."
            )
            return

        for record in self.task_records:
            self.status_changed.emit(record["sequence_key"], "pending")

        try:
            results = self._run_export_queue()
        except Exception:
            self.queue_failed.emit(traceback.format_exc())
            return

        self.queue_finished.emit(results)

    def _run_export_queue(self):
        run_export_queue = export_jobs.run_export_queue
        tasks = [record["task"] for record in self.task_records]

        def progress_callback(*args, **kwargs):
            status = kwargs.get("status")
            task = kwargs.get("task")
            result = kwargs.get("result")
            if not status and args:
                for arg in args:
                    candidate = _extract_result_value(arg, "status")
                    if candidate:
                        status = candidate
                        result = arg
                        break
                    if isinstance(arg, str) and arg in (
                        "pending",
                        "running",
                        "done",
                        "failed",
                        "skipped",
                    ):
                        status = arg
                task = task or (args[0] if args else None)

            output_path = _extract_result_value(result, "output_path") or _extract_result_value(
                task, "output_path"
            )
            sequence_key = self._sequence_key_for_output(output_path)
            if sequence_key and status in ("pending", "running"):
                self.status_changed.emit(sequence_key, str(status))

        kwargs = {}
        try:
            signature = inspect.signature(run_export_queue)
            parameters = signature.parameters
        except (TypeError, ValueError):
            parameters = {}

        if "max_parallel_exports" in parameters:
            kwargs["max_parallel_exports"] = self.max_parallel_exports
        elif "max_workers" in parameters:
            kwargs["max_workers"] = self.max_parallel_exports
        elif "parallelism" in parameters:
            kwargs["parallelism"] = self.max_parallel_exports

        if "overwrite" in parameters:
            kwargs["overwrite"] = self.overwrite

        for name in (
            "status_callback",
            "progress_callback",
            "on_status",
            "on_update",
            "on_result",
        ):
            if name in parameters:
                kwargs[name] = progress_callback

        if "exporter_path" in parameters:
            kwargs["exporter_path"] = str(DEFAULT_EXPORTER_PATH)
        if "model_root" in parameters:
            kwargs["model_root"] = str(DEFAULT_MODEL_ROOT)

        if kwargs:
            return run_export_queue(tasks, **kwargs)

        try:
            return run_export_queue(
                tasks,
                max_parallel_exports=self.max_parallel_exports,
                overwrite=self.overwrite,
            )
        except TypeError:
            try:
                return run_export_queue(tasks, self.max_parallel_exports)
            except TypeError:
                return run_export_queue(tasks)

    def _sequence_key_for_output(self, output_path):
        if not output_path:
            return None
        output_path = str(output_path)
        for record in self.task_records:
            if str(record["output_path"]) == output_path:
                return record["sequence_key"]
        return None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Insta360 Batch Export")
        self.resize(1280, 820)

        self.config = config_store.load_config()
        self.items_by_mount = {}
        self.sequence_rows = []
        self.sequence_status = {}
        self.selected_cell_keys = set()
        self.worker = None
        self._updating_assignments = False
        self._updating_profiles = False

        self._build_ui()
        self._load_config_into_widgets()
        self.scan_media()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        top_row = QHBoxLayout()
        self.scan_button = QPushButton("Rescan SD Cards")
        self.scan_button.clicked.connect(self.scan_media)
        self.refresh_table_button = QPushButton("Refresh Table")
        self.refresh_table_button.clicked.connect(self.refresh_sequences)
        self.scan_summary_label = QLabel("")
        top_row.addWidget(self.scan_button)
        top_row.addWidget(self.refresh_table_button)
        top_row.addWidget(self.scan_summary_label, 1)
        root_layout.addLayout(top_row)

        assignments_group = QGroupBox("Camera Position Binding")
        assignments_layout = QFormLayout(assignments_group)
        self.position_combos = {}
        self.show_last_spinboxes = {}
        self.profile_combos = {}
        for pos in POSITIONS:
            row = QHBoxLayout()
            combo = QComboBox()
            combo.currentIndexChanged.connect(self._on_assignment_changed)
            self.position_combos[pos] = combo
            show_last_spinbox = QSpinBox()
            show_last_spinbox.setRange(1, 999)
            show_last_spinbox.setValue(10)
            show_last_spinbox.valueChanged.connect(self._on_show_last_changed)
            self.show_last_spinboxes[pos] = show_last_spinbox
            profile_combo = QComboBox()
            profile_combo.currentIndexChanged.connect(self._on_position_profile_changed)
            self.profile_combos[pos] = profile_combo
            row.addWidget(combo, 1)
            row.addWidget(QLabel("Show last"))
            row.addWidget(show_last_spinbox)
            row.addWidget(QLabel("videos"))
            row.addWidget(QLabel("Profile"))
            row.addWidget(profile_combo)
            assignments_layout.addRow(pos, row)
        root_layout.addWidget(assignments_group)

        output_group = QGroupBox("Export Options")
        output_layout = QFormLayout(output_group)

        output_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Choose output directory")
        self.output_dir_edit.editingFinished.connect(self._on_output_dir_edited)
        self.output_dir_button = QPushButton("Browse")
        self.output_dir_button.clicked.connect(self.choose_output_dir)
        output_row.addWidget(self.output_dir_edit, 1)
        output_row.addWidget(self.output_dir_button)
        output_layout.addRow("Output directory", output_row)

        self.overwrite_checkbox = QCheckBox("Overwrite existing files")
        self.overwrite_checkbox.stateChanged.connect(self._on_export_option_changed)
        output_layout.addRow("Overwrite", self.overwrite_checkbox)

        self.parallel_spinbox = QSpinBox()
        self.parallel_spinbox.setRange(1, 8)
        self.parallel_spinbox.setValue(1)
        self.parallel_spinbox.valueChanged.connect(self._on_export_option_changed)
        output_layout.addRow("Max parallel exports", self.parallel_spinbox)

        profile_editor = QHBoxLayout()
        self.profile_edit_combo = QComboBox()
        self.profile_edit_combo.currentIndexChanged.connect(self._on_profile_edit_selected)
        self.profile_new_button = QPushButton("New Profile")
        self.profile_new_button.clicked.connect(self._on_new_profile)
        self.profile_save_button = QPushButton("Save Profile")
        self.profile_save_button.clicked.connect(self._on_save_profile)
        profile_editor.addWidget(self.profile_edit_combo, 1)
        profile_editor.addWidget(self.profile_new_button)
        profile_editor.addWidget(self.profile_save_button)
        output_layout.addRow("Edit profile", profile_editor)

        self.profile_resolution_combo = QComboBox()
        self.profile_resolution_combo.setEditable(True)
        self.profile_resolution_combo.addItems(PROFILE_RESOLUTION_PRESETS)
        output_layout.addRow("Resolution", self.profile_resolution_combo)

        profile_flags = QHBoxLayout()
        self.profile_flowstate_checkbox = QCheckBox("FlowState")
        self.profile_denoise_checkbox = QCheckBox("Denoise")
        self.profile_direction_lock_checkbox = QCheckBox("Direction lock")
        self.profile_direction_lock_checkbox.stateChanged.connect(
            self._on_direction_lock_changed
        )
        profile_flags.addWidget(self.profile_flowstate_checkbox)
        profile_flags.addWidget(self.profile_denoise_checkbox)
        profile_flags.addWidget(self.profile_direction_lock_checkbox)
        output_layout.addRow("Profile flags", profile_flags)
        root_layout.addWidget(output_group)

        self.sequence_table = QTableWidget(0, len(POSITIONS))
        self.sequence_table.setHorizontalHeaderLabels(list(POSITIONS))
        self.sequence_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.sequence_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.sequence_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sequence_table.verticalHeader().setVisible(False)
        self.sequence_table.horizontalHeader().setStretchLastSection(True)
        self.sequence_table.setStyleSheet(
            """
            QTableWidget {
                background-color: #f9fafb;
                color: #111827;
                gridline-color: #9ca3af;
            }
            QTableWidget::item {
                color: #111827;
                padding: 4px;
            }
            QHeaderView::section {
                background-color: #1f2937;
                color: #f9fafb;
                border: 1px solid #111827;
                padding: 4px;
            }
            """
        )
        self.sequence_table.itemClicked.connect(self.on_video_cell_clicked)
        root_layout.addWidget(self.sequence_table, 1)

        bottom_row = QHBoxLayout()
        self.export_button = QPushButton("Export Selected Videos")
        self.export_button.clicked.connect(self.start_export)
        self.status_label = QLabel("")
        bottom_row.addWidget(self.export_button)
        bottom_row.addWidget(self.status_label, 1)
        root_layout.addLayout(bottom_row)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(130)
        root_layout.addWidget(self.log_text)

    def _load_config_into_widgets(self):
        self.output_dir_edit.setText(self.config.get("output_dir", ""))
        self.overwrite_checkbox.setChecked(bool(self.config.get("overwrite", False)))
        self.parallel_spinbox.setValue(int(self.config.get("max_parallel_exports", 1)))
        self._refresh_profile_combos()
        show_last_n = self.config.get("show_last_n", {})
        if not isinstance(show_last_n, dict):
            show_last_n = {}
        for pos, spinbox in self.show_last_spinboxes.items():
            spinbox.blockSignals(True)
            spinbox.setValue(_sanitize_show_last_n(show_last_n.get(pos, 10)))
            spinbox.blockSignals(False)

    def _refresh_profile_combos(self):
        names = _profile_names(self.config)
        self._updating_profiles = True
        current_edit = self.profile_edit_combo.currentText() or config_store.DEFAULT_PROFILE_NAME
        self.profile_edit_combo.blockSignals(True)
        self.profile_edit_combo.clear()
        self.profile_edit_combo.addItems(names)
        edit_index = self.profile_edit_combo.findText(current_edit)
        self.profile_edit_combo.setCurrentIndex(edit_index if edit_index >= 0 else 0)
        self.profile_edit_combo.blockSignals(False)

        profile_by_pos = self.config.get("profile_by_pos", {})
        if not isinstance(profile_by_pos, dict):
            profile_by_pos = {}
        for pos, combo in self.profile_combos.items():
            current = profile_by_pos.get(pos, config_store.DEFAULT_PROFILE_NAME)
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            index = combo.findText(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self._updating_profiles = False
        self._load_profile_editor(self.profile_edit_combo.currentText())

    def _load_profile_editor(self, name):
        profile = self.config.get("profiles", {}).get(name, config_store.DEFAULT_PROFILE)
        output_size = str(profile.get("output_size", "3840x1920"))
        index = self.profile_resolution_combo.findText(output_size)
        if index < 0:
            self.profile_resolution_combo.addItem(output_size)
            index = self.profile_resolution_combo.findText(output_size)
        self.profile_resolution_combo.setCurrentIndex(index)
        self.profile_flowstate_checkbox.setChecked(bool(profile.get("enable_flowstate", True)))
        self.profile_denoise_checkbox.setChecked(bool(profile.get("enable_denoise", True)))
        self.profile_direction_lock_checkbox.setChecked(
            bool(profile.get("enable_direction_lock", False))
        )

    def _profile_from_editor(self):
        enable_direction_lock = self.profile_direction_lock_checkbox.isChecked()
        return {
            "output_size": self.profile_resolution_combo.currentText().strip() or "3840x1920",
            "enable_flowstate": self.profile_flowstate_checkbox.isChecked()
            or enable_direction_lock,
            "enable_denoise": self.profile_denoise_checkbox.isChecked(),
            "enable_direction_lock": enable_direction_lock,
        }

    def _on_profile_edit_selected(self):
        if self._updating_profiles:
            return
        self._load_profile_editor(self.profile_edit_combo.currentText())

    def _on_direction_lock_changed(self):
        if self.profile_direction_lock_checkbox.isChecked():
            self.profile_flowstate_checkbox.setChecked(True)

    def _on_new_profile(self):
        name, accepted = QInputDialog.getText(self, "New export profile", "Profile name")
        if not accepted:
            return
        name = name.strip()
        if not name:
            return
        self.config.setdefault("profiles", {})[name] = self._profile_from_editor()
        self._save_config()
        self._refresh_profile_combos()
        index = self.profile_edit_combo.findText(name)
        if index >= 0:
            self.profile_edit_combo.setCurrentIndex(index)

    def _on_save_profile(self):
        name = self.profile_edit_combo.currentText().strip() or config_store.DEFAULT_PROFILE_NAME
        self.config.setdefault("profiles", {})[name] = self._profile_from_editor()
        if self.config["profiles"][name]["enable_direction_lock"]:
            self.config["profiles"][name]["enable_flowstate"] = True
        self._save_config()
        self._refresh_profile_combos()

    def _on_position_profile_changed(self):
        if self._updating_profiles:
            return
        self.config["profile_by_pos"] = {
            pos: combo.currentText() or config_store.DEFAULT_PROFILE_NAME
            for pos, combo in self.profile_combos.items()
        }
        self._save_config()

    def scan_media(self):
        self.log("Scanning {} ...".format(MEDIA_ROOT))
        items = []
        if media_scan is not None and hasattr(media_scan, "scan_mounts"):
            try:
                items = [
                    normalized
                    for normalized in (
                        _normalize_media_item(item)
                        for item in _flatten_scan_result(media_scan.scan_mounts(str(MEDIA_ROOT)))
                    )
                    if normalized is not None
                ]
            except Exception as exc:
                self.log("core.media_scan failed; using GUI fallback scanner: {}".format(exc))
                items = _fallback_scan_mounts(MEDIA_ROOT)
        else:
            self.log("core.media_scan unavailable; using GUI fallback scanner.")
            items = _fallback_scan_mounts(MEDIA_ROOT)

        self.items_by_mount = {}
        for item in items:
            if not item.mount_id:
                continue
            self.items_by_mount.setdefault(item.mount_id, []).append(item)

        for mount_items in self.items_by_mount.values():
            mount_items.sort(key=lambda item: item.timestamp)

        self._refresh_assignment_combos()
        self.refresh_sequences(clear_selection=True)

        total_items = sum(len(items) for items in self.items_by_mount.values())
        self.scan_summary_label.setText(
            "{} SD cards, {} videos".format(len(self.items_by_mount), total_items)
        )
        self.log("Scan complete: {} SD cards, {} videos.".format(len(self.items_by_mount), total_items))

    def _refresh_assignment_combos(self):
        self._updating_assignments = True
        saved_positions = self.config.get("positions", {})
        selected = self.current_assignments()
        mount_ids = sorted(self.items_by_mount.keys())

        for pos, combo in self.position_combos.items():
            current = selected.get(pos) or saved_positions.get(pos, "")
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Select SD card", "")
            used_elsewhere = {
                mount_id
                for other_pos, mount_id in selected.items()
                if other_pos != pos and mount_id
            }
            values = [mount_id for mount_id in mount_ids if mount_id not in used_elsewhere]
            if current and current not in values:
                values.append(current)
            for mount_id in sorted(values):
                count = len(self.items_by_mount.get(mount_id, []))
                label = "{} ({} videos)".format(mount_id, count)
                combo.addItem(label, mount_id)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        self._updating_assignments = False
        self.update_export_enabled()

    def current_assignments(self):
        assignments = {}
        for pos, combo in self.position_combos.items():
            value = combo.currentData()
            assignments[pos] = str(value) if value else ""
        return assignments

    def current_show_last_n(self):
        return {
            pos: _sanitize_show_last_n(spinbox.value())
            for pos, spinbox in self.show_last_spinboxes.items()
        }

    def _on_assignment_changed(self):
        if self._updating_assignments:
            return
        assignments = self.current_assignments()
        seen = set()
        for pos in POSITIONS:
            mount_id = assignments.get(pos, "")
            if not mount_id:
                continue
            if mount_id in seen:
                self.position_combos[pos].setCurrentIndex(0)
                assignments[pos] = ""
            else:
                seen.add(mount_id)
        self.config["positions"] = assignments
        self._save_config()
        self._refresh_assignment_combos()
        self.refresh_sequences(clear_selection=True)

    def _on_output_dir_edited(self):
        self.config["output_dir"] = self.output_dir_edit.text().strip()
        self._save_config()
        self.update_export_enabled()

    def _on_export_option_changed(self):
        self.config["overwrite"] = self.overwrite_checkbox.isChecked()
        self.config["max_parallel_exports"] = self.parallel_spinbox.value()
        self._save_config()
        self.update_export_enabled()

    def _on_show_last_changed(self):
        self.config["show_last_n"] = self.current_show_last_n()
        self._save_config()
        self.refresh_sequences(clear_selection=False)

    def _save_config(self):
        try:
            config_store.save_config(self.config)
        except OSError as exc:
            self.log("Failed to save config: {}".format(exc))

    def choose_output_dir(self):
        current = self.output_dir_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose output directory", current)
        if not chosen:
            return
        self.output_dir_edit.setText(chosen)
        self._on_output_dir_edited()

    def refresh_sequences(self, clear_selection=False):
        assignments = self.current_assignments()
        if not all(assignments.get(pos) for pos in POSITIONS):
            self.sequence_rows = []
            self.selected_cell_keys.clear()
            self.sequence_status = {}
            self._populate_sequence_table()
            self.update_export_enabled()
            return

        items_by_pos = {
            pos: list(self.items_by_mount.get(assignments[pos], [])) for pos in POSITIONS
        }
        self.sequence_rows = _build_manual_video_grid(items_by_pos, self.current_show_last_n())

        visible_keys = set()
        for row in self.sequence_rows:
            for pos, item in row.items():
                visible_keys.add(_video_cell_key(pos, item))
        if clear_selection:
            self.selected_cell_keys.clear()
        else:
            self.selected_cell_keys.intersection_update(visible_keys)
        self.sequence_status = {
            key: status
            for key, status in self.sequence_status.items()
            if key in visible_keys
        }
        self._populate_sequence_table()
        self.update_export_enabled()

    def _populate_sequence_table(self):
        self.sequence_table.setRowCount(0)
        for row_index, row in enumerate(self.sequence_rows):
            self.sequence_table.insertRow(row_index)
            for col, pos in enumerate(POSITIONS):
                item = row.get(pos)
                table_item = QTableWidgetItem(_video_cell_label(item) if item else "")
                if item:
                    cell_key = _video_cell_key(pos, item)
                    table_item.setData(Qt.UserRole, cell_key)
                    status = self.sequence_status.get(cell_key, "")
                    selected = cell_key in self.selected_cell_keys
                    self._style_video_item(table_item, status, selected)
                else:
                    table_item.setBackground(QBrush(QColor("#f3f4f6")))
                    table_item.setForeground(QBrush(QColor("#6b7280")))
                    table_item.setFlags(Qt.ItemIsEnabled)
                self.sequence_table.setItem(row_index, col, table_item)

        self.sequence_table.resizeColumnsToContents()
        self.sequence_table.resizeRowsToContents()

    def _style_video_item(self, table_item, status, selected):
        background, foreground = _video_item_colors(status, selected)
        table_item.setBackground(QBrush(QColor(background)))
        table_item.setForeground(QBrush(QColor(foreground)))

    def on_video_cell_clicked(self, table_item):
        cell_key = table_item.data(Qt.UserRole)
        if not cell_key:
            return
        if cell_key in self.selected_cell_keys:
            self.selected_cell_keys.remove(cell_key)
        else:
            self.selected_cell_keys.add(cell_key)
            self.sequence_status.pop(cell_key, None)
        self._populate_sequence_table()
        self.update_export_enabled()

    def selected_video_cells(self):
        cells = []
        for row in self.sequence_rows:
            for pos in POSITIONS:
                item = row.get(pos)
                if not item:
                    continue
                cell_key = _video_cell_key(pos, item)
                if cell_key in self.selected_cell_keys:
                    cells.append((cell_key, pos, item))
        return cells

    def update_export_enabled(self):
        assignments = self.current_assignments()
        all_assigned = all(assignments.get(pos) for pos in POSITIONS)
        output_dir = self.output_dir_edit.text().strip()
        selected_count = len(self.selected_video_cells())
        backend_ready = export_jobs is not None and hasattr(export_jobs, "run_export_queue")
        busy = self.worker is not None and self.worker.isRunning()

        enabled = all_assigned and bool(output_dir) and selected_count > 0 and backend_ready and not busy
        self.export_button.setEnabled(enabled)

        if busy:
            self.status_label.setText("Export queue running")
        elif not backend_ready:
            self.status_label.setText("Export backend unavailable")
        elif not all_assigned:
            self.status_label.setText("Bind all 5 positions to enable export")
        elif not output_dir:
            self.status_label.setText("Choose an output directory")
        elif selected_count == 0:
            self.status_label.setText("Select at least one video cell")
        else:
            self.status_label.setText("Ready: {} selected videos".format(selected_count))

    def start_export(self):
        output_dir = self.output_dir_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "Missing output directory", "Choose an output directory first.")
            return

        selected_cells = self.selected_video_cells()
        if not selected_cells:
            QMessageBox.warning(self, "No selected videos", "Select at least one video cell.")
            return

        task_records = self._build_task_records(selected_cells, output_dir)
        if not task_records:
            QMessageBox.warning(self, "No export tasks", "No export tasks were generated.")
            return

        for cell_key, _, _ in selected_cells:
            self.sequence_status[cell_key] = "pending"
        self._populate_sequence_table()

        self.worker = ExportWorker(
            task_records=task_records,
            max_parallel_exports=self.parallel_spinbox.value(),
            overwrite=self.overwrite_checkbox.isChecked(),
            parent=self,
        )
        self.worker.status_changed.connect(self.on_worker_status)
        self.worker.message.connect(self.log)
        self.worker.queue_finished.connect(self.on_worker_finished)
        self.worker.queue_failed.connect(self.on_worker_failed)
        self.worker.finished.connect(self.on_worker_thread_stopped)
        self.worker.start()
        self.log(
            "Started export queue: {} tasks, max_parallel_exports={}.".format(
                len(task_records), self.parallel_spinbox.value()
            )
        )
        self.update_export_enabled()

    def _build_task_records(self, selected_cells, output_dir):
        records = []
        for cell_key, pos, item in selected_cells:
            output_path = _build_output_path(output_dir, pos, item)
            task = self._make_export_task(pos, item, output_path)
            records.append(
                {
                    "sequence_key": cell_key,
                    "pos": pos,
                    "item": item,
                    "output_path": str(output_path),
                    "task": task,
                }
            )
        return records

    def _make_export_task(self, pos, item, output_path):
        timestamp = _item_timestamp(item)
        profile = _profile_for_pos(self.config, pos)
        task_id = "{}_{}_{}_{}".format(
            timestamp.strftime("%Y%m%d_%H%M%S") if timestamp else "unknown_time",
            pos,
            _item_mount_id(item) or "unknown_mount",
            _item_seq_id(item) or "unknown_seq",
        )

        values = {
            "task_id": task_id,
            "input_path": _item_video_path(item),
            "video_path": _item_video_path(item),
            "output_dir": self.output_dir_edit.text().strip(),
            "output_path": str(output_path),
            "pos": pos,
            "position": pos,
            "mount_id": _item_mount_id(item),
            "mount_path": _item_mount_path(item),
            "seq_id": _item_seq_id(item),
            "capture_time": timestamp,
            "timestamp": timestamp,
            "overwrite": self.overwrite_checkbox.isChecked(),
            "exporter_path": str(DEFAULT_EXPORTER_PATH),
            "model_root": _default_model_root(),
            "output_size": profile["output_size"],
            "enable_flowstate": profile["enable_flowstate"],
            "enable_denoise": profile["enable_denoise"],
            "enable_direction_lock": profile["enable_direction_lock"],
        }

        if export_jobs is not None and hasattr(export_jobs, "ExportTask"):
            task_cls = export_jobs.ExportTask
            try:
                signature = inspect.signature(task_cls)
                parameters = signature.parameters
                if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
                    return task_cls(**values)
                kwargs = {
                    name: values[name]
                    for name in parameters
                    if name != "self" and name in values
                }
                return task_cls(**kwargs)
            except TypeError:
                pass

        return values

    def on_worker_status(self, sequence_key, status):
        if status not in ("pending", "running", "done", "failed", "skipped"):
            return
        current = self.sequence_status.get(sequence_key)
        if current == "failed" and status != "running":
            return
        self.sequence_status[sequence_key] = status
        self._populate_sequence_table()
        self.update_export_enabled()

    def on_worker_finished(self, results):
        aggregate = {}
        for record in self.worker.task_records:
            aggregate.setdefault(record["sequence_key"], [])

        if results is None:
            for sequence_key in aggregate:
                aggregate[sequence_key].append("done")
        else:
            if not isinstance(results, (list, tuple)):
                results = [results]
            output_to_sequence = {
                str(record["output_path"]): record["sequence_key"]
                for record in self.worker.task_records
            }
            matched = set()
            for result in results:
                output_path = _extract_result_value(result, "output_path")
                if output_path is None:
                    output_path = _extract_result_value(result, "output")
                sequence_key = output_to_sequence.get(str(output_path))
                if not sequence_key:
                    continue
                matched.add(str(output_path))
                aggregate.setdefault(sequence_key, []).append(_extract_result_status(result))
            for record in self.worker.task_records:
                if str(record["output_path"]) not in matched:
                    aggregate.setdefault(record["sequence_key"], []).append("done")

        for sequence_key, statuses in aggregate.items():
            self.sequence_status[sequence_key] = self._aggregate_statuses(statuses)

        self._populate_sequence_table()
        self.log("Export queue finished.")
        self.update_export_enabled()

    def on_worker_failed(self, error_text):
        if self.worker is not None:
            for record in self.worker.task_records:
                self.sequence_status[record["sequence_key"]] = "failed"
        self._populate_sequence_table()
        self.log("Export queue failed:\n{}".format(error_text))
        QMessageBox.critical(self, "Export failed", error_text)
        self.update_export_enabled()

    def on_worker_thread_stopped(self):
        self.worker = None
        self.update_export_enabled()

    def _aggregate_statuses(self, statuses):
        if not statuses:
            return ""
        statuses = [status for status in statuses if status]
        if any(status == "failed" for status in statuses):
            return "failed"
        if all(status == "skipped" for status in statuses):
            return "skipped"
        if all(status in ("done", "skipped") for status in statuses):
            return "done"
        if any(status == "running" for status in statuses):
            return "running"
        return statuses[-1]

    def log(self, message):
        self.log_text.append(str(message))


def main():
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
