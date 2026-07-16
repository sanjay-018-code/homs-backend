import asyncio
import os
import sys
import bcrypt
from motor.motor_asyncio import AsyncIOMotorClient

# Set up path so we can import from app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.config import settings

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# Default password for initial seeded users is "Niresh_007"
DEFAULT_PASSWORD = "Niresh_007"
PASSWORD_HASH = get_password_hash(DEFAULT_PASSWORD)

INITIAL_USERS = [
    {
        "name": "Niresh Admin",
        "email": "niresh@admin.com",
        "role": "admin",
        "password_hash": PASSWORD_HASH,
        "enrollment_status": "active"
    },
    {
        "name": "Niresh Student",
        "email": "niresh@student.com",
        "role": "student",
        "roll_number": "STU101",
        "parent_email": "parent@niresh.com",
        "password_hash": PASSWORD_HASH,
        "enrollment_status": "active"
    },
    {
        "name": "Dr. Advisor",
        "email": "advisor@faculty.com",
        "role": "advisor",
        "password_hash": PASSWORD_HASH,
        "enrollment_status": "active"
    },
    {
        "name": "Charlie Warden",
        "email": "warden@hostel.com",
        "role": "warden",
        "password_hash": PASSWORD_HASH,
        "enrollment_status": "active"
    },
    {
        "name": "Dave HOD",
        "email": "hod@department.com",
        "role": "hod",
        "password_hash": PASSWORD_HASH,
        "enrollment_status": "active"
    },
    {
        "name": "Sam Security",
        "email": "security@gate.com",
        "role": "security",
        "password_hash": PASSWORD_HASH,
        "enrollment_status": "active"
    }
]

async def seed():
    print(f"Connecting to database at URI: {settings.MONGODB_URI}")
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    
    # Initialize indexes
    print("Creating unique indexes on users and outpasses...")
    await db.users.create_index("email", unique=True)
    await db.users.create_index("roll_number", unique=True, sparse=True)
    await db.outpasses.create_index("qr_token", unique=True, sparse=True)
    
    print(f"Upserting {len(INITIAL_USERS)} default users...")
    
    for user_data in INITIAL_USERS:
        email = user_data["email"]
        roll_number = user_data.get("roll_number")
        
        # Check by email or roll_number to avoid index violations
        query = {"email": email}
        if roll_number:
            query = {"$or": [{"email": email}, {"roll_number": roll_number}]}
            
        existing_user = await db.users.find_one(query)
        
        if existing_user:
            # Update credentials & basic properties to ensure synchronization
            print(f"User '{email}' or roll '{roll_number}' already exists. Syncing properties and resetting password...")
            await db.users.update_one(
                {"_id": existing_user["_id"]},
                {"$set": {
                    "name": user_data["name"],
                    "email": email,
                    "role": user_data["role"],
                    "password_hash": user_data["password_hash"],
                    "enrollment_status": "active",
                    **({k: v for k, v in user_data.items() if k in ["roll_number", "parent_email"]})
                }}
            )
        else:
            # Create user
            print(f"Creating user: {email} ({user_data['role']})")
            await db.users.insert_one(user_data)
            
    print("\nDatabase seeding completed successfully!")
    print(f"All seeded accounts have the password set to: {DEFAULT_PASSWORD}")
    print("\nSeeded accounts summary:")
    print(f"  - Admin: niresh@admin.com")
    print(f"  - Student: niresh@student.com")
    print(f"  - Advisor: advisor@faculty.com")
    print(f"  - Warden: warden@hostel.com")
    print(f"  - HOD: hod@department.com")
    print(f"  - Security: security@gate.com")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(seed())
