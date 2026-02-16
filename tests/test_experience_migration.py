"""
Migration Tests - Test database schema migrations
Specifically tests Phase 10 experience_tool migration for legacy databases.
"""
import pytest
import sqlite3
from pathlib import Path
import tempfile
import shutil
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestExperienceMigration:
  """Test experience_tool handles legacy databases without crashing"""

  @pytest.fixture
  def temp_data_dir(self):
    """Create temporary data directory"""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

  def _create_legacy_db(self, db_path: Path):
    """
    Create a legacy experiences.db WITHOUT the Phase 10 columns:
    - people, sentiment, rating, tags

    This simulates a database created before Phase 10.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Legacy schema (pre-Phase 10) - missing people, sentiment, rating, tags
    cursor.execute("""
      CREATE TABLE experiences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        date DATE NOT NULL,
        time TEXT,
        category TEXT DEFAULT 'activity',
        place TEXT,
        city TEXT,
        amount REAL DEFAULT 0,
        currency TEXT DEFAULT 'INR',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    """)

    # Add some legacy data
    cursor.execute("""
      INSERT INTO experiences (text, date, place, amount)
      VALUES ('Went to mall', '2026-01-15', 'Phoenix Mall', 500)
    """)
    cursor.execute("""
      INSERT INTO experiences (text, date, place)
      VALUES ('Had coffee with friend', '2026-01-20', 'Starbucks')
    """)

    conn.commit()
    conn.close()

  def _get_columns(self, db_path: Path) -> set:
    """Get column names from experiences table"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(experiences)")
    cols = {row[1] for row in cursor.fetchall()}
    conn.close()
    return cols

  def test_legacy_db_auto_migrates(self, temp_data_dir):
    """
    Test that a legacy DB without 'people' column auto-migrates
    when ExperienceTool is initialized.
    """
    db_path = temp_data_dir / "experiences.db"

    # Create legacy DB
    self._create_legacy_db(db_path)

    # Verify legacy state - missing columns
    cols_before = self._get_columns(db_path)
    assert "people" not in cols_before, "Legacy DB should not have 'people' column"
    assert "sentiment" not in cols_before
    assert "rating" not in cols_before
    assert "tags" not in cols_before

    # Initialize ExperienceTool (should trigger migration)
    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(data_dir=temp_data_dir)

    # Verify columns were added
    cols_after = self._get_columns(db_path)
    assert "people" in cols_after, "Migration should add 'people' column"
    assert "sentiment" in cols_after, "Migration should add 'sentiment' column"
    assert "rating" in cols_after, "Migration should add 'rating' column"
    assert "tags" in cols_after, "Migration should add 'tags' column"

  def test_legacy_data_preserved(self, temp_data_dir):
    """Test that existing data is preserved after migration"""
    db_path = temp_data_dir / "experiences.db"

    # Create legacy DB with data
    self._create_legacy_db(db_path)

    # Initialize (triggers migration)
    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(data_dir=temp_data_dir)

    # Verify data still exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM experiences")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 2, "Legacy data should be preserved"

  def test_migration_is_idempotent(self, temp_data_dir):
    """Test that running migration multiple times doesn't crash"""
    db_path = temp_data_dir / "experiences.db"

    # Create legacy DB
    self._create_legacy_db(db_path)

    # Initialize multiple times (simulates app restarts)
    from src.agent.tools.experience_tool import ExperienceTool
    tool1 = ExperienceTool(data_dir=temp_data_dir)
    tool2 = ExperienceTool(data_dir=temp_data_dir)
    tool3 = ExperienceTool(data_dir=temp_data_dir)

    # Should not crash and columns should exist
    cols = self._get_columns(db_path)
    assert "people" in cols

  def test_new_db_has_all_columns(self, temp_data_dir):
    """Test that a fresh DB is created with all columns"""
    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(data_dir=temp_data_dir)

    cols = self._get_columns(temp_data_dir / "experiences.db")

    assert "id" in cols
    assert "text" in cols
    assert "date" in cols
    assert "place" in cols
    assert "people" in cols
    assert "sentiment" in cols
    assert "rating" in cols
    assert "tags" in cols

  def test_can_insert_with_new_columns_after_migration(self, temp_data_dir):
    """Test that new columns work after migration"""
    db_path = temp_data_dir / "experiences.db"

    # Create legacy DB and migrate
    self._create_legacy_db(db_path)

    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(data_dir=temp_data_dir)

    # Insert using new columns
    result = tool.execute("log", {
      "text": "Dinner with family",
      "date": "today",
      "place": "Restaurant",
      "people": "Mom, Dad",
      "sentiment": "happy",
      "rating": 5
    })

    assert result.success, f"Insert should work: {result.message}"

  def test_search_works_with_migrated_columns(self, temp_data_dir):
    """Test that search on new columns works after migration"""
    db_path = temp_data_dir / "experiences.db"

    # Create legacy and migrate
    self._create_legacy_db(db_path)

    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(data_dir=temp_data_dir)

    # Add entry with people
    tool.execute("log", {
      "text": "Meeting with boss",
      "date": "today",
      "people": "John"
    })

    # Search should work
    result = tool.execute("search", {"query": "John"})
    assert result.success

  def test_indexes_created_after_migration(self, temp_data_dir):
    """Test that indexes are created on migrated columns"""
    db_path = temp_data_dir / "experiences.db"

    # Create legacy and migrate
    self._create_legacy_db(db_path)

    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(data_dir=temp_data_dir)

    # Check indexes exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='experiences'")
    indexes = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "idx_exp_people" in indexes, "Index on people column should exist"
    assert "idx_exp_place" in indexes, "Index on place column should exist"
    assert "idx_exp_date" in indexes, "Index on date column should exist"


class TestMigrationEdgeCases:
  """Edge case tests for migration robustness"""

  @pytest.fixture
  def temp_data_dir(self):
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

  def test_partial_migration_recovery(self, temp_data_dir):
    """
    Test that if only some Phase 10 columns exist (partial migration),
    remaining columns are still added.
    """
    db_path = temp_data_dir / "experiences.db"

    # Create DB with SOME new columns but not all (has base + people, missing sentiment/rating/tags)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
      CREATE TABLE experiences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        date DATE NOT NULL,
        time TEXT,
        category TEXT DEFAULT 'activity',
        place TEXT,
        city TEXT,
        amount REAL DEFAULT 0,
        currency TEXT DEFAULT 'INR',
        people TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    """)
    conn.commit()
    conn.close()

    # Initialize - should add missing columns
    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(data_dir=temp_data_dir)

    # Verify all columns now exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(experiences)")
    cols = {row[1] for row in cursor.fetchall()}
    conn.close()

    assert "sentiment" in cols, "Missing 'sentiment' should be added"
    assert "rating" in cols, "Missing 'rating' should be added"
    assert "tags" in cols, "Missing 'tags' should be added"

  def test_legacy_db_minimal_schema(self, temp_data_dir):
    """Test migration on legacy database with only essential columns"""
    db_path = temp_data_dir / "experiences.db"

    # Create legacy DB with base columns but no Phase 10 additions
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
      CREATE TABLE experiences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        date DATE NOT NULL,
        time TEXT,
        category TEXT DEFAULT 'activity',
        place TEXT,
        city TEXT,
        amount REAL DEFAULT 0,
        currency TEXT DEFAULT 'INR',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    """)
    conn.commit()
    conn.close()

    # Should not crash
    from src.agent.tools.experience_tool import ExperienceTool
    tool = ExperienceTool(data_dir=temp_data_dir)

    # Can insert with new columns
    result = tool.execute("log", {
      "text": "Test event",
      "date": "today",
      "people": "Alice, Bob",
      "sentiment": "happy"
    })
    assert result.success


if __name__ == "__main__":
  pytest.main([__file__, "-v"])
