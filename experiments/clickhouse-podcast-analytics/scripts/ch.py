"""Tiny ClickHouse HTTP helper (stdlib only).

Used by experiments/clickhouse-podcast-analytics/scripts/generate.py and
experiments/clickhouse-podcast-analytics/scripts/bench.py.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

URL = "http://127.0.0.1:8123/"


class ClickHouseError(RuntimeError):
    pass


def _post(data: bytes, params: dict, retries: int = 30):
    qs = urllib.parse.urlencode(params)
    last = None
    for _ in range(retries):
        req = urllib.request.Request(URL + "?" + qs, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = resp.read().decode()
                summary = json.loads(resp.headers.get("X-ClickHouse-Summary", "{}"))
                return body, {k: int(v) for k, v in summary.items()}
        except urllib.error.HTTPError as e:
            raise ClickHouseError(e.read().decode()) from None
        except (urllib.error.URLError, ConnectionError) as e:
            # Server may be restarting right after the init scripts ran.
            last = e
            time.sleep(1)
    raise ClickHouseError(f"cannot reach ClickHouse: {last}")


def query(sql: str, **settings):
    """Run a query; returns (body_text, summary_dict)."""
    return _post(sql.encode(), settings)


def rows(sql: str, **settings):
    """Run a query and return rows as lists (TSV, all values as strings)."""
    body, _ = query(sql, **settings)
    return [line.split("\t") for line in body.splitlines()]


def insert(table: str, data: str, fmt: str = "TabSeparated"):
    """Insert a pre-formatted payload with one INSERT; returns the summary."""
    params = {"query": f"INSERT INTO {table} FORMAT {fmt}"}
    _, summary = _post(data.encode(), params)
    return summary
