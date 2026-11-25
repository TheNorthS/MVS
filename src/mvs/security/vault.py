"""认证加密的本地凭证；可用环境主密钥或系统钥匙串托管密钥。"""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class Vault:
    def __init__(self, root: Path) -> None:
        key = os.environ.get("MVS_VAULT_KEY")
        backend = os.environ.get("MVS_VAULT_BACKEND", "file")
        if key is None and backend == "keyring":
            import keyring

            identity = str(root.resolve())
            key = keyring.get_password("mvs-vault", identity)
            if key is None:
                key = Fernet.generate_key().decode()
                keyring.set_password("mvs-vault", identity, key)
        elif key is None:
            path = root / "vault.key"
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                key = path.read_text(encoding="ascii")
            else:
                key = Fernet.generate_key().decode()
                with os.fdopen(fd, "w", encoding="ascii") as file:
                    file.write(key)
        self.cipher = Fernet(key.encode())

    def seal(self, value: dict) -> dict:
        return {
            "$encrypted": self.cipher.encrypt(
                json.dumps(value, ensure_ascii=False).encode()
            ).decode()
        }

    def open(self, value: dict) -> dict:
        if "$encrypted" not in value:
            return value  # 首次迁移旧版明文状态。
        try:
            return json.loads(self.cipher.decrypt(value["$encrypted"].encode()))
        except (InvalidToken, ValueError):
            raise ValueError("凭证解密失败，主密钥缺失或不匹配") from None

    def encode_state(self, state: dict) -> str:
        copied = dict(state)
        copied["secrets"] = self.seal(state["secrets"])
        return json.dumps(copied, ensure_ascii=False)

    def decode_state(self, raw: str) -> dict:
        value = json.loads(raw)
        value["secrets"] = self.open(value["secrets"])
        return value
