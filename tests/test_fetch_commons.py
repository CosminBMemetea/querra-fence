"""tools/fetch_commons.py keeps only photos that are free to reuse, and names files safely."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import fetch_commons as fc  # noqa: E402


def test_free_licences_are_kept():
    for lic in ("CC BY-SA 2.0", "CC BY 4.0", "CC BY-SA 3.0", "CC0", "Public domain", "PD-self", "CC-BY-SA-3.0", "cc by-sa 4.0"):
        assert fc.FREE.match(lic), lic


def test_other_licences_are_refused():
    for lic in ("GFDL 1.2", "Copyrighted free use", "CC BY-NC 2.0", "CC BY-ND 4.0", "", "Fair use"):
        assert not fc.FREE.match(lic), lic


def test_file_names_are_safe():
    for title in ("File:Ohradník v Praze - Řepích/../x.jpg", "File:../../etc/passwd.jpg", "File:.hidden.png", "File:???.jpg"):
        name = fc.safe(title)
        assert name and "/" not in name and not name.startswith((".", "-")), (title, name)
