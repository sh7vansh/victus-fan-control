"""Compose this single app's catalog and icons for Flatpak bundle metadata.

flatpak build-bundle reads share/app-info, not just share/metainfo. Keeping
composition here makes the direct local build and SDK manifest behave alike.
"""

import copy
from datetime import datetime, timezone
import gzip
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

APP_ID = "io.github.sh7vansh.VictusFanControl"


def compose(prefix):
    prefix = Path(prefix)
    component = copy.deepcopy(ET.parse(prefix / "share/metainfo" / f"{APP_ID}.metainfo.xml").getroot())
    for tag in ("metadata_license",):
        element = component.find(tag)
        if element is not None:
            component.remove(element)
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
