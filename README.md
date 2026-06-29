# EQ Inventory Manager

Scans EverQuest inventory export files and builds a roster view of equipped gear — locally as CSV and/or in a shared Google Sheet.

**Input:** `*_{server}-Inventory.txt` files under a configured EQ home directory. Create these using the `/outputfile inventory` command in game.

**Output:** One row per character. Equipment slots are columns. Equipped items appear as clickable [Lucy](https://lucy.allakhazam.com) links.

## What it exports

- **Equipment only** — worn slots (Head, Arms, etc.); not bags, bank, or Held
- **Column order:** `Character`, Head … Waist, Ammo, Charm, Power Source
- **Paired slots:** Left/Right Ear, Wrist, and Fingers (mapped by order in the inventory file)
- **Empty slots:** left blank
- **Equipped items:** Google Sheets `HYPERLINK` formulas pointing to `https://lucy.allakhazam.com/item.html?id=…`

## Requirements

- Python 3
- Inventory text files produced by EQ on the local machine
- Python packages from `requirements.txt`: PyYAML, gspread, google-auth
- (Optional) Google Cloud service account for Sheets export

## Installation

```bash
git clone <repo-url>
cd eq_inventory_mgr
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS
pip install -r requirements.txt
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and edit it. `config.yaml` is gitignored — keep machine-specific paths and secrets local.

```yaml
eq_home: "C:/eq_live"
server: frostreaver

output_csv: inventory.csv

google_sheets:
  spreadsheet_id: "1abc...xyz"
  worksheet: Inventory
  credentials: credentials/credentials.json
```

| Setting | Required | Description |
| --- | --- | --- |
| `eq_home` | yes | EQ install directory to scan (recursive) |
| `server` | yes | Server suffix in filenames (e.g. `frostreaver`) |
| `output_csv` | no* | Local CSV output path |
| `google_sheets.spreadsheet_id` | no* | Spreadsheet ID from the sheet URL |
| `google_sheets.worksheet` | no | Worksheet tab name (default `Inventory`) |
| `google_sheets.credentials` | no | Path to service account JSON (default `credentials/credentials.json`) |

\*At least one of `output_csv` or `google_sheets` must be configured.

**Config discovery:** the script looks for `config.yaml`, `config.yml`, or `config.xml` in the current directory or beside the script. Use `--config path/to/config.yaml` to override.

An XML config format is also supported — see `config.example.xml`.

## Google Sheets setup (one-time)

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the **Google Sheets API**.
2. Create a **service account** and download its JSON key.
3. Save the key as `credentials/credentials.json` (the `credentials/` folder is gitignored).
4. Open the JSON file and copy the `client_email` value.
5. Share your target Google Sheet with that email as **Editor**.
6. Copy the **spreadsheet ID** from the sheet URL — the long string between `/d/` and `/edit`:

   ```
   https://docs.google.com/spreadsheets/d/1abc...xyz/edit
                                         ^^^^^^^^^^^
   ```

### How sheet updates work

Each run only touches rows for characters found on **that machine**:

- **Existing character** → row is updated in place
- **New character** → row is appended at the bottom
- **Other characters** (uploaded from other PCs) → left unchanged

The header row is written once (bold) and rewritten if the column layout changes.

## Usage

From the project root, with `config.yaml` in place:

```bash
python scripts/inventory_export.py
```

Example output:

```
Wrote 4 character(s) to inventory.csv
Google Sheets: updated 3, appended 1 (https://docs.google.com/spreadsheets/d/...)
```

### CLI overrides

All config values can be overridden on the command line:

| Flag | Overrides |
| --- | --- |
| `--config PATH` | Config file path |
| `--eq-home PATH` | `eq_home` |
| `--server NAME` | `server` |
| `--output PATH` | `output_csv` |
| `--sheets ID` | `google_sheets.spreadsheet_id` |
| `--worksheet NAME` | `google_sheets.worksheet` |
| `--credentials PATH` | `google_sheets.credentials` |
| `--no-recurse` | Search only the top level of `eq_home` (default is recursive) |

```bash
python scripts/inventory_export.py --server frostreaver --eq-home "C:/eq_live"
```

## Multi-computer workflow

Several computers can share one Google Sheet. Each machine runs the script with the same `spreadsheet_id` and `server`. Only characters with inventory files on that machine are updated or appended; everyone else's rows stay as they are.

## Project layout

```
eq_inventory_mgr/
  scripts/inventory_export.py   # main script
  config.example.yaml           # config template
  config.example.xml
  requirements.txt
  credentials/                  # gitignored — service account key
  config.yaml                   # gitignored — your local config
```
