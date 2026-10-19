"""Migration regression tests; PostgreSQL cases use a disposable test database.

python -m unittest backend.tests.test_stock_code_upgrade -v
Set RUN_MIGRATION_PG_TESTS=1 inside the backend container to include real PG tests.
"""

import ast
import io
import logging
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SQL_11 = ROOT / "data/upgrade_v1.0.11.sql"
SQL_14 = ROOT / "data/upgrade_v1.0.14.sql"


def load_startup_function(name, **overrides):
    """Load actual startup functions without starting app imports/background jobs."""
    path = ROOT / "backend/main_oss.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    namespace = {"os": os, "__file__": str(path), "logger": logging.getLogger(__name__)}
    namespace.update(overrides)
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace
    )
    return namespace[name]


class StartupMigrationTests(unittest.TestCase):
    def test_versions_are_sorted_numerically_and_duplicate_mounts_run_once(self):
        paths = ["/data/upgrade_v1.0.9.sql", "/data/upgrade_v1.0.10.sql"]
        function = load_startup_function("_upgrade_script_paths")
        with patch(
            "glob.glob", side_effect=[paths, [paths[0]], ["/repo/upgrade_v1.0.14.sql"]]
        ):
            result = function()
        self.assertEqual(
            [os.path.basename(p) for p in result],
            ["upgrade_v1.0.9.sql", "upgrade_v1.0.10.sql", "upgrade_v1.0.14.sql"],
        )

    def test_shared_connection_rolls_back_before_following_patch_and_closes(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        aborted = False
        completed = []

        def execute(text):
            nonlocal aborted
            if text == "ROLLBACK":
                aborted = False
                return
            if text == "bad":
                aborted = True
                raise RuntimeError("unique violation inside BEGIN")
            if aborted:
                raise AssertionError("following patch inherited aborted transaction")
            completed.append(text)

        cursor.execute.side_effect = execute
        driver = types.SimpleNamespace(connect=lambda **kwargs: connection)
        function = load_startup_function(
            "_ensure_database_schema_python",
            _upgrade_script_paths=lambda: ["bad.sql", "good.sql"],
            open=lambda path, **kwargs: io.StringIO(
                {"bad.sql": "bad", "good.sql": "good"}.get(str(path), "init")
            ),
        )
        with (
            patch.dict(sys.modules, {"psycopg2": driver}),
            patch("os.path.isfile", return_value=True),
        ):
            function()
        self.assertIn("good", completed)
        cursor.execute.assert_any_call("ROLLBACK")
        connection.close.assert_called_once()

    def test_single_patch_failure_closes_connection(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = lambda text: (
            None
            if text == "ROLLBACK"
            else (_ for _ in ()).throw(RuntimeError("failure"))
        )
        driver = types.SimpleNamespace(connect=lambda **kwargs: connection)
        function = load_startup_function(
            "_ensure_upgrade_scripts_python",
            open=lambda *a, **k: io.StringIO("BEGIN; bad;"),
        )
        with patch.dict(sys.modules, {"psycopg2": driver}):
            function("bad.sql")
        cursor.execute.assert_any_call("ROLLBACK")
        connection.close.assert_called_once()

    def test_psql_stops_on_errors(self):
        function = load_startup_function(
            "_ensure_upgrade_scripts", _upgrade_script_paths=lambda: ["bad.sql"]
        )
        with patch("subprocess.run") as run:
            run.return_value.returncode = 1
            function({})
        self.assertIn("ON_ERROR_STOP=1", run.call_args.args[0])

    def test_replay_and_new_version_have_identical_transaction_bodies(self):
        scripts = [p.read_text(encoding="utf-8") for p in (SQL_11, SQL_14)]
        self.assertEqual(*(text[text.index("BEGIN;") :] for text in scripts))


@unittest.skipUnless(
    os.getenv("RUN_MIGRATION_PG_TESTS") == "1", "real PG tests not enabled"
)
class PostgreSQLMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql

        cls.driver = psycopg2
        cls.options = {
            "host": os.getenv("DB_HOST", "db"),
            "port": os.getenv("DB_PORT", "5432"),
            "user": os.getenv("DB_USER", "quantmind"),
            "password": os.getenv("DB_PASSWORD", ""),
        }
        cls.database = "qm_suffix_test_" + uuid4().hex[:12]
        cls.admin = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "quantmind"), **cls.options
        )
        cls.admin.autocommit = True
        with cls.admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database))
            )

    @classmethod
    def tearDownClass(cls):
        from psycopg2 import sql

        try:
            with cls.admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {}").format(sql.Identifier(cls.database))
                )
        finally:
            cls.admin.close()

    def setUp(self):
        self.connection = self.driver.connect(dbname=self.database, **self.options)
        self.connection.autocommit = True
        self.cursor = self.connection.cursor()
        self.cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        self.cursor.execute("""
            CREATE TABLE quote_daily_summaries (
              id INTEGER PRIMARY KEY, trade_date DATE NOT NULL, symbol TEXT NOT NULL,
              data_source TEXT, close_price FLOAT, quote_count INTEGER,
              UNIQUE(trade_date, symbol, data_source)
            );
            INSERT INTO quote_daily_summaries VALUES
              (1,'2026-10-08','SH600000','remote_redis',9.1,10),
              (2,'2026-10-08','600000.SH','remote_redis',9.9,20),
              (3,'2026-10-09','SH600000','remote_redis',9.2,30),
              (4,'2026-10-08','SH600000','quantdb',9.3,40),
              (5,'2026-10-08','SZ000001',NULL,11.1,50),
              (6,'2026-10-08','000001.SZ',NULL,11.9,60),
              (7,'2026-10-08','AAPL','external',200,1),
              (8,'2026-10-08','sh600001','external',9,1);
            CREATE TABLE positions (stock_code TEXT);
            INSERT INTO positions VALUES ('BJ920000');
            CREATE VIEW position_view AS SELECT stock_code FROM positions;
        """)

    def tearDown(self):
        self.cursor.execute("ROLLBACK")
        self.cursor.close()
        self.connection.close()

    def test_collision_archives_complete_rows_and_replay_is_idempotent(self):
        for script in (SQL_14, SQL_11, SQL_14):
            self.cursor.execute(script.read_text(encoding="utf-8"))
        self.cursor.execute(
            "SELECT id,symbol,close_price,quote_count FROM quote_daily_summaries ORDER BY id"
        )
        self.assertEqual(
            self.cursor.fetchall(),
            [
                (2, "600000.SH", 9.9, 20),
                (3, "600000.SH", 9.2, 30),
                (4, "600000.SH", 9.3, 40),
                (6, "000001.SZ", 11.9, 60),
                (7, "AAPL", 200, 1),
                (8, "sh600001", 9, 1),
            ],
        )
        self.cursor.execute(
            "SELECT row_id,legacy_row,canonical_row FROM stock_code_migration_conflicts ORDER BY row_id"
        )
        rows = self.cursor.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1]["close_price"], 9.1)
        self.assertEqual(rows[0][1]["quote_count"], 10)
        self.assertEqual(rows[0][2]["close_price"], 9.9)
        self.cursor.execute("SELECT stock_code FROM positions")
        self.assertEqual(self.cursor.fetchone()[0], "920000.BJ")

    def test_unhandled_constraint_rolls_back_without_discarding_financial_rows(self):
        self.cursor.execute(
            "CREATE TABLE orders(symbol TEXT UNIQUE); INSERT INTO orders VALUES ('SZ000001'),('000001.SZ')"
        )
        with self.assertRaises(self.driver.errors.UniqueViolation):
            self.cursor.execute(SQL_11.read_text(encoding="utf-8"))
        self.cursor.execute("ROLLBACK")
        self.cursor.execute("SELECT count(*) FROM quote_daily_summaries")
        self.assertEqual(self.cursor.fetchone()[0], 8)
        self.cursor.execute(
            "SELECT to_regclass('public.stock_code_migration_conflicts')"
        )
        self.assertIsNone(self.cursor.fetchone()[0])

    def test_empty_database_is_supported(self):
        self.cursor.execute(
            "DROP VIEW position_view; DROP TABLE positions, quote_daily_summaries"
        )
        self.cursor.execute(SQL_14.read_text(encoding="utf-8"))

    def test_startup_recovers_real_autocommit_connection_after_explicit_begin_failure(
        self,
    ):
        connection = self.driver.connect(dbname=self.database, **self.options)
        function = load_startup_function(
            "_ensure_database_schema_python",
            _upgrade_script_paths=lambda: ["bad.sql", "good.sql"],
            open=lambda path, **kwargs: io.StringIO(
                {
                    "bad.sql": "BEGIN; SELECT 1/0; COMMIT;",
                    "good.sql": "CREATE TABLE completed_upgrade (id INT);",
                }.get(str(path), "SELECT 1;")
            ),
        )
        with (
            patch.object(self.driver, "connect", return_value=connection),
            patch("os.path.isfile", return_value=True),
        ):
            function()
        self.assertTrue(connection.closed)
        self.cursor.execute("SELECT to_regclass('public.completed_upgrade')")
        self.assertEqual(self.cursor.fetchone()[0], "completed_upgrade")


if __name__ == "__main__":
    unittest.main()
