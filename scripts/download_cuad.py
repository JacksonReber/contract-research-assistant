"""Download a 50-document subset of CUAD into data/cuad/.

CUAD (Contract Understanding Atticus Dataset) ships ~510 commercial
contracts as PDFs. We pull the official Zenodo release zip
(https://zenodo.org/records/4595826), extract a deterministic
50-doc subset, and stage them under data/cuad/ so the rest of the
ingest pipeline can treat them like any other source PDF.

The HuggingFace mirror (theatticusproject/cuad-qa) is script-based
and broken on modern `datasets` versions, so we skip it.
"""

from pathlib import Path
import io
import sys
import urllib.request
import zipfile

OUT_DIR = Path("data/cuad")
ZIP_URL = "https://zenodo.org/records/4595826/files/CUAD_v1.zip"
N_DOCS = 50


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading CUAD_v1.zip from Zenodo ({ZIP_URL})...", file=sys.stderr)
    with urllib.request.urlopen(ZIP_URL) as resp:
        zip_bytes = resp.read()
    print(f"  downloaded {len(zip_bytes) / 1e6:.1f} MB", file=sys.stderr)

    saved = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # PDFs live under CUAD_v1/full_contract_pdf/<Category>/<Subcategory>/<file>.pdf
        pdf_names = sorted(
            n for n in zf.namelist()
            if n.startswith("CUAD_v1/full_contract_pdf/") and n.lower().endswith(".pdf")
        )
        for entry in pdf_names:
            if saved >= N_DOCS:
                break
            data = zf.read(entry)
            filename = Path(entry).name
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in filename)
            out_path = OUT_DIR / f"CUAD-{safe}"
            out_path.write_bytes(data)
            saved += 1

    print(f"Saved {saved} CUAD PDFs to {OUT_DIR}/", file=sys.stderr)


if __name__ == "__main__":
    main()
