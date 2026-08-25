"""ORM ↔ init.sql 漂移防护：解析 01_schema.sql 的列集合与 ORM metadata 双向比对。

纯文件级校验（无需真实 MySQL），保证「DDL 是权威、ORM 不漂移」。
"""
import re
from pathlib import Path

import pytest

from app.models import Base

SQL_PATH = Path(__file__).resolve().parents[2] / "deploy" / "mysql" / "init" / "01_schema.sql"

EXPECTED_TABLES = {
    "departments", "users", "roles", "user_roles", "role_permissions",
    "knowledge_units", "knowledge_chunks", "unit_permissions",
    "qa_sessions", "qa_access_logs", "faqs", "knowledge_gaps", "import_tasks",
}


def _parse_sql_tables(sql_text: str) -> dict[str, set[str]]:
    """提取每张 CREATE TABLE 的列名集合（剔除索引行/注释内容）。"""
    tables: dict[str, set[str]] = {}
    pattern = re.compile(
        r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\)\s*ENGINE", re.S
    )
    for match in pattern.finditer(sql_text):
        table_name, body = match.group(1), match.group(2)
        # 去掉单引号字符串内容，避免 COMMENT '...' 内逗号干扰
        body = re.sub(r"'[^']*'", "''", body)
        columns: set[str] = set()
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            first_token = line.split()[0].strip("`").lower()
            if first_token.upper() in {
                "KEY", "UNIQUE", "FULLTEXT", "CONSTRAINT", "PRIMARY", "INDEX", "FOREIGN",
            }:
                continue
            columns.add(first_token)
        tables[table_name] = columns
    return tables


@pytest.fixture(scope="module")
def sql_tables() -> dict[str, set[str]]:
    assert SQL_PATH.exists(), f"找不到 {SQL_PATH}"
    parsed = _parse_sql_tables(SQL_PATH.read_text(encoding="utf-8"))
    assert set(parsed) == EXPECTED_TABLES, f"DDL 表集合异常: {set(parsed) ^ EXPECTED_TABLES}"
    return parsed


def test_orm_registers_exactly_thirteen_tables():
    orm_tables = set(Base.metadata.tables)
    assert orm_tables == EXPECTED_TABLES, f"ORM 表差异: {orm_tables ^ EXPECTED_TABLES}"


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_columns_no_drift(table: str, sql_tables: dict[str, set[str]]):
    orm_cols = {c.name for c in Base.metadata.tables[table].columns}
    ddl_cols = sql_tables[table]
    missing_in_orm = ddl_cols - orm_cols
    missing_in_ddl = orm_cols - ddl_cols
    assert not missing_in_orm, f"[{table}] DDL 有而 ORM 缺: {sorted(missing_in_orm)}"
    assert not missing_in_ddl, f"[{table}] ORM 有而 DDL 缺: {sorted(missing_in_ddl)}"


def test_ngram_fulltext_present():
    raw = SQL_PATH.read_text(encoding="utf-8")
    assert "FULLTEXT KEY ft_content (content) WITH PARSER ngram" in raw
