"""
Tiny automatic migration: adds any NEW columns to tables that already
exist, so people with an older lifeflow.db do not have to delete it.
(For PostgreSQL you can use `alembic upgrade head` instead.)
"""
from sqlalchemy import inspect, text


def add_missing_columns(engine, base) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table in base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all() already built it with every column
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                column_type = column.type.compile(engine.dialect)
                connection.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {column_type}'))
