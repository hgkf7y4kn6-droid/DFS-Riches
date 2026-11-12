import json

from scripts import bump_version as bv


def test_versions_agree_across_app_and_package_files():
    app = json.loads(bv.APP_JSON.read_text())["expo"]["version"]
    pkg = json.loads(bv.PACKAGE_JSON.read_text())["version"]
    lock = json.loads(bv.LOCK_JSON.read_text())
    assert app == pkg == lock["version"] == lock["packages"][""]["version"]


def test_next_version_counts_up_the_third_number():
    assert bv.next_version("1.0.0") == "1.0.1"
    assert bv.next_version("1.2.9") == "1.2.10"
