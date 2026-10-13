from pathlib import Path
import subprocess
import sys
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_production_compose_has_persistent_data_and_private_redis():
    configuration = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = configuration["services"]
    assert "redis" in services, "Persistent FSM requires Redis"
    assert not services["redis"].get("ports")
    assert "--appendonly" in str(services["redis"]["command"])
    assert ".:/app" not in services["bot"]["volumes"]
    assert services["bot"].get("read_only") is True
    assert any("/app/data" in str(item) for item in services["bot"]["volumes"])


def test_container_installs_hashed_lock_and_runs_as_non_root():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "--require-hashes" in dockerfile
    assert "requirements.lock" in dockerfile
    assert "USER " in dockerfile
    assert "USER root" not in dockerfile


def test_docs_do_not_promise_a_nonexistent_setup_script():
    guide = (ROOT / "docs" / "CLIENT_ONBOARDING_UZ.md").read_text()
    assert "scripts/setup_new_client.py" not in guide
    assert "Amallar" in guide
    assert (ROOT / "README.md").is_file()
    assert (ROOT / "docs" / "DEPLOY_UZ.md").is_file()


def test_documented_dev_install_does_not_misapply_hash_mode(tmp_path):
    # An uninstalled wheel proves whether production hashes accidentally force
    # unhashed developer tools into pip's global hash-checking mode.
    wheel = tmp_path / "oymaoy_dev_probe-1.0-py3-none-any.whl"
    info = "oymaoy_dev_probe-1.0.dist-info/"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            info + "METADATA",
            "Metadata-Version: 2.1\nName: oymaoy-dev-probe\nVersion: 1.0\n",
        )
        archive.writestr(
            info + "WHEEL",
            "Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(info + "RECORD", "")
    source = (ROOT / "requirements-dev.txt").read_text()
    source = source.replace(
        "-r requirements.lock", "-r " + str(ROOT / "requirements.lock")
    )
    manifest = tmp_path / "dev.txt"
    manifest.write_text(source + "\noymaoy-dev-probe==1.0\n")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--no-index",
            "--find-links",
            str(tmp_path),
            "-r",
            str(manifest),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
