"""Raw API responses on disk, gzip-compressed.

Layout under the store root:
    league/<name>.xml.gz              settings, teams, game weeks, draft data
    weeks/scoreboard_wNN.xml.gz       latest scoreboard of each week
    days/<YYYY-MM-DD>/<name>.xml.gz   rosters and stats for that stats day,
                                      plus standings/transactions snapshots
    days/<YYYY-MM-DD>/run.json        written last; marks the day as complete
    samples/<name>.xml.gz             one of each response type (smoke test)
"""
import gzip
import json
import shutil
from pathlib import Path


class RawStore:
    def __init__(self, root):
        self.root = Path(root)

    def _path(self, rel):
        return self.root / (rel + ".gz")

    def save(self, rel, data: bytes):
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        # mtime=0 -> identical content always produces identical bytes.
        path.write_bytes(gzip.compress(data, mtime=0))

    def load(self, rel) -> bytes:
        return gzip.decompress(self._path(rel).read_bytes())

    def exists(self, rel) -> bool:
        return self._path(rel).exists()

    # ---- per-day bookkeeping ---------------------------------------------

    def _day_dir(self, day):
        return self.root / "days" / day

    def mark_done(self, day, info):
        directory = self._day_dir(day)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "run.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def is_done(self, day) -> bool:
        return (self._day_dir(day) / "run.json").exists()

    def run_info(self, day):
        return json.loads((self._day_dir(day) / "run.json").read_text(encoding="utf-8"))

    def done_dates(self):
        days = self.root / "days"
        if not days.exists():
            return []
        return sorted(d.name for d in days.iterdir() if (d / "run.json").exists())

    def files(self, folder):
        """Stored response names directly inside one folder, sorted."""
        directory = self.root / folder
        if not directory.exists():
            return []
        return sorted(f"{folder}/{p.name[:-3]}" for p in directory.glob("*.xml.gz"))

    def day_files(self, day):
        return self.files(f"days/{day}")

    def clear_day(self, day):
        shutil.rmtree(self._day_dir(day), ignore_errors=True)
