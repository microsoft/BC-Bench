"""Durable opt-in gold admission and actual outbound attempt reservations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from bcal_reasoning_coding import AdmissionError


class StudyBudget:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def create(cls, path: Path, cells: list[str], binding: str) -> StudyBudget:
        if len(cells) != 330 or len(set(cells)) != 330:
            raise AdmissionError("The study requires exactly 330 distinct frozen cells.")
        with path.open("x"):
            pass
        budget = cls(path)
        with budget.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE study(binding TEXT NOT NULL, stopped INTEGER NOT NULL);
                CREATE TABLE cells(id TEXT PRIMARY KEY, admitted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE attempts(id INTEGER PRIMARY KEY, cell TEXT NOT NULL REFERENCES cells(id), role TEXT NOT NULL);
                CREATE INDEX attempt_role_cell ON attempts(role,cell);
                """
            )
            db.execute("INSERT INTO study VALUES (?,0)", (binding,))
            db.executemany("INSERT INTO cells(id) VALUES (?)", ((cell,) for cell in cells))
        return budget

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)
        try:
            with db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("PRAGMA foreign_keys=ON")
                yield db
        finally:
            db.close()

    def admit(self, cell: str, binding: str) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT binding,stopped FROM study").fetchone() != (binding, 0):
                raise AdmissionError("Study source binding differs or admissions have stopped.")
            if db.execute("UPDATE cells SET admitted=1 WHERE id=? AND admitted=0", (cell,)).rowcount != 1:
                raise AdmissionError("Unknown or previously admitted cell; replacement forbidden.")

    def reserve(self, cell: str, role: str) -> int:
        limits = {"main": 64, "judge": 1}
        if role not in limits:
            raise AdmissionError("Auxiliary and unknown provider roles are forbidden.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            admitted = db.execute("SELECT admitted FROM cells WHERE id=?", (cell,)).fetchone()
            used = db.execute("SELECT COUNT(*) FROM attempts WHERE cell=? AND role=?", (cell, role)).fetchone()[0]
            role_total = db.execute("SELECT COUNT(*) FROM attempts WHERE role=?", (role,)).fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            if db.execute("SELECT stopped FROM study").fetchone() != (0,) or admitted != (1,) or used >= limits[role] or role_total >= limits[role] * 330 or total >= 21450:
                raise AdmissionError("Actual HTTP study/cell budget exhausted or cell not admitted.")
            cursor = db.execute("INSERT INTO attempts(cell,role) VALUES (?,?)", (cell, role))
            return cursor.lastrowid

    def stop(self) -> None:
        with self.connect() as db:
            db.execute("UPDATE study SET stopped=1")

    def snapshot(self) -> dict:
        with self.connect() as db:
            rows = db.execute("SELECT cell,role,COUNT(*) FROM attempts GROUP BY cell,role ORDER BY cell,role").fetchall()
            return {
                "binding": db.execute("SELECT binding FROM study").fetchone()[0],
                "stopped": bool(db.execute("SELECT stopped FROM study").fetchone()[0]),
                "admittedCells": db.execute("SELECT COUNT(*) FROM cells WHERE admitted=1").fetchone()[0],
                "attempts": sum(row[2] for row in rows),
                "codingAttempts": sum(row[2] for row in rows if row[1] == "main"),
                "judgeAttempts": sum(row[2] for row in rows if row[1] == "judge"),
                "cellRoles": [{"cell": cell, "role": role, "attempts": count} for cell, role, count in rows],
            }
