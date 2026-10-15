#!/usr/bin/env python
"""
Seed the OneBoard database with the turnkey 'NorthStar Studio' business profile.
"""
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apps.api.core.database import SessionLocal, init_db
from apps.api.services.seed_data import seed_northstar_studio

def main():
    print("Initializing OneBoard database...")
    init_db()
    db = SessionLocal()
    try:
        print("Seeding NorthStar Studio demo profile...")
        seed_northstar_studio(db, reset=True)
        print("Database successfully initialized and seeded with NorthStar Studio!")
    finally:
        db.close()

if __name__ == "__main__":
    main()
