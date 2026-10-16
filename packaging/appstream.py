"""Compose the catalog and icons embedded in Flatpak bundles."""

import argparse
from datetime import datetime, timezone
import gzip
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from project import APP_ID


def compose_mirrored(prefix, base_url):
    """Use AppStream's full composer for repositories that host their media."""
    prefix = Path(prefix).resolve()
    # The lightweight local catalog must not coexist with the mirrored one.
    (prefix / "share/app-info/xmls" / f"{APP_ID}.xml.gz").unlink(missing_ok=True)
    subprocess.run([
        "appstreamcli", "compose", "--prefix=/", "--origin=flatpak",
        f"--result-root={prefix}", f"--data-dir={prefix}/share/app-info/xmls",
        f"--icons-dir={prefix}/share/app-info/icons/flatpak",
        f"--media-dir={prefix}/share/app-info/media", f"--media-baseurl={base_url}",
        "--no-partial-urls", str(prefix),
    ], check=True)
    (prefix / "share/app-info/xmls/flatpak.xml.gz").replace(
        prefix / "share/app-info/xmls" / f"{APP_ID}.xml.gz")


def compose(prefix):
    prefix = Path(prefix)
    component = ET.parse(prefix / "share/metainfo" / f"{APP_ID}.metainfo.xml").getroot()
    license_element = component.find("metadata_license")
    if license_element is not None:
        component.remove(license_element)
    developer = component.findtext("developer/name")
    if developer:
        ET.SubElement(component, "developer_name").text = developer
    for release in component.findall("releases/release"):
        date = release.attrib.pop("date", None)
        if date:
            release.set("timestamp", str(int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())))
        release.set("type", release.get("type", "stable"))
    for size in (64, 128):
        icon_name = f"{APP_ID}.png"
        icon = ET.SubElement(component, "icon", type="cached", width=str(size), height=str(size))
        icon.text = icon_name
        destination = prefix / "share/app-info/icons/flatpak" / f"{size}x{size}" / icon_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prefix / "share/icons/hicolor" / f"{size}x{size}/apps" / icon_name, destination)
    catalog = ET.Element("components", version="1.0", origin="flatpak")
    catalog.append(component)
    ET.indent(catalog, space="  ")
    xml = ET.tostring(catalog, encoding="utf-8", xml_declaration=True)
    target = prefix / "share/app-info/xmls" / f"{APP_ID}.xml.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.compress(xml, mtime=0))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix", type=Path)
    parser.add_argument("--media-baseurl", required=True)
    args = parser.parse_args()
    compose_mirrored(args.prefix, args.media_baseurl)
