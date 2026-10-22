import json
import sqlite3

from .models import Experience, RetrievalContext
from .guard import OmegaGuard


class SwarmMemory:
    """Persistent experience store shared by simulated robots."""

    def __init__(self, path="swarm_memory.sqlite3", kill_switch=None):
        self.path = path
        self.kill_switch = kill_switch

        with self._connect() as db:
            self._prepare(db)

    def _connect(self):
        return sqlite3.connect(self.path)

    def _prepare(self, db):
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS experiences (
                experience_id TEXT PRIMARY KEY,
                origin_robot_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_digest TEXT NOT NULL
            )
            """
        )
        cols = {row[1] for row in db.execute("PRAGMA table_info(experiences)")}
        if "validation_status" not in cols:
            db.execute(
                """
                ALTER TABLE experiences
                ADD COLUMN validation_status TEXT NOT NULL DEFAULT 'PENDING'
                """
            )
        if "quarantine_incident_id" not in cols:
            db.execute(
                """
                ALTER TABLE experiences
                ADD COLUMN quarantine_incident_id TEXT
                """
            )

    def _simulation_permitted(self) -> bool:
        switch = self.kill_switch
        if switch is None:
            return True
        try:
            return bool(switch.permits_simulation())
        except Exception:
            return False

    def publish(self, experience: Experience) -> None:
        """Publish a record; publication does not establish trust."""
        payload = json.dumps(
            experience.payload(),
            sort_keys=True,
            separators=(",", ":"),
        )

        with self._connect() as db:
            self._prepare(db)
            db.execute(
                """
                INSERT INTO experiences (
                    experience_id,
                    origin_robot_id,
                    payload_json,
                    payload_digest,
                    validation_status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    experience.experience_id,
                    experience.origin_robot_id,
                    payload,
                    experience.digest(),
                    experience.validation_status,
                ),
            )

    def quarantine(self, record_id: str, incident_id: str) -> bool:
        """
        Persist quarantine. A failed update must not leave the record usable.
        """
        if not record_id or not incident_id:
            return False

        try:
            with self._connect() as db:
                self._prepare(db)
                cursor = db.execute(
                    """
                    UPDATE experiences
                    SET validation_status = 'QUARANTINED',
                        quarantine_incident_id = ?
                    WHERE experience_id = ?
                    """,
                    (incident_id, record_id),
                )
                if cursor.rowcount == 1:
                    return True
        except Exception:
            pass

        try:
            with self._connect() as db:
                db.execute(
                    "DELETE FROM experiences WHERE experience_id = ?",
                    (record_id,),
                )
        except Exception:
            pass
        return False

    def retrieve_candidates(
        self,
        context: RetrievalContext,
        guard: OmegaGuard,
    ) -> list[tuple[Experience, str]]:
        """Return only VALIDATED records accepted by the receiver policy.

        Quarantined rows are excluded. A latched or unreadable safety
        switch yields nothing. Publication never establishes trust.
        """
        if not self._simulation_permitted():
            return []

        try:
            latch = guard.check_kill_switch()
        except Exception:
            return []
        if not latch.allowed:
            return []

        try:
            with self._connect() as db:
                self._prepare(db)
                rows = db.execute(
                    """
                    SELECT payload_json, payload_digest
                    FROM experiences
                    WHERE validation_status = 'VALIDATED'
                    """
                ).fetchall()
        except Exception:
            return []

        accepted = []

        for payload_json, stored_digest in rows:
            try:
                record = json.loads(payload_json)
                experience = Experience(**record)

                if experience.digest() != stored_digest:
                    continue
                if experience.validation_status != "VALIDATED":
                    continue

                decision = guard.validate_shared_memory(experience, context)

                if decision.allowed:
                    accepted.append((experience, decision.code))

            except (ValueError, TypeError, KeyError):
                continue

        return accepted
