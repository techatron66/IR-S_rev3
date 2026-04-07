#!/usr/bin/env python3
"""
Database migration script - Fix schema issues
"""
import os
import sqlite3
from sqlmodel import SQLModel, create_engine
from models import *

DB_URL = "sqlite:///./main_app.db"
engine = create_engine(DB_URL)

print("🔧 Running database migration...")

# Drop all tables by dropping them via SQL
with sqlite3.connect("main_app.db") as conn:
    cursor = conn.cursor()
    
    # Get list of all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    # Drop each table
    for table in tables:
        table_name = table[0]
        print(f"  Dropping table: {table_name}")
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name};")
        except Exception as e:
            print(f"  ⚠️  Could not drop {table_name}: {e}")
    
    conn.commit()
    print("✅ All tables dropped")

# Recreate all tables with correct schema
print("📝 Recreating tables with new schema...")
SQLModel.metadata.create_all(engine)
print("✅ Database migration complete!\n")

# Verify tables
with sqlite3.connect("main_app.db") as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    print("📊 Database tables:")
    for table in tables:
        print(f"  ✅ {table[0]}")

print("\n🎉 Database ready!")
