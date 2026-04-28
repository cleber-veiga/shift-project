"""
Matriz completa de tradução de path Firebird (Fase 7).

Estende test_firebird_path_translation.py com a tabela de >=14 combinacoes
exigidas pela Fase 7 — bundled hosts (incluindo case-insensitive e com
sufixo de dominio), hosts remotos (host.docker.internal, IPs, FQDN,
localhost, 127.0.0.1) e edge cases (path ja traduzido, path sem drive,
path vazio, tudo None).
"""

from __future__ import annotations

import pytest

from app.services.firebird_client import translate_host_path_to_container


@pytest.mark.parametrize(
    "host,path,expected",
    [
        # --- bundled hosts -> traduz ---
        (None, "D:\\X.FDB", "/firebird/data/X.FDB"),
        ("", "D:\\X.FDB", "/firebird/data/X.FDB"),
        ("firebird25", "D:\\Data\\X.FDB", "/firebird/data/Data/X.FDB"),
        ("FIREBIRD25", "D:\\X.FDB", "/firebird/data/X.FDB"),               # case insensitive
        ("firebird30", "C:/db/X.FDB", "/firebird/data/db/X.FDB"),
        ("firebird25.local", "D:\\X.FDB", "/firebird/data/X.FDB"),         # alias com dominio
        ("firebird30.shift-net", "E:\\Y.FDB", "/firebird/data/Y.FDB"),
        # --- hosts remotos -> preserva ---
        ("host.docker.internal", "D:\\X.FDB", "D:\\X.FDB"),
        ("192.168.1.50", "C:\\Sistemas\\X.FDB", "C:\\Sistemas\\X.FDB"),
        ("db.empresa.com", "/var/fb/X.FDB", "/var/fb/X.FDB"),
        ("localhost", "D:\\X.FDB", "D:\\X.FDB"),
        ("127.0.0.1", "D:\\X.FDB", "D:\\X.FDB"),
        # --- edge cases ---
        ("firebird25", "/firebird/data/X.FDB", "/firebird/data/X.FDB"),    # ja no formato
        ("firebird25", "relative.fdb", "relative.fdb"),                    # sem drive letter
        ("firebird25", "", ""),                                            # path vazio
        (None, None, None),                                                # tudo vazio
    ],
)
def test_path_translation_matrix(host, path, expected) -> None:
    assert translate_host_path_to_container(path, host) == expected


# ---------------------------------------------------------------------------
# FIREBIRD_HOST_MOUNT_ROOT — strip do prefixo do mount, convencao C:\Shift\Data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mount_root,path,expected",
    [
        # Convencao Windows: C:\Shift\Data como mount root.
        (r"C:\Shift\Data", r"C:\Shift\Data\PALACIO.FDB", "/firebird/data/PALACIO.FDB"),
        (r"C:\Shift\Data", r"C:\Shift\Data\sub\X.FDB", "/firebird/data/sub/X.FDB"),
        # Case-insensitive (Windows e case-insensitive em paths).
        (r"C:\Shift\Data", r"c:\shift\data\X.FDB", "/firebird/data/X.FDB"),
        # Forward slashes — equivalentes a backslash em Windows.
        ("C:/Shift/Data", "C:/Shift/Data/X.FDB", "/firebird/data/X.FDB"),
        # Convencao Linux: /opt/shift/data.
        ("/opt/shift/data", "/opt/shift/data/X.FDB", "/firebird/data/X.FDB"),
        ("/opt/shift/data", "/opt/shift/data/sub/Y.FDB", "/firebird/data/sub/Y.FDB"),
        # Path FORA do mount root cai no fallback drive-letter.
        (r"C:\Shift\Data", r"D:\Outro\X.FDB", "/firebird/data/Outro/X.FDB"),
        # Mount root em si (sem arquivo) -> /firebird/data.
        (r"C:\Shift\Data", r"C:\Shift\Data", "/firebird/data"),
    ],
)
def test_path_translation_with_mount_root(
    monkeypatch: pytest.MonkeyPatch, mount_root: str, path: str, expected: str
) -> None:
    monkeypatch.setenv("FIREBIRD_HOST_MOUNT_ROOT", mount_root)
    assert translate_host_path_to_container(path, "firebird30") == expected


def test_mount_root_unset_falls_back_to_drive_letter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem FIREBIRD_HOST_MOUNT_ROOT, comportamento e o do drive-letter strip."""
    monkeypatch.delenv("FIREBIRD_HOST_MOUNT_ROOT", raising=False)
    assert (
        translate_host_path_to_container(r"C:\Shift\Data\X.FDB", "firebird30")
        == "/firebird/data/Shift/Data/X.FDB"
    )


def test_mount_root_does_not_affect_remote_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mount root so vale para hosts bundled — remoto preserva path."""
    monkeypatch.setenv("FIREBIRD_HOST_MOUNT_ROOT", r"C:\Shift\Data")
    assert (
        translate_host_path_to_container(r"C:\Shift\Data\X.FDB", "host.docker.internal")
        == r"C:\Shift\Data\X.FDB"
    )
