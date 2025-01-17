import psycopg2
from psycopg2 import sql

from feast.protos.feast.core.Registry_pb2 import Registry as RegistryProto
from feast.registry_store import RegistryStore
from feast.repo_config import RegistryConfig
from feast_postgres.postgres_config import PostgreSQLConfig
from feast_postgres.utils import _get_conn


class PostgreSQLRegistryStore(RegistryStore):
    def __init__(self, config: RegistryConfig, registry_path: str):
        self.db_config = PostgreSQLConfig(
            host=config.host,
            port=config.port,
            database=config.database,
            db_schema=config.db_schema,
            user=config.user,
            password=config.password,
            sslrootcert_path=config.sslrootcert_path,
            sslcert_path=config.sslcert_path,
            sslkey_path=config.sslkey_path,
            sslmode=config.sslmode
        )
        self.table_name = config.path
        self.cache_ttl_seconds = config.cache_ttl_seconds

    def get_registry_proto(self) -> RegistryProto:
        registry_proto = RegistryProto()
        try:
            with _get_conn(self.db_config) as conn, conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT registry
                        FROM {}
                        WHERE version = (SELECT max(version) FROM {})
                        """
                    ).format(
                        sql.Identifier(self.table_name),
                        sql.Identifier(self.table_name),
                    )
                )
                row = cur.fetchone()
                if row:
                    registry_proto = registry_proto.FromString(row[0])
        except psycopg2.errors.UndefinedTable:
            pass
        return registry_proto

    def update_registry_proto(self, registry_proto: RegistryProto):
        """
        Overwrites the current registry proto with the proto passed in. This method
        writes to the registry path.

        Args:
            registry_proto: the new RegistryProto
        """
        schema_name = self.db_config.db_schema or self.db_config.user
        with _get_conn(self.db_config) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name = %s
                """,
                (schema_name,),
            )
            schema_exists = cur.fetchone()
            if not schema_exists:
                cur.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(
                        sql.Identifier(schema_name),
                        sql.Identifier(self.db_config.user),
                    ),
                )

            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {} (
                        version BIGSERIAL PRIMARY KEY,
                        registry BYTEA NOT NULL
                    );
                    """
                ).format(sql.Identifier(self.table_name)),
            )
            # Do we want to keep track of the history or just keep the latest?
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (registry)
                    VALUES (%s);
                    """
                ).format(sql.Identifier(self.table_name)),
                [registry_proto.SerializeToString()],
            )

    def teardown(self):
        with _get_conn(self.db_config) as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    DROP TABLE IF EXISTS {};
                    """
                ).format(sql.Identifier(self.table_name))
            )
