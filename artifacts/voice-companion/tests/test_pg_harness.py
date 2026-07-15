def test_pg_conn_roundtrip(pg_conn):
    pg_conn.execute("CREATE TABLE t (id int primary key, name text)")
    pg_conn.execute("INSERT INTO t VALUES (1, 'ok')")
    row = pg_conn.execute("SELECT name FROM t WHERE id = 1").fetchone()
    assert row[0] == "ok"
