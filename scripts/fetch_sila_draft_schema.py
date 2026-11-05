"""Snapshot official public SiLA schemas for offline validation of the C01 draft."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
import requests

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/"exports/research/sila2-schema"
BASE="https://gitlab.com/SiLA2/sila_base/-/raw/master/schema/"


def main():
    DEST.mkdir(parents=True,exist_ok=True)
    pending=["FeatureDefinition.xsd"]
    seen={}
    while pending:
        name=pending.pop()
        if name in seen: continue
        if Path(name).name!=name or not name.endswith(".xsd"): raise ValueError("Unexpected schema include")
        response=requests.get(BASE+name,timeout=30)
        response.raise_for_status()
        data=response.content
        xml=ET.fromstring(data)
        for node in xml.findall("{http://www.w3.org/2001/XMLSchema}include"):
            pending.append(node.attrib["schemaLocation"])
        (DEST/name).write_bytes(data)
        seen[name]={"url":BASE+name,"sha256":hashlib.sha256(data).hexdigest()}
    (DEST/"sources.json").write_text(json.dumps({"retrieved_on":"2026-10-28","note":"Official schema snapshot; XSD validation is not device conformance testing", "files":seen},indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"downloaded":list(seen)}))


if __name__=="__main__": main()
