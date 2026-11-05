"""Retrieve the preferred actuator CAD bundles and preserve their provenance.

Only STEP files and PDF drawings/specifications are extracted. Vendor archives
remain unmodified; no downloaded script, installer or macro is executed.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "cad/vendor/myactuator"
DOWNLOAD_PAGE = "https://www.myactuator.com/downloads-xseries"
SOURCES = [
    {"part": "RMD-X2-P28-7-E", "revision": "260920", "url":
     "https://www.myactuator.com/_files/archives/cab28a_77b7670917e14f6b8256b4db4d912857.zip?dn=RMD-X2-P28-7+260920.zip"},
    {"part": "RMD-X4-P36-36-E-L", "revision": "261019", "url":
     "https://www.myactuator.com/_files/archives/cab28a_8106ede9e38f497b8c12545bab3f95d5.zip?dn=RMD-X4-P36-36-E-L+261019.zip"},
    {"part": "RMD-X6-P20-60-E", "revision": "260920", "url":
     "https://www.myactuator.com/_files/archives/cab28a_4231acdf891b41f3a56bb690f4c1d312.zip?dn=RMD-X6-P20-60+260920.zip"},
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def retrieve():
    records = []
    for source in SOURCES:
        folder = DESTINATION / source["part"] / source["revision"]
        folder.mkdir(parents=True, exist_ok=True)
        archive_path = folder / "vendor-original.zip"
        if not archive_path.exists():
            print("Downloading " + source["part"], flush=True)
            request = urllib.request.Request(source["url"], headers={"User-Agent": "SolidCraftBot CAD research"})
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read(100_000_001)
            if len(data) > 100_000_000:
                raise ValueError("Unexpectedly large vendor archive")
            if not zipfile.is_zipfile(__import__("io").BytesIO(data)):
                raise ValueError("Download is not a ZIP archive")
            archive_path.write_bytes(data)
        record = {**source, "retrieved_on": "2026-10-28", "download_page": DOWNLOAD_PAGE,
                  "archive": archive_path.relative_to(ROOT).as_posix(), "archive_sha256": sha256(archive_path),
                  "archive_entries": [], "files": []}
        counts = {"step": 0, "pdf": 0}
        with zipfile.ZipFile(archive_path) as archive:
            for item in archive.infolist():
                name = PurePosixPath(item.filename.replace("\\", "/"))
                if name.is_absolute() or ".." in name.parts:
                    raise ValueError("Unsafe path in vendor archive")
                record["archive_entries"].append({"name": item.filename, "bytes": item.file_size})
                suffix = name.suffix.lower()
                kind = "step" if suffix in {".step", ".stp"} else "pdf" if suffix == ".pdf" else None
                if kind is None or item.is_dir():
                    continue
                if item.file_size > 200_000_000:
                    raise ValueError("Unexpectedly large archive member")
                counts[kind] += 1
                filename = "vendor-model-%d.step" % counts[kind] if kind == "step" else "vendor-document-%d.pdf" % counts[kind]
                path = folder / filename
                data = archive.read(item)
                if path.exists() and path.read_bytes() != data:
                    raise ValueError("Existing vendor asset differs: " + str(path))
                if not path.exists():
                    path.write_bytes(data)
                record["files"].append({"kind": kind, "archive_name": item.filename,
                                         "path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "bytes": len(data)})
        record["cad_available"] = counts["step"] > 0
        records.append(record)
        print(source["part"], "STEP files:", counts["step"], "PDFs:", counts["pdf"], flush=True)
    result = {"format": "solidcraftbot.vendor-assets/1", "vendor": "MyActuator", "units_for_import": "mm",
              "status": "vendor_reference_geometry_not_integrated_into_robot", "models": records,
              "rights": "Manufacturer assets retained with attribution; no redistribution licence has been established."}
    (DESTINATION / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = retrieve()
    if not all(model["cad_available"] for model in result["models"]):
        raise SystemExit("A preferred actuator has no STEP file; inspect the saved vendor archive listing")
