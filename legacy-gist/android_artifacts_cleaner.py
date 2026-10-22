import ctypes
import json
import os
import shutil
import string
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4

# Scan limits for background size calculation.
SIZE_SCAN_MAX_SECONDS = 1.2
SIZE_SCAN_MAX_FILES = 6000
AUTO_SELECT_SMALL_BYTES = 16 * 1024

DIR_NAME_MARKERS = {
    "android",
    "lost.dir",
    ".android_secure",
    ".thumbnails",
}

FILE_NAME_MARKERS = {
    ".nomedia",
}

PATH_SIGNATURES = {
    "android/data",
    "android/obb",
    "dcim/.thumbnails",
}

ANDROID_EMPTY_DIR_CANDIDATES = {
    "android/data",
    "android/obb",
    ".thumbnails",
    "dcim/.thumbnails",
    "lost.dir",
}


@dataclass
class Candidate:
    path: Path
    is_dir: bool
    size_bytes: int
    item_count: int
    reason: str
    size_limited: bool = False


def format_size(size: int) -> str:
    if size < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def list_local_target_drives() -> list[str]:
    drives: list[str] = []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    except Exception:
        return drives

    for index, letter in enumerate(string.ascii_uppercase):
        if not (mask & (1 << index)):
            continue
        if letter.upper() == "C":
            continue

        root = f"{letter}:\\"
        drive_type = get_drive_type(root)
        if drive_type == DRIVE_REMOTE:
            continue
        if drive_type not in (DRIVE_REMOVABLE, DRIVE_FIXED):
            continue
        if not os.path.isdir(root):
            continue
        drives.append(root)

    return sorted(drives)


def get_volume_label(root: str) -> str:
    kernel32 = ctypes.windll.kernel32
    volume_name = ctypes.create_unicode_buffer(261)
    fs_name = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_uint32()
    max_comp_len = ctypes.c_uint32()
    flags = ctypes.c_uint32()

    ok = kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root),
        volume_name,
        len(volume_name),
        ctypes.byref(serial),
        ctypes.byref(max_comp_len),
        ctypes.byref(flags),
        fs_name,
        len(fs_name),
    )
    if not ok:
        return "Без имени"

    label = volume_name.value.strip()
    return label if label else "Без имени"


def get_disk_topology() -> dict[str, tuple[int, str]]:
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "if (-not (Get-Command Get-Partition -ErrorAction SilentlyContinue)) { '[]'; exit }; "
        "$parts=Get-Partition | Where-Object { $_.DriveLetter } | Select-Object DriveLetter,DiskNumber; "
        "$disks=Get-Disk | Select-Object Number,FriendlyName,Model; "
        "$result=foreach($p in $parts){ "
        "$d=$disks | Where-Object { $_.Number -eq $p.DiskNumber } | Select-Object -First 1; "
        "[pscustomobject]@{ "
        "Drive=($p.DriveLetter + ':\\'); "
        "DiskNumber=[int]$p.DiskNumber; "
        "DiskName=if($d){($d.FriendlyName + ' ' + $d.Model).Trim()}else{''} "
        "} }; "
        "$result | ConvertTo-Json -Compress"
    )
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=creationflags,
        ).strip()
    except Exception:
        return {}

    if not output:
        return {}

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return {}

    if isinstance(parsed, dict):
        parsed = [parsed]

    mapping: dict[str, tuple[int, str]] = {}
    for item in parsed:
        drive = str(item.get("Drive", "")).upper()
        if not drive.endswith("\\"):
            drive = f"{drive}\\"
        disk_number = item.get("DiskNumber")
        if len(drive) < 3 or disk_number is None:
            continue
        disk_name = str(item.get("DiskName", "")).strip()
        mapping[drive] = (int(disk_number), disk_name)

    return mapping


def dir_stats_limited(path: Path) -> tuple[int, int, bool]:
    total = 0
    count = 0
    files_seen = 0
    deadline = time.monotonic() + SIZE_SCAN_MAX_SECONDS

    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        if time.monotonic() >= deadline:
            return total, count, True

        count += len(dirs) + len(files)
        for name in files:
            if time.monotonic() >= deadline or files_seen >= SIZE_SCAN_MAX_FILES:
                return total, count, True
            file_path = Path(root) / name
            try:
                file_size = file_path.stat().st_size
                if file_size > 0:
                    total += file_size
            except OSError:
                pass
            files_seen += 1

    return total, count, False


def normalize_rel(path: Path) -> str:
    return path.as_posix().strip("/").lower()


def scan_android_artifacts(root: Path) -> list[Candidate]:
    root = root.resolve()
    results: list[Candidate] = []
    seen: set[str] = set()

    # Normal mode: all first-level folders + Android marker files in root.
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                abs_path = Path(entry.path)
                key = str(abs_path).lower()
                if key in seen:
                    continue

                name_norm = entry.name.lower()
                is_dir = entry.is_dir(follow_symlinks=False)
                reason = "Папка 1-го уровня" if is_dir else ""
                if not is_dir and name_norm in FILE_NAME_MARKERS:
                    reason = f"Android-файл: {entry.name}"
                if not reason:
                    continue

                size_bytes = -1 if is_dir else 0
                item_count = -1 if is_dir else 0
                if not is_dir:
                    try:
                        st = abs_path.stat().st_size
                        size_bytes = st if st >= 0 else 0
                    except OSError:
                        size_bytes = 0

                results.append(
                    Candidate(
                        path=abs_path,
                        is_dir=is_dir,
                        size_bytes=size_bytes,
                        item_count=item_count,
                        reason=reason,
                        size_limited=False,
                    )
                )
                seen.add(key)
    except OSError:
        return results

    # Explicit Android path signatures (avoid duplicates).
    for signature in PATH_SIGNATURES:
        sig_path = root / Path(*signature.split("/"))
        if not sig_path.exists():
            continue
        key = str(sig_path).lower()
        if key in seen:
            continue

        is_dir = sig_path.is_dir()
        size_bytes = -1 if is_dir else 0
        item_count = -1 if is_dir else 0
        if not is_dir:
            try:
                st = sig_path.stat().st_size
                size_bytes = st if st >= 0 else 0
            except OSError:
                size_bytes = 0

        results.append(
            Candidate(
                path=sig_path,
                is_dir=is_dir,
                size_bytes=size_bytes,
                item_count=item_count,
                reason=f"Сигнатура пути: {normalize_rel(Path(signature))}",
                size_limited=False,
            )
        )
        seen.add(key)

    results.sort(key=lambda c: str(c.path).lower())
    return results


def scan_empty_android_dirs(root: Path) -> list[Candidate]:
    root = root.resolve()
    results: list[Candidate] = []
    seen: set[str] = set()

    # Root-level markers that are directories.
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                name_norm = entry.name.lower()
                if name_norm not in DIR_NAME_MARKERS:
                    continue
                p = Path(entry.path)
                key = str(p).lower()
                if key in seen:
                    continue
                results.append(
                    Candidate(
                        path=p,
                        is_dir=True,
                        size_bytes=0,
                        item_count=-1,
                        reason=f"Имя папки: {entry.name}",
                        size_limited=False,
                    )
                )
                seen.add(key)
    except OSError:
        return results

    # Known Android directory signatures.
    for signature in ANDROID_EMPTY_DIR_CANDIDATES:
        p = root / Path(*signature.split("/"))
        if not p.exists() or not p.is_dir():
            continue
        key = str(p).lower()
        if key in seen:
            continue
        results.append(
            Candidate(
                path=p,
                is_dir=True,
                size_bytes=0,
                item_count=-1,
                reason=f"Сигнатура пути: {signature}",
                size_limited=False,
            )
        )
        seen.add(key)

    results.sort(key=lambda c: str(c.path).lower())
    return results


class SizeScanWorker(QThread):
    # Use object for size/count to avoid 32-bit overflow in Qt int.
    progress = Signal(int, object, object, object)

    def __init__(self, candidates: list[Candidate]) -> None:
        super().__init__()
        self._candidates = candidates

    def run(self) -> None:
        for index, candidate in enumerate(self._candidates):
            if self.isInterruptionRequested():
                return

            if candidate.is_dir:
                size, count, limited = dir_stats_limited(candidate.path)
            else:
                try:
                    st = candidate.path.stat().st_size
                    size = st if st >= 0 else 0
                except OSError:
                    size = 0
                count = 0
                limited = False

            self.progress.emit(index, size, count, limited)


class CleanerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Очистка Android-артефактов")
        self.resize(1100, 660)

        self.candidates: list[Candidate] = []
        self.drive_buttons: dict[str, QCheckBox] = {}
        self.size_worker: SizeScanWorker | None = None
        self.last_scanned_roots: list[Path] = []
        self.empty_only_mode = False

        self._build_ui()
        self._refresh_drive_buttons(auto_check_all=True, auto_scan_all=True)

    def _build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)

        drives_row = QHBoxLayout()
        drives_row.addWidget(QLabel("Найденные диски:"))
        self.drives_buttons_host = QWidget()
        self.drives_buttons_layout = QHBoxLayout(self.drives_buttons_host)
        self.drives_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.drives_buttons_layout.setSpacing(8)
        drives_row.addWidget(self.drives_buttons_host, 1)
        layout.addLayout(drives_row)

        self.disk_groups_label = QLabel("Группировка по физическим дискам")
        self.disk_groups_label.setWordWrap(True)
        self.disk_groups_label.setMinimumHeight(90)
        self.disk_groups_label.setStyleSheet(
            "QLabel {"
            " background: #1f2430;"
            " color: #e8edf7;"
            " border: 1px solid #4d5a70;"
            " border-radius: 6px;"
            " padding: 10px;"
            "}"
        )
        layout.addWidget(self.disk_groups_label)

        disk_actions_row = QHBoxLayout()
        btn_select_drives = QPushButton("Выделить все диски")
        btn_select_drives.clicked.connect(lambda: self._set_drive_checks(True))
        btn_clear_drives = QPushButton("Снять диски")
        btn_clear_drives.clicked.connect(lambda: self._set_drive_checks(False))
        btn_scan_selected = QPushButton("Сканировать выбранные")
        btn_scan_selected.clicked.connect(self._scan_selected_drives)
        btn_scan_all = QPushButton("Сканировать все")
        btn_scan_all.clicked.connect(self._scan_all_drives)
        btn_refresh = QPushButton("Обновить диски")
        btn_refresh.clicked.connect(
            lambda: self._refresh_drive_buttons(auto_check_all=False, auto_scan_all=False)
        )

        disk_actions_row.addWidget(btn_select_drives)
        disk_actions_row.addWidget(btn_clear_drives)
        disk_actions_row.addWidget(btn_scan_selected)
        disk_actions_row.addWidget(btn_scan_all)
        disk_actions_row.addWidget(btn_refresh)
        disk_actions_row.addStretch(1)
        layout.addLayout(disk_actions_row)

        self.empty_only_checkbox = QCheckBox("Только пустые Android-папки (быстрый режим)")
        self.empty_only_checkbox.toggled.connect(self._on_empty_only_mode_toggled)
        layout.addWidget(self.empty_only_checkbox)

        layout.addSpacing(8)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)
        layout.addSpacing(6)

        layout.addWidget(QLabel("Найденные Android-папки и файлы:"))

        actions_row = QHBoxLayout()
        btn_select_all = QPushButton("Выделить все")
        btn_select_all.clicked.connect(lambda: self._set_all_checks(Qt.Checked))
        btn_unselect_all = QPushButton("Снять выделение")
        btn_unselect_all.clicked.connect(lambda: self._set_all_checks(Qt.Unchecked))
        btn_delete = QPushButton("Удалить выбранное")
        btn_delete.clicked.connect(self._delete_selected)
        actions_row.addWidget(btn_select_all)
        actions_row.addWidget(btn_unselect_all)
        actions_row.addStretch(1)
        actions_row.addWidget(btn_delete)
        layout.addLayout(actions_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "Путь", "Тип", "Размер", "Пустая", "Почему найдено"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(1, 500)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 90)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("Автоскан выполнится по найденным дискам.")
        layout.addWidget(self.status_label)
        self.setCentralWidget(container)

    def _clear_drive_buttons(self) -> None:
        while self.drives_buttons_layout.count():
            item = self.drives_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.drive_buttons.clear()

    def _set_drive_checks(self, checked: bool) -> None:
        for checkbox in self.drive_buttons.values():
            checkbox.setChecked(checked)

    def _selected_drive_roots(self) -> list[str]:
        return [drive for drive, checkbox in self.drive_buttons.items() if checkbox.isChecked()]

    def _refresh_drive_buttons(self, auto_check_all: bool, auto_scan_all: bool) -> None:
        self._clear_drive_buttons()
        drives = list_local_target_drives()
        topology = get_disk_topology()

        if not drives:
            none_label = QLabel("Локальные диски не найдены (кроме C:).")
            self.drives_buttons_layout.addWidget(none_label)
            self.drives_buttons_layout.addStretch(1)
            self.disk_groups_label.setText("Группировка по физическим дискам\n\nНет доступных дисков.")
            return

        for drive in drives:
            label = get_volume_label(drive)
            disk_info = topology.get(drive.upper())
            disk_suffix = f" | Диск {disk_info[0]}" if disk_info else ""
            checkbox = QCheckBox(f"{drive} [{label}]{disk_suffix}")
            checkbox.setChecked(auto_check_all)
            self.drives_buttons_layout.addWidget(checkbox)
            self.drive_buttons[drive] = checkbox

        self.drives_buttons_layout.addStretch(1)
        self._update_disk_groups_label(drives, topology)
        if auto_scan_all:
            self._scan_all_drives()

    def _update_disk_groups_label(self, drives: list[str], topology: dict[str, tuple[int, str]]) -> None:
        groups: dict[int, list[str]] = {}
        names: dict[int, str] = {}
        unknown: list[str] = []

        for drive in drives:
            info = topology.get(drive.upper())
            if not info:
                unknown.append(drive)
                continue
            disk_num, disk_name = info
            groups.setdefault(disk_num, []).append(drive)
            if disk_name:
                names[disk_num] = disk_name

        lines: list[str] = []
        for disk_num in sorted(groups.keys()):
            letters = ", ".join(sorted(groups[disk_num]))
            n = names.get(disk_num, "")
            suffix = f" ({n})" if n else ""
            lines.append(f"=== Диск {disk_num}{suffix}: {letters} ===")

        if unknown:
            lines.append(f"=== Не определено: {', '.join(sorted(unknown))} ===")

        if not lines:
            self.disk_groups_label.setText("Группировка по физическим дискам\n\nНет данных.")
            return

        self.disk_groups_label.setText("Группировка по физическим дискам\n\n" + "\n\n".join(lines))

    def _scan_selected_drives(self) -> None:
        roots = [Path(d) for d in self._selected_drive_roots()]
        if not roots:
            QMessageBox.information(self, "Диски не выбраны", "Сначала выбери один или несколько дисков.")
            return
        self._scan_roots(roots)

    def _scan_all_drives(self) -> None:
        roots = [Path(d) for d in self.drive_buttons.keys()]
        if not roots:
            QMessageBox.information(self, "Нет дисков", "Нет дисков для сканирования.")
            return
        self._scan_roots(roots)

    def _scan_roots(self, roots: list[Path]) -> None:
        self._stop_size_worker()
        valid_roots = [r for r in roots if r.exists() and r.is_dir()]
        if not valid_roots:
            QMessageBox.warning(self, "Путь недоступен", "Ни один выбранный диск сейчас недоступен.")
            return

        self.status_label.setText("Сканирование...")
        QApplication.processEvents()

        merged: list[Candidate] = []
        if self.empty_only_mode:
            for root in valid_roots:
                merged.extend(scan_empty_android_dirs(root))
        else:
            for root in valid_roots:
                merged.extend(scan_android_artifacts(root))
        merged.sort(key=lambda c: str(c.path).lower())

        self.candidates = merged
        self.last_scanned_roots = valid_roots
        self._fill_table(valid_roots)
        if self.empty_only_mode:
            self._start_empty_check_scan()
        else:
            self._start_size_scan()

    def _on_empty_only_mode_toggled(self, checked: bool) -> None:
        self.empty_only_mode = checked
        self.status_label.setText(
            "Режим: только пустые Android-папки." if checked else "Режим: обычный скан Android-артефактов."
        )

    def _start_empty_check_scan(self) -> None:
        # Reuse worker; size values are already 0 for this mode.
        # We still need item counts to determine empty/non-empty quickly.
        if not self.candidates:
            return
        self.size_worker = SizeScanWorker(self.candidates.copy())
        self.size_worker.progress.connect(self._on_empty_mode_progress)
        self.size_worker.finished.connect(self._on_empty_mode_finished)
        self.size_worker.start()

    def _on_empty_mode_progress(self, row: int, _size: object, item_count: object, _limited: object) -> None:
        if not self.empty_only_mode:
            return
        if row >= len(self.candidates):
            return
        c = self.candidates[row]
        if not c.is_dir:
            return
        cnt = int(item_count) if isinstance(item_count, int) else 0
        if cnt < 0:
            cnt = 0
        c.item_count = cnt
        c.size_bytes = 0
        c.size_limited = False

        empty_item = self.table.item(row, 4)
        if empty_item:
            empty_item.setText("Да" if cnt == 0 else "Нет")
        self._update_status_summary(self.last_scanned_roots, calculating=True)

    def _on_empty_mode_finished(self) -> None:
        if not self.empty_only_mode:
            return
        # Keep only empty directories in fast mode.
        filtered = [c for c in self.candidates if c.is_dir and c.item_count == 0]
        self.candidates = filtered
        self._fill_table(self.last_scanned_roots)
        self._update_status_summary(self.last_scanned_roots, calculating=False)

    def _stop_size_worker(self) -> None:
        if self.size_worker and self.size_worker.isRunning():
            self.size_worker.requestInterruption()
            self.size_worker.wait(500)
        self.size_worker = None

    def _start_size_scan(self) -> None:
        if not self.candidates:
            return
        self.size_worker = SizeScanWorker(self.candidates.copy())
        self.size_worker.progress.connect(self._on_size_progress)
        self.size_worker.finished.connect(self._on_size_finished)
        self.size_worker.start()

    def _on_size_progress(self, row: int, size: object, item_count: object, limited: object) -> None:
        if row >= len(self.candidates):
            return

        s = int(size) if isinstance(size, int) else 0
        c = int(item_count) if isinstance(item_count, int) else 0
        if s < 0:
            s = 0
        if c < 0:
            c = 0

        candidate = self.candidates[row]
        candidate.size_bytes = s
        candidate.item_count = c
        candidate.size_limited = bool(limited)

        size_item = self.table.item(row, 3)
        empty_item = self.table.item(row, 4)
        if size_item:
            txt = format_size(s)
            if candidate.size_limited:
                txt += "+"
            size_item.setText(txt)
        if empty_item:
            if candidate.is_dir:
                empty_item.setText("Да" if c == 0 else "Нет")
            else:
                empty_item.setText("Нет")

        # Auto-select empty folders or small folders.
        check_item = self.table.item(row, 0)
        if check_item and candidate.is_dir:
            if c == 0 or s <= AUTO_SELECT_SMALL_BYTES:
                check_item.setCheckState(Qt.Checked)
            else:
                check_item.setCheckState(Qt.Unchecked)

        self._update_status_summary(self.last_scanned_roots, calculating=True)

    def _on_size_finished(self) -> None:
        self._update_status_summary(self.last_scanned_roots, calculating=False)

    def _fill_table(self, scanned_roots: list[Path] | None = None) -> None:
        self.table.setRowCount(0)

        for row, candidate in enumerate(self.candidates):
            self.table.insertRow(row)

            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            # Start unchecked, then background pass sets smart defaults.
            check_item.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, check_item)

            self.table.setItem(row, 1, QTableWidgetItem(str(candidate.path)))
            self.table.setItem(row, 2, QTableWidgetItem("Папка" if candidate.is_dir else "Файл"))

            if candidate.size_bytes < 0:
                size_text = "Считается..."
            else:
                size_text = format_size(candidate.size_bytes) + ("+" if candidate.size_limited else "")
            self.table.setItem(row, 3, QTableWidgetItem(size_text))

            if candidate.is_dir and candidate.item_count < 0:
                empty_text = "..."
            else:
                empty_text = "Да" if candidate.is_dir and candidate.item_count == 0 else "Нет"
            self.table.setItem(row, 4, QTableWidgetItem(empty_text))

            self.table.setItem(row, 5, QTableWidgetItem(candidate.reason))

        self._update_status_summary(scanned_roots or [], calculating=True)

    def _update_status_summary(self, scanned_roots: list[Path], calculating: bool) -> None:
        total_size = 0
        empty_count = 0
        pending = 0
        limited_count = 0

        for candidate in self.candidates:
            if candidate.size_bytes >= 0:
                total_size += candidate.size_bytes
            else:
                pending += 1

            if candidate.is_dir and candidate.item_count >= 0 and candidate.item_count == 0:
                empty_count += 1
            if candidate.size_limited:
                limited_count += 1

        roots_info = ""
        if scanned_roots:
            roots_info = " | Корни: " + ", ".join(str(r) for r in scanned_roots)

        progress_info = f" | Уточняется размеров: {pending}" if calculating and pending > 0 else ""
        limited_info = f" | Ограничено по времени: {limited_count}" if limited_count else ""

        self.status_label.setText(
            f"Найдено: {len(self.candidates)} | Пустых папок: {empty_count} | "
            f"Общий размер: {format_size(total_size)}{progress_info}{limited_info}{roots_info}"
        )

    def _set_all_checks(self, state: Qt.CheckState) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)

    def _selected_candidates(self) -> list[Candidate]:
        selected: list[Candidate] = []
        for row, candidate in enumerate(self.candidates):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                selected.append(candidate)
        return selected

    def _delete_selected(self) -> None:
        self._stop_size_worker()
        selected = self._selected_candidates()
        if not selected:
            QMessageBox.information(self, "Нечего удалять", "Нет отмеченных элементов.")
            return

        total = sum(max(c.size_bytes, 0) for c in selected)
        answer = QMessageBox.question(
            self,
            "Подтвердить удаление",
            f"Удалить {len(selected)} элементов?\nБудет удалено: {format_size(total)}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        deleted = 0
        failed: list[str] = []
        for item in sorted(selected, key=lambda c: len(str(c.path)), reverse=True):
            try:
                if item.is_dir:
                    shutil.rmtree(item.path)
                else:
                    item.path.unlink(missing_ok=True)
                deleted += 1
            except Exception as exc:
                failed.append(f"{item.path} ({exc})")

        if failed:
            QMessageBox.warning(
                self,
                "Удалено с ошибками",
                f"Удалено: {deleted}\nОшибок: {len(failed)}\n\n" + "\n".join(failed[:10]),
            )
        else:
            QMessageBox.information(self, "Готово", f"Удалено элементов: {deleted}")

        selected_roots = [Path(d) for d in self._selected_drive_roots()]
        if selected_roots:
            self._scan_roots(selected_roots)
        else:
            self._scan_all_drives()


def main() -> int:
    app = QApplication(sys.argv)
    window = CleanerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
