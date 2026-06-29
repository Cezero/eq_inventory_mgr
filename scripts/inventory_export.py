#!/usr/bin/env python3
"""Export EverQuest inventory files to CSV and/or Google Sheets.

Config-first usage: copy config.example.yaml to config.yaml, then run with no args.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

LUCY_ITEM_URL = "https://lucy.allakhazam.com/item.html?id={item_id}"

EQUIPMENT_SLOT_NAMES = frozenset(
    {
        "Charm",
        "Ear",
        "Head",
        "Face",
        "Neck",
        "Shoulders",
        "Arms",
        "Back",
        "Wrist",
        "Range",
        "Hands",
        "Primary",
        "Secondary",
        "Fingers",
        "Chest",
        "Legs",
        "Feet",
        "Waist",
        "Power Source",
        "Ammo",
    }
)

DUPLICATE_SLOT_NAMES: dict[str, tuple[str, str]] = {
    "Ear": ("Left Ear", "Right Ear"),
    "Wrist": ("Left Wrist", "Right Wrist"),
    "Fingers": ("Left Fingers", "Right Fingers"),
}

EQUIPMENT_COLUMNS = [
    "Head",
    "Face",
    "Left Ear",
    "Right Ear",
    "Neck",
    "Shoulders",
    "Arms",
    "Back",
    "Left Wrist",
    "Right Wrist",
    "Range",
    "Hands",
    "Primary",
    "Secondary",
    "Left Fingers",
    "Right Fingers",
    "Chest",
    "Legs",
    "Feet",
    "Waist",
    "Ammo",
    "Charm",
    "Power Source",
]

COLUMNS = ["Character", *EQUIPMENT_COLUMNS]

INVENTORY_FILENAME_RE = re.compile(r"^(.+)_(.+)-[Ii]nventory\.txt$", re.IGNORECASE)

CONFIG_NAMES = ("config.yaml", "config.yml", "config.xml")
DEFAULT_CREDENTIALS_PATH = "credentials/credentials.json"


@dataclass
class GoogleSheetsConfig:
    spreadsheet_id: str
    worksheet: str = "Inventory"
    credentials: str = ""


@dataclass
class Config:
    eq_home: str = ""
    server: str = ""
    output_csv: str | None = None
    google_sheets: GoogleSheetsConfig | None = None
    config_path: Path | None = field(default=None, repr=False)


class ConfigError(Exception):
    pass


def is_top_level(location: str) -> bool:
    return "-Slot" not in location


def lucy_hyperlink(item_id: str, name: str) -> str:
    escaped_name = name.replace('"', '""')
    return (
        f'=HYPERLINK("{LUCY_ITEM_URL.format(item_id=item_id)}","{escaped_name}")'
    )


def cell_value(name: str, item_id: str) -> str:
    if name == "Empty" or not item_id or item_id == "0":
        return ""
    return lucy_hyperlink(item_id, name)


def parse_inventory_file(path: Path) -> dict[str, str]:
    """Parse one inventory TSV; return equipment column -> cell value."""
    result = {col: "" for col in EQUIPMENT_COLUMNS}
    occurrence: dict[str, int] = {}

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if not row:
                continue
            location = row[0].strip()
            if location == "KeyRing":
                break
            if not is_top_level(location):
                continue
            if location not in EQUIPMENT_SLOT_NAMES:
                continue

            name = row[1].strip() if len(row) > 1 else ""
            item_id = row[2].strip() if len(row) > 2 else "0"

            if location in DUPLICATE_SLOT_NAMES:
                idx = occurrence.get(location, 0)
                if idx >= len(DUPLICATE_SLOT_NAMES[location]):
                    continue
                column = DUPLICATE_SLOT_NAMES[location][idx]
                occurrence[location] = idx + 1
            else:
                column = location

            result[column] = cell_value(name, item_id)

    return result


def character_from_filename(filename: str, server: str) -> str | None:
    match = INVENTORY_FILENAME_RE.match(filename)
    if not match:
        return None
    if match.group(2).lower() != server.lower():
        return None
    return match.group(1)


def discover_inventory_files(
    eq_home: Path, server: str, *, recurse: bool = True
) -> list[Path]:
    if not eq_home.is_dir():
        raise FileNotFoundError(f"eq_home is not a directory: {eq_home}")

    candidates = eq_home.rglob("*") if recurse else eq_home.iterdir()
    files: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        if character_from_filename(path.name, server) is not None:
            files.append(path)

    return sorted(files, key=lambda p: p.name.lower())


def build_character_row(character: str, slots: dict[str, str]) -> list[str]:
    return [character] + [slots.get(col, "") for col in EQUIPMENT_COLUMNS]


def write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows)


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _repo_root() -> Path:
    return _script_dir().parent


def resolve_credentials_path(
    credentials: str, config_path: Path | None = None
) -> Path:
    """Resolve a config credentials path/filename to an existing file."""
    path = Path(credentials)
    if path.is_absolute() and path.is_file():
        return path.resolve()

    search_roots: list[Path] = []
    if config_path is not None:
        search_roots.append(config_path.parent)
    search_roots.append(Path.cwd())
    search_roots.append(_repo_root())

    seen: set[Path] = set()
    for root in search_roots:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        candidate = (root / path).resolve()
        if candidate.is_file():
            return candidate

    return path


def find_config_file(explicit: Path | None) -> Path | None:
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"Config file not found: {explicit}")
        return explicit

    for name in CONFIG_NAMES:
        candidate = Path.cwd() / name
        if candidate.is_file():
            return candidate

    for name in CONFIG_NAMES:
        candidate = _script_dir() / name
        if candidate.is_file():
            return candidate

    return None


def _parse_google_sheets(data: dict[str, Any] | None) -> GoogleSheetsConfig | None:
    if not data:
        return None
    spreadsheet_id = data.get("spreadsheet_id", "").strip()
    if not spreadsheet_id:
        return None
    return GoogleSheetsConfig(
        spreadsheet_id=spreadsheet_id,
        worksheet=str(data.get("worksheet", "Inventory")).strip() or "Inventory",
        credentials=str(data.get("credentials", "")).strip(),
    )


def load_config_file(path: Path) -> Config:
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        if yaml is None:
            raise ConfigError("PyYAML is required for YAML config files (pip install PyYAML)")
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        if not isinstance(raw, dict):
            raise ConfigError(f"Config root must be a mapping: {path}")
    elif suffix == ".xml":
        tree = ET.parse(path)
        root = tree.getroot()
        raw = _xml_to_dict(root)
    else:
        raise ConfigError(f"Unsupported config format: {path}")

    return _dict_to_config(raw, path)


def _xml_to_dict(root: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in root:
        tag = child.tag
        if tag == "google_sheets":
            result[tag] = {sub.tag: (sub.text or "").strip() for sub in child}
        else:
            result[tag] = (child.text or "").strip()
    return result


def _dict_to_config(raw: dict[str, Any], path: Path) -> Config:
    eq_home = str(raw.get("eq_home", "")).strip()
    server = str(raw.get("server", "")).strip()
    output_csv = raw.get("output_csv")
    output_csv_str = str(output_csv).strip() if output_csv else None

    gs_raw = raw.get("google_sheets")
    google_sheets = None
    if isinstance(gs_raw, dict):
        google_sheets = _parse_google_sheets(gs_raw)

    return Config(
        eq_home=eq_home,
        server=server,
        output_csv=output_csv_str or None,
        google_sheets=google_sheets,
        config_path=path,
    )


def merge_cli_overrides(config: Config, args: argparse.Namespace) -> Config:
    if args.eq_home:
        config.eq_home = args.eq_home
    if args.server:
        config.server = args.server
    if args.output:
        config.output_csv = args.output
    if args.sheets:
        if config.google_sheets is None:
            config.google_sheets = GoogleSheetsConfig(spreadsheet_id=args.sheets)
        else:
            config.google_sheets.spreadsheet_id = args.sheets
    if args.worksheet:
        if config.google_sheets is None:
            config.google_sheets = GoogleSheetsConfig(
                spreadsheet_id="", worksheet=args.worksheet
            )
        else:
            config.google_sheets.worksheet = args.worksheet
    if args.credentials:
        if config.google_sheets is None:
            config.google_sheets = GoogleSheetsConfig(
                spreadsheet_id="", credentials=args.credentials
            )
        else:
            config.google_sheets.credentials = args.credentials
    return config


def validate_config(config: Config) -> None:
    errors: list[str] = []
    if not config.eq_home:
        errors.append("eq_home is required (config or --eq-home)")
    if not config.server:
        errors.append("server is required (config or --server)")
    if not config.output_csv and config.google_sheets is None:
        errors.append("at least one of output_csv or google_sheets must be configured")
    if config.google_sheets is not None:
        if not config.google_sheets.spreadsheet_id:
            errors.append("google_sheets.spreadsheet_id is required")
        creds_ref = config.google_sheets.credentials or DEFAULT_CREDENTIALS_PATH
        creds_path = resolve_credentials_path(creds_ref, config.config_path)
        if not creds_path.is_file():
            errors.append(f"google_sheets.credentials file not found: {creds_ref}")
        else:
            config.google_sheets.credentials = str(creds_path)
    if errors:
        raise ConfigError("\n".join(errors))


def load_config(args: argparse.Namespace) -> Config:
    explicit = Path(args.config) if args.config else None
    config_path = find_config_file(explicit)

    if config_path is None:
        config = Config()
    else:
        config = load_config_file(config_path)

    config = merge_cli_overrides(config, args)
    validate_config(config)
    return config


def build_row_map(
    eq_home: Path, server: str, *, recurse: bool
) -> dict[str, list[str]]:
    files = discover_inventory_files(eq_home, server, recurse=recurse)
    if not files:
        pattern = f"*_{server}-Inventory.txt"
        scope = "recursively" if recurse else "in the top level of"
        raise FileNotFoundError(
            f"No inventory files matching {pattern!r} found {scope} {eq_home}"
        )

    rows: dict[str, list[str]] = {}
    for path in files:
        character = character_from_filename(path.name, server)
        if character is None:
            continue
        slots = parse_inventory_file(path)
        rows[character] = build_character_row(character, slots)
    return rows


def format_header_bold(worksheet: Any) -> None:
    from gspread.utils import rowcol_to_a1

    end_cell = rowcol_to_a1(1, len(COLUMNS))
    worksheet.format(f"A1:{end_cell}", {"textFormat": {"bold": True}})


def upsert_google_sheets(
    config: GoogleSheetsConfig, rows: dict[str, list[str]]
) -> tuple[int, int]:
    """Update or append character rows. Returns (updated_count, appended_count)."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise ConfigError(
            "gspread and google-auth are required for Google Sheets export "
            "(pip install gspread google-auth)"
        ) from exc

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file(
        config.credentials, scopes=scopes
    )
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(config.spreadsheet_id)

    try:
        worksheet = spreadsheet.worksheet(config.worksheet)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=config.worksheet, rows=1000, cols=30)

    updated = 0
    appended = 0

    existing_header = worksheet.row_values(1)
    if existing_header != COLUMNS:
        worksheet.update(
            values=[COLUMNS], range_name="A1", value_input_option="USER_ENTERED"
        )
    format_header_bold(worksheet)

    col_a = worksheet.col_values(1)
    row_by_character: dict[str, int] = {}
    duplicate_warnings: set[str] = set()
    for row_idx, name in enumerate(col_a[1:], start=2):
        if not name:
            continue
        if name in row_by_character:
            duplicate_warnings.add(name)
            continue
        row_by_character[name] = row_idx

    for name in sorted(duplicate_warnings):
        print(f"Warning: duplicate character {name!r} in sheet; updating first match only")

    for character in sorted(rows.keys()):
        row_data = rows[character]
        if character in row_by_character:
            row_num = row_by_character[character]
            worksheet.update(
                values=[row_data],
                range_name=f"A{row_num}",
                value_input_option="USER_ENTERED",
            )
            updated += 1
        else:
            worksheet.append_row(row_data, value_input_option="USER_ENTERED")
            appended += 1

    return updated, appended


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export EQ inventory files to CSV and/or Google Sheets."
    )
    parser.add_argument("--config", help="Path to config.yaml or config.xml")
    parser.add_argument("--eq-home", help="EverQuest home / MQ log directory")
    parser.add_argument("--server", help="Server suffix for inventory filenames")
    parser.add_argument("--output", help="CSV output path")
    parser.add_argument("--sheets", help="Google Spreadsheet ID")
    parser.add_argument("--worksheet", help="Google worksheet tab name")
    parser.add_argument("--credentials", help="Path to Google service account JSON key")
    parser.add_argument(
        "--no-recurse",
        action="store_true",
        help="Only search eq_home top level (default: recursive)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    eq_home = Path(config.eq_home)
    try:
        rows = build_row_map(eq_home, config.server, recurse=not args.no_recurse)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if config.output_csv:
        csv_path = Path(config.output_csv)
        write_csv(csv_path, list(rows.values()))
        print(f"Wrote {len(rows)} character(s) to {csv_path}")

    if config.google_sheets is not None:
        try:
            updated, appended = upsert_google_sheets(config.google_sheets, rows)
        except (ConfigError, FileNotFoundError) as exc:
            print(f"Google Sheets error: {exc}", file=sys.stderr)
            return 1
        sheet_url = (
            f"https://docs.google.com/spreadsheets/d/"
            f"{config.google_sheets.spreadsheet_id}"
        )
        print(
            f"Google Sheets: updated {updated}, appended {appended} "
            f"({sheet_url})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
