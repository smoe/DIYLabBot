"""Save station colors/visibility/camera while preserving native geometry bytes."""
from pathlib import Path
import json
import math
import xml.etree.ElementTree as ET
import zipfile
from persist_view import material


def persist(path,spec,geometry):
    path=Path(path)
    styles={b['id']:b['appearance'] for b in spec['bodies']}
    with zipfile.ZipFile(path) as archive: contents={n:archive.read(n) for n in archive.namelist()}
    xml=ET.fromstring(contents['Document.xml'])
    kinds={o.get('name'):o.get('type') for o in xml.findall('Objects/Object')}
    objects=xml.findall('ObjectData/Object')
    gui=ET.Element('Document',SchemaVersion='1',HasExpansion='1'); ET.SubElement(gui,'Expand')
    providers=ET.SubElement(gui,'ViewProviderData',Count=str(len(objects)))
    buffers={}; visible=[]
    for obj in objects:
        name=obj.get('name'); kind=kinds[name]
        entry=obj.find("Properties/Property[@name='SourceBody']/String")
        body=entry.get('value') if entry is not None else None
        provider=ET.SubElement(providers,'ViewProvider',name=name,expanded='0',treeRank='-1')
        props=ET.SubElement(provider,'Properties',Count='0',TransientCount='0')
        def prop(name,kind,tag,**attrs): ET.SubElement(ET.SubElement(props,'Property',name=name,type=kind,status='1'),tag,**attrs)
        prop('Visibility','App::PropertyBool','Bool',value=str(bool(body or kind=='App::Part' or name in {'Controller','ModelParameters'})).lower())
        prop('ShowInTree','App::PropertyBool','Bool',value='true')
        prop('ShowPlacement','App::PropertyBool','Bool',value='false')
        if kind=='App::Part': prop('OverrideMaterial','App::PropertyBool','Bool',value='false')
        if body:
            look=styles[body]; color=[int(look['color'][i:i+2],16) for i in (1,3,5)]
            filename='GuiMaterial_'+name; buffers[filename]=material(color,look['opacity'])
            prop('ShapeAppearance','App::PropertyMaterialList','MaterialList',file=filename,version='3')
            prop('Transparency','App::PropertyPercent','Integer',value=str(round(100*(1-look['opacity']))))
            prop('DisplayMode','App::PropertyEnumeration','Integer',value='0')
            prop('LineColor','App::PropertyColor','PropertyColor',value=str(0x222222ff))
            prop('LineWidth','App::PropertyFloatConstraint','Float',value='1')
            visible.append(body)
        props.set('Count',str(len(props)))
    bounds=[b['bbox'] for b in geometry]
    lo=[min(b['min'][i] for b in bounds) for i in range(3)]; hi=[max(b['max'][i] for b in bounds) for i in range(3)]
    center=[(a+b)/2 for a,b in zip(lo,hi)]; radius=math.dist(lo,hi)/2; distance=max(200,radius*3)
    position=[c+d*distance/math.sqrt(3) for c,d in zip(center,[1,-1,1])]
    camera=('OrthographicCamera {\n viewportMapping ADJUST_CAMERA\n position %s\n orientation 0.74290609 0.30772209 0.59447283 1.2171158\n nearDistance 0.1\n farDistance %s\n aspectRatio 1\n focalDistance %s\n height %s\n}\n')%(' '.join(map(str,position)),distance+radius*3,distance,radius*2.5)
    ET.SubElement(gui,'Camera',settings=camera); ET.indent(gui)
    tmp=path.with_suffix('.presentation-tmp')
    if tmp.exists(): raise FileExistsError(tmp)
    try:
        with zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,data in contents.items():
                if name!='GuiDocument.xml' and not name.startswith('GuiMaterial_'): archive.writestr(name,data)
            archive.writestr('GuiDocument.xml',ET.tostring(gui,encoding='utf-8',xml_declaration=True))
            for name,data in buffers.items(): archive.writestr(name,data)
        with zipfile.ZipFile(tmp) as archive:
            for name,data in contents.items():
                if name!='GuiDocument.xml' and not name.startswith('GuiMaterial_'):
                    if archive.read(name)!=data: raise AssertionError('Geometry bytes changed')
        tmp.replace(path)
    finally:
        if tmp.exists(): tmp.unlink()
    if set(visible)!=set(styles): raise AssertionError('Missing presentation bodies')
    return {'passed':True,'visible_final_bodies':len(visible),'geometry_bytes_unchanged':True,'gui_render_checked':False,'method':'Saved native presentation metadata; no GUI process'}
