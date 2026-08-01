"""Verified recovery-manifest creation and compensating restoration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from ..domain.models import RecoveryAction, RecoveryItem, RecoveryManifest
from ..ports.protocols import FileSystemPort
from ..services.redaction import redact_text
from .candidate import SwitchAsset


class RecoveryManager:
    def __init__(self, filesystem: FileSystemPort):
        self.fs = filesystem

    def create_manifest(
        self,
        transaction_id: str,
        backup_root: Path,
        assets: Iterable[SwitchAsset],
    ) -> RecoveryManifest:
        root = self.fs.resolve(backup_root)
        self.fs.mkdir(root)
        changed = [item for item in assets if item.action != "preserve"]
        required_bytes = sum(
            self.fs.size(item.target) if self.fs.exists(item.target) else 0
            for item in changed
        )
        if self.fs.free_bytes(root) < required_bytes:
            return RecoveryManifest(
                transaction_id,
                str(root),
                errors=["insufficient space for complete recovery backup"],
            )
        items: list[RecoveryItem] = []
        for index, asset in enumerate(changed):
            backup = _contained(root, Path("items") / f"{index:04d}")
            existed = self.fs.exists(asset.target) or self.fs.is_symlink(asset.target)
            digest = self.fs.digest(asset.target) if existed else None
            size = self.fs.size(asset.target) if existed else 0
            if existed:
                if self.fs.is_symlink(asset.target):
                    return RecoveryManifest(
                        transaction_id,
                        str(root),
                        items=items,
                        errors=[f"recovery source cannot be a symlink: {asset.target}"],
                    )
                self.fs.copy(asset.target, backup)
                if self.fs.digest(backup) != digest:
                    return RecoveryManifest(
                        transaction_id,
                        str(root),
                        items=items,
                        errors=[f"backup digest verification failed: {asset.target}"],
                    )
            items.append(
                RecoveryItem(
                    asset_type=asset.asset_type,
                    source=str(asset.target),
                    backup_path=str(backup),
                    restore_target=str(asset.target),
                    digest=digest,
                    size=size,
                    existed=existed,
                    complete=True,
                )
            )
        manifest = RecoveryManifest(
            transaction_id=transaction_id,
            backup_root=str(root),
            items=items,
            complete=True,
        )
        self.fs.write_text_atomic(
            root / "recovery-manifest.json",
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
        )
        return manifest

    def compensate(
        self,
        manifest: RecoveryManifest,
        written_targets: Iterable[str],
        fault: Callable[[str], None] | None = None,
    ) -> list[RecoveryAction]:
        by_target = {item.restore_target: item for item in manifest.items}
        actions: list[RecoveryAction] = []
        for index, target_value in enumerate(reversed(list(written_targets))):
            target = Path(target_value)
            item = by_target.get(target_value)
            if item is None:
                actions.append(
                    RecoveryAction(
                        target_value,
                        "unknown",
                        None,
                        self.fs.digest(target),
                        "failed",
                        "target is missing from recovery manifest",
                    )
                )
                continue
            try:
                if fault is not None:
                    fault(f"recovery:{index}")
                if self.fs.exists(target) or self.fs.is_symlink(target):
                    self.fs.remove(target)
                if item.existed:
                    backup = Path(item.backup_path)
                    if not self.fs.exists(backup):
                        raise ValueError(f"recovery backup is missing: {backup}")
                    self.fs.copy(backup, target)
                restored_digest = self.fs.digest(target)
                if restored_digest != item.digest:
                    raise ValueError(
                        f"restored digest mismatch: {restored_digest} != {item.digest}"
                    )
                actions.append(
                    RecoveryAction(
                        target_value,
                        "restore" if item.existed else "remove_created",
                        item.digest,
                        restored_digest,
                        "restored",
                    )
                )
            except Exception as exc:
                actions.append(
                    RecoveryAction(
                        target_value,
                        "restore" if item.existed else "remove_created",
                        item.digest,
                        self.fs.digest(target),
                        "failed",
                        redact_text(f"{type(exc).__name__}: {exc}"),
                    )
                )
        return actions


def _contained(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"backup path escapes root: {relative}")
    target = root / relative
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ValueError(f"backup path escapes root: {target}") from exc
    return target
