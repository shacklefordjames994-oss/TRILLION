from dataclasses import dataclass


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    source_id: str
    public_key_bytes: bytes
    revoked: bool = False


class KeyRegistry:
    def __init__(self, trusted_keys: list[TrustedKey]):
        self._keys: dict[str, TrustedKey] = {}
        for key in trusted_keys:
            if not key.key_id or not key.source_id:
                raise ValueError("KEY_ID_AND_SOURCE_REQUIRED")
            if len(key.public_key_bytes) != 32:
                raise ValueError("INVALID_ED25519_PUBLIC_KEY_LENGTH")
            if key.key_id in self._keys:
                raise ValueError("DUPLICATE_KEY_ID")
            self._keys[key.key_id] = key

    def resolve(self, key_id: str, source_id: str) -> TrustedKey | None:
        key = self._keys.get(key_id)
        if key is None or key.source_id != source_id or key.revoked:
            return None
        return key
