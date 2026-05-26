# show_totp_qr.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.db.connection import get_connection
from core.auth.totp import get_provisioning_uri
import qrcode

with get_connection() as conn:
    row = conn.execute(
        "SELECT username, totp_secret FROM users WHERE username = 'admin'"
    ).fetchone()

if not row:
    print("No admin user found. Run seed_dev.py first.")
    sys.exit(1)

secret = row["totp_secret"]
uri = get_provisioning_uri(secret, row["username"])
print(f"Secret: {secret}")
print(f"URI: {uri}")

img = qrcode.make(uri)
img.save("totp_qr.png")
print("QR saved to totp_qr.png — scan it with your authenticator app")