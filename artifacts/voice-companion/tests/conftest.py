import atexit
import os
import shutil
import socket
import subprocess
import tempfile

import pytest

PG_BIN = os.environ.get("PG_BIN", "/opt/homebrew/opt/postgresql@16/bin")
# Postgres on macOS refuses to start multithreaded unless a locale is set.
_ENV = {**os.environ, "LC_ALL": "en_US.UTF-8", "LC_CTYPE": "en_US.UTF-8"}


def _free_port() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return str(port)


def _run(*args):
    r = subprocess.run(args, env=_ENV, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed (exit {r.returncode}):\n{r.stdout}")


@pytest.fixture(scope="session")
def _pg_server():
    if not os.path.exists(os.path.join(PG_BIN, "pg_ctl")):
        pytest.skip("local postgresql@16 not installed (set PG_BIN)")
    tmp = tempfile.mkdtemp(prefix="ledger_pg.")
    data = os.path.join(tmp, "data")
    log = os.path.join(tmp, "log")
    try:
        _run(os.path.join(PG_BIN, "initdb"), "-D", data, "-U", "postgres", "--auth=trust")
        port = _free_port()
        _run(os.path.join(PG_BIN, "pg_ctl"), "-D", data, "-l", log, "-o", f"-p {port}", "-w", "start")
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    def _stop():
        subprocess.run([os.path.join(PG_BIN, "pg_ctl"), "-D", data, "-w", "stop"],
                       env=_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        shutil.rmtree(tmp, ignore_errors=True)

    atexit.register(_stop)
    try:
        yield f"host=127.0.0.1 port={port} user=postgres"
    finally:
        _stop()


@pytest.fixture
def pg_conn(_pg_server):
    import psycopg
    with psycopg.connect(f"{_pg_server} dbname=postgres", autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        yield conn
