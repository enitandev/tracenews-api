"""
A small in-memory stand-in for the Supabase query builder, covering the calls
the notification engine makes (select/insert/update/upsert/delete with eq,
is_, like, gte, in_, order, limit). Unique open keys are enforced like the
staff_notifications_open_key index.
"""
import re
import uuid


class _Res:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters, self.op, self.payload = [], "select", None
        self._order, self._limit, self.on_conflict = None, None, None

    # building
    def select(self, *_a, **_k):
        return self

    def insert(self, rows):
        self.op, self.payload = "insert", rows if isinstance(rows, list) else [rows]
        return self

    def update(self, values):
        self.op, self.payload = "update", values
        return self

    def upsert(self, rows, on_conflict=None):
        self.op, self.payload = "upsert", rows if isinstance(rows, list) else [rows]
        self.on_conflict = on_conflict.split(",") if on_conflict else ["id"]
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def is_(self, col, val):
        assert val == "null"
        self.filters.append(lambda r: r.get(col) is None)
        return self

    def like(self, col, pattern):
        rx = re.compile("^" + re.escape(pattern).replace("%", ".*") + "$")
        self.filters.append(lambda r: r.get(col) is not None and rx.match(r[col]) is not None)
        return self

    def gte(self, col, val):
        self.filters.append(lambda r: r.get(col) is not None and r[col] >= val)
        return self

    def in_(self, col, vals):
        self.filters.append(lambda r: r.get(col) in vals)
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    # running
    def _match(self):
        return [r for r in self.db.tables.setdefault(self.table, []) if all(f(r) for f in self.filters)]

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "select":
            out = [dict(r) for r in self._match()]
            if self._order:
                col, desc = self._order
                out.sort(key=lambda r: r.get(col) or "", reverse=desc)
            return _Res(out[: self._limit] if self._limit else out)
        if self.op == "insert":
            out = []
            for row in self.payload:
                row = {"id": str(uuid.uuid4()), "resolved_at": None, "occurrences": 1, "meta": {},
                       "emailed_at": None, "escalated_at": None, **row}
                if self.table == "staff_notifications" and any(
                        r["dedupe_key"] == row["dedupe_key"] and r.get("resolved_at") is None for r in rows):
                    raise Exception("duplicate key value violates unique constraint (23505)")
                rows.append(row)
                out.append(dict(row))
            return _Res(out)
        if self.op == "update":
            hit = self._match()
            for r in hit:
                r.update(self.payload)
            return _Res([dict(r) for r in hit])
        if self.op == "upsert":
            for row in self.payload:
                same = [r for r in rows if all(r.get(c) == row.get(c) for c in self.on_conflict)]
                if same:
                    same[0].update(row)
                else:
                    rows.append(dict(row))
            return _Res(self.payload)
        if self.op == "delete":
            hit = self._match()
            self.db.tables[self.table] = [r for r in rows if r not in hit]
            return _Res(hit)
        raise AssertionError(self.op)


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}

    def table(self, name):
        return _Query(self, name)

    def rows(self, name):
        return self.tables.get(name, [])
