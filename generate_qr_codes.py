"""
Batch-generates a QR code PNG for every staff member in staff.json.
Each QR code encodes the URL of that person's card, e.g.:
    https://wankeley.github.io/staff-cards/index.html?id=emp001

Setup:
    pip install qrcode[pil]

Usage:
    python generate_qr_codes.py
"""

import json
import os
import qrcode

# --- Configuration ---------------------------------------------------------

STAFF_JSON_PATH = "staff.json"
OUTPUT_DIR = "qr_codes"

# Change this to your real GitHub Pages URL (and repo name / custom domain
# once you have one).
BASE_URL = "https://wankeley.github.io/staff-cards/index.html"

# ----------------------------------------------------------------------------


def load_staff(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_qr(url, output_path):
    qr = qrcode.QRCode(
        version=None,          # auto-size to fit the data
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_path)


def main():
    staff = load_staff(STAFF_JSON_PATH)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for emp_id, details in staff.items():
        url = f"{BASE_URL}?id={emp_id}"
        filename = os.path.join(OUTPUT_DIR, f"{emp_id}.png")
        generate_qr(url, filename)
        name = details.get("name", emp_id)
        print(f"Generated {filename}  ->  {url}  ({name})")

    print(f"\nDone. {len(staff)} QR code(s) saved to '{OUTPUT_DIR}/'.")


if __name__ == "__main__":
    main()
