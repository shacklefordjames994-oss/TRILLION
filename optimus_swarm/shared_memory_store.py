import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from optimus_swarm.trust_fabric import (
    SharedExperience,
    TrustDecision,
    TrustPolicy,
    validate_shared_experience,
)


class SharedMemoryStore:
    def __init__(self, database_path: str = ":memory:"):
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)

        self._db = sqlite3.connect(database_path)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS shared_experiences (
                experience_id TEXT PRIMARY KEY,
                source_robot_id TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                inserted_at_ms INTEGER NOT NULL
            )
            """
        )
        self._db.commit()

    def publish(
        self,
        experience: SharedExperience,
        *,
        now_ms: int,
        trusted_source_ids: set[str],
        policy: TrustPolicy = TrustPolicy(),
    ) -> TrustDecision:
        decision = validate_shared_experience(
            experience,
            now_ms=now_ms,
            trusted_source_ids=trusted_source_ids,
            policy=policy,
        )

        if not decision.accepted:
            return decision

        try:
            payload_json = json.dumps(
                asdict(experience),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            with self._db:
                self._db.execute(
                    """
                    INSERT INTO shared_experiences (
                        experience_id,
                        source_robot_id,
                        created_at_ms,
                        payload_json,
                        payload_digest,
                        inserted_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experience.experience_id,
                        experience.source_robot_id,
                        experience.created_at_ms,
                        payload_json,
                        experience.payload_digest,
                        now_ms,
                    ),
                )
        except sqlite3.IntegrityError:
            return TrustDecision(
                accepted=False,
                reason_codes=("DUPLICATE_EXPERIENCE_ID",),
                experience_digest=decision.experience_digest,
                physical_execution_authorized=False,
            )

        return decision

    def retrieve(
        self,
        *,
        now_ms: int,
        trusted_source_ids: set[str],
        policy: TrustPolicy = TrustPolicy(),
        limit: int = 100,
    ) -> list[SharedExperience]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")

        rows = self._db.execute(
            """
            SELECT payload_json
            FROM shared_experiences
            ORDER BY inserted_at_ms DESC, experience_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        accepted: list[SharedExperience] = []

        for (raw,) in rows:
            try:
                data = json.loads(raw)
                data["payload_digest"] = data.get("payload_digest", "")
                item = SharedExperience(**data)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

            decision = validate_shared_experience(
                item,
                now_ms=now_ms,
                trusted_source_ids=trusted_source_ids,
                policy=policy,
            )

            if decision.accepted:
                accepted.append(item)

        return accepted

    def close(self) -> None:
        self._db.close()
