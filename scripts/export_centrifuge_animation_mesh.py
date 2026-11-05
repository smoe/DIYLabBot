"""Read checked native CF01 solids into a lightweight, source-bound animation mesh."""
import json
import sys
from pathlib import Path
import FreeCAD as App
import MeshPart
import centrifuge_model as model
sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion


def main():
    context=json.loads((model.ROOT/'tmp/cf01-animation-context.json').read_text()); out=Path(context['out'])
    spec=model.load();p=model.parameters(spec); source=model.expanded(spec,p); meta={b['id']:b for b in source['bodies']}
    doc=App.openDocument(str(Path(context['cad'])/'Centrifuge_CF01.FCStd')); result=[]
    for obj in doc.Objects:
        if 'SourceBody' not in obj.PropertiesList:continue
        mesh=MeshPart.meshFromShape(Shape=motion.world_shape(obj),LinearDeflection=1.5,AngularDeflection=0.35,Relative=False)
        vertices,triangles=mesh.Topology
        result.append({'id':obj.SourceBody,'group':obj.RigidLink,'role':meta[obj.SourceBody]['role'],
            'opacity':meta[obj.SourceBody]['appearance']['opacity'],
            'v':[[round(n,1) for n in v] for v in vertices],'f':[list(t) for t in triangles]})
    data={'source_sha256':model.digest(model.SOURCE),'bodies':result,'joints':source['joints'],
          'pickup':dict(zip(['bottom','axis'],model.pocket(spec,p,1))),'parameters':p}
    (out/'animation-mesh.json').write_text(json.dumps(data,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'bodies':len(result),'triangles':sum(len(b['f']) for b in result),'bytes':(out/'animation-mesh.json').stat().st_size}),flush=True)
    App.closeDocument(doc.Name)


if __name__=='__main__':
    import export_centrifuge_animation_mesh as backend
    backend.main()
