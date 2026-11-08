"""Write native FreeCAD presentation metadata without loading Qt or FreeCADGui.

The XML properties and one-material binary format are taken from FreeCAD 27.1
saved documents. Geometry entries are copied byte-for-byte. A normal FreeCAD
GUI check remains separate from this structural verification.
"""
from pathlib import Path
import json
import math
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import robot_spec as model


def rgba(color):
    r,g,b=color
    return (r<<24)|(g<<16)|(b<<8)|255


def material(color,opacity):
    # Native PropertyMaterialList v3: one material, four RGBA colours,
    # shininess, transparency, and three empty string lengths.
    return struct.pack("<5I2f3I",1,0x555555ff,rgba(color),0x888888ff,0x000000ff,
                       0.9,1-opacity,0,0,0)


def persist(path,report_path):
    path=Path(path).resolve()
    if not path.is_relative_to((model.ROOT/"cad/generated").resolve()):
        raise ValueError("Only generated project documents may be prepared")
    spec=model.load()
    styles=model.appearances(spec)["appearances"]
    with zipfile.ZipFile(path) as archive:
        contents={n:archive.read(n) for n in archive.namelist()}
    document=ET.fromstring(contents["Document.xml"])
    kinds={o.get("name"):o.get("type") for o in document.findall("Objects/Object")}
    objects={o.get("name"):o for o in document.findall("ObjectData/Object")}
    def value(obj,name):
        prop=obj.find("Properties/Property[@name='%s']/String"%name)
        return prop.get("value") if prop is not None else None
    if value(objects["Controller"],"SpecSHA256")!=model.digest(model.SPEC):
        raise ValueError("The FreeCAD file belongs to another source revision")
    gui=ET.Element("Document",SchemaVersion="1",HasExpansion="1")
    ET.SubElement(gui,"Expand")
    providers=ET.SubElement(gui,"ViewProviderData",Count=str(len(objects)))
    buffers={}; letters=[]; visible_bodies=[]
    for name,obj in objects.items():
        body=value(obj,"SourceBody"); link=value(obj,"RigidLink")
        kind=kinds[name]
        provider=ET.SubElement(providers,"ViewProvider",name=name,expanded="0",treeRank="-1")
        properties=ET.SubElement(provider,"Properties",Count="0",TransientCount="0")
        def prop(name,kind,tag,**attributes):
            p=ET.SubElement(properties,"Property",name=name,type=kind,status="1")
            ET.SubElement(p,tag,**attributes)
        visible=bool(body or kind=="App::Part" or name in {"Controller","ModelParameters"})
        prop("Visibility","App::PropertyBool","Bool",value=str(visible).lower())
        prop("ShowInTree","App::PropertyBool","Bool",value="true")
        prop("ShowPlacement","App::PropertyBool","Bool",value="false")
        if kind=="App::Part":
            prop("OverrideMaterial","App::PropertyBool","Bool",value="false")
        if body:
            look=styles["bodies"].get(body) or styles["components"][link]
            color,opacity=look["color"],look["opacity"]
            filename="GuiMaterial_"+name
            buffers[filename]=material(color,opacity)
            prop("ShapeAppearance","App::PropertyMaterialList","MaterialList",file=filename,version="3")
            prop("Transparency","App::PropertyPercent","Integer",value=str(round(100*(1-opacity))))
            prop("DisplayMode","App::PropertyEnumeration","Integer",value="0")
            prop("LineColor","App::PropertyColor","PropertyColor",value=str(0x222222ff))
            prop("LineWidth","App::PropertyFloatConstraint","Float",value="1")
            visible_bodies.append(body)
            if value(obj,"ModelRole")=="marking":letters.append(body)
        properties.set("Count",str(len(properties)))
    measurements=json.loads((Path(report_path).parent/"solidcraft-measurements.json").read_text(encoding="utf-8"))
    bounds=[b["bbox"] for b in measurements["bodies"]]
    lo=[min(b["min"][i] for b in bounds) for i in range(3)]
    hi=[max(b["max"][i] for b in bounds) for i in range(3)]
    centre=[(a+b)/2 for a,b in zip(lo,hi)]
    radius=math.sqrt(sum((a-b)**2 for a,b in zip(lo,hi)))/2
    distance=max(200,radius*3)
    # FreeCAD's standard axonometric orientation, looking from +X,-Y,+Z.
    camera_position=[c+d*distance/math.sqrt(3) for c,d in zip(centre,[1,-1,1])]
    camera=("OrthographicCamera {\n viewportMapping ADJUST_CAMERA\n position %s\n"
            " orientation 0.74290609 0.30772209 0.59447283 1.2171158\n"
            " nearDistance 0.1\n farDistance %s\n aspectRatio 1\n focalDistance %s\n height %s\n}\n")%(
                " ".join(str(v) for v in camera_position),distance+radius*3,distance,radius*2.5)
    ET.SubElement(gui,"Camera",settings=camera)
    ET.indent(gui)
    xml=ET.tostring(gui,encoding="utf-8",xml_declaration=True)
    temp=path.with_suffix(".presentation-tmp")
    if temp.exists():raise FileExistsError(temp)
    try:
        with zipfile.ZipFile(temp,"w",compression=zipfile.ZIP_DEFLATED) as archive:
            for name,data in contents.items():
                if name=="GuiDocument.xml" or name.startswith("GuiMaterial_"):continue
                archive.writestr(name,data)
            archive.writestr("GuiDocument.xml",xml)
            for name,data in buffers.items():archive.writestr(name,data)
        with zipfile.ZipFile(temp) as archive:
            for name,data in contents.items():
                if name!="GuiDocument.xml" and not name.startswith("GuiMaterial_"):
                    if archive.read(name)!=data:raise AssertionError("Geometry changed: "+name)
            ET.fromstring(archive.read("GuiDocument.xml"))
        temp.replace(path)
    finally:
        if temp.exists():temp.unlink()
    expected={op["body"] for link in model.expanded(spec)["links"] for op in link["recipe"] if op["action"]=="create"}
    result={"spec_sha256":model.digest(model.SPEC),"model":str(path.relative_to(model.ROOT)).replace("\\","/"),
            "method":"Native FCStd presentation metadata; no Qt or FreeCADGui process",
            "gui_document_saved":True,"final_bodies":len(visible_bodies),"letters":letters,
            "geometry_entries_unchanged":True,"visual_render_checked":False,
            "passed":set(visible_bodies)==expected and len(letters)==3}
    Path(report_path).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    if not result["passed"]:raise AssertionError("Missing bodies or lettering")
    print("FreeCAD presentation saved without a GUI process: %d bodies, three UMR letters"%len(visible_bodies))


if __name__=="__main__":persist(*sys.argv[1:])
