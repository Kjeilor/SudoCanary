"""One-time dev setup — creates admin user and one room."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db.schema import initialise_schema
from core.auth.auth_service import auth_service
from core.auth.totp import generate_secret, generate_qr_bytes, get_provisioning_uri
from core.models.user import SystemRole
from core.room_impl import RoomAPIImpl
from core.models.user import User, RoomRole
from core.sdk.types import UserId, RoomId
import uuid
from datetime import datetime

initialise_schema()

# Create admin user
user = auth_service.create_user(
    username="admin",
    display_name="Admin User",
    password="admin1234",
    system_role=SystemRole.ADMIN,
)
print(f"Created user: admin / admin1234")

# Enroll TOTP
secret = generate_secret()
auth_service.enroll_totp(user.user_id, secret)
uri = get_provisioning_uri(secret, "admin")
print(f"\nTOTP secret: {secret}")
print(f"Provisioning URI: {uri}")
print("\nScan the QR code below with your authenticator app:")

# Print QR to terminal
import qrcode as qr
qr.make(uri).save("totp_qr.png")
print("QR saved to totp_qr.png — open it and scan with Google Authenticator or Authy")

# Mark first login complete so data notice triggers properly
from core.db.connection import get_connection
from datetime import datetime
with get_connection() as conn:
    conn.execute(
        "UPDATE users SET first_login_complete = 0 WHERE user_id = ?",
        (user.user_id,)
    )

# Create a demo room
from core.db.connection import get_connection
room_id = str(uuid.uuid4())
now = datetime.utcnow().isoformat()
with get_connection() as conn:
    conn.execute(
        "INSERT INTO rooms (room_id, name, description, created_at, created_by) VALUES (?,?,?,?,?)",
        (room_id, "RoadWorks Room", "Demo room for the showcase", now, user.user_id)
    )
    conn.execute(
        "INSERT INTO room_roles (user_id, room_id, role) VALUES (?,?,?)",
        (user.user_id, room_id, "officer")
    )
print(f"\nCreated room: RoadWorks Room")
print("\nDone. Run: python app/main.py")