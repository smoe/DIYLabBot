"""Bind checked CAD meshes and the shared timeline into the interactive animation."""
import json
from pathlib import Path
import centrifuge_model as model
import centrifuge_protocol as protocol


def main():
    context=json.loads((model.ROOT/'tmp/cf01-animation-context.json').read_text());out=Path(context['out'])
    mesh=json.loads((out/'animation-mesh.json').read_text());timeline=json.loads((out/'timeline.json').read_text())
    assert mesh['source_sha256']==timeline['geometry_sha256']==model.digest(model.SOURCE)
    assert timeline['protocol_sha256']==model.digest(protocol.SOURCE)
    template=(model.ROOT/'scripts/templates/centrifuge_animation.html').read_text(encoding='utf-8')
    fragment=template.replace('__MESH__',json.dumps(mesh,separators=(',',':'))).replace('__TIMELINE__',json.dumps(timeline,separators=(',',':')))
    target=Path(context['renders'])/'cf01-robot-access.html';target.write_text(fragment,encoding='utf-8')
    assert target.stat().st_size<1_000_000
    print(json.dumps({'path':str(target),'bytes':target.stat().st_size}))


if __name__=='__main__':main()
