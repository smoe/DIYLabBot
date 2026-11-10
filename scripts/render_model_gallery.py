"""Curate GitHub model previews, source links and verifiable image provenance.

Uses existing checked local builds. No CAD geometry is a new leading source.
--check works on a fresh checkout, without either CAD application installed.
"""
import argparse
import tool_paths
from datetime import datetime
import hashlib
import html
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import robot_spec as robot

ROOT=robot.ROOT
DIRECTORY=ROOT/'docs/models'
CATALOG=DIRECTORY/'catalog.json'
PROVENANCE=DIRECTORY/'provenance.json'
WORK=ROOT/'tmp/model-gallery'

# These exact, versioned formats describe transport contracts rather than new
# geometry. Their referenced station models remain subject to image coverage.
# Unknown formats and future revisions retain the default image requirement.
NON_GEOMETRIC_SHARED_FORMATS=frozenset({'solidcraftbot.cf01-sila2/1'})


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rel(path):return str(Path(path).resolve().relative_to(ROOT))
def project(path):
    p=Path(str(path).replace('\\','/'))
    p=(ROOT/p).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('Gallery input outside project')
    return p


def checked_case(family,case='default'):
    path=ROOT/'cad'/family/'shared-build-report.json';report=read(path)
    if not report['passed']:raise ValueError('Failed build: '+family)
    source=ROOT/'model'/(family+'.shared.json');equivalence=None
    if report['source_sha256']!=sha(source):
        if family!='tip-collector-t01':raise ValueError('Stale source: '+family)
        # T01's redundancy cleanup changed metadata only, not one CAD command.
        import tip_collector_model as model
        files=report['cases'][0]['files']
        old_path=project(files['commands']) if 'commands' in files else ROOT/'exports/generated'/project(files['solidcraft']).parent.name/'default.commands.json'
        def geometry(commands):return [c for c in commands if c['command']!='document.metadata.set']
        current=geometry(model.solidcraft_commands(model.load(),model.parameters(model.load())))
        if current!=geometry(read(old_path)['commands']):raise ValueError('T01 geometry changed; rebuild first')
        equivalence={'method':'Exact equality of all CAD commands except document metadata',
                     'old_commands':rel(old_path),'old_commands_sha256':sha(old_path),
                     'geometry_commands_sha256':hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()}
    item=next(c for c in report['cases'] if c['id']==case)
    model=project(item['files']['solidcraft'])
    if sha(model)!=item['artifact_sha256']['solidcraft']:raise ValueError('Changed CAD artifact: '+str(model))
    return model,{'build_report':rel(path),'build_report_sha256':sha(path),'build_passed':True,
                  'build_source_sha256':report['source_sha256'],'source_equivalence':equivalence},item


def input_for(entry):
    render=entry['render'];kind=render['kind'];commands=[];evidence={}
    if kind=='synthetic-lab':
        path=ROOT/'cad/synthetic-lab-scene/shared-build-report.json';report=read(path)
        if not report['passed']:raise ValueError('Checked five-device scene required')
        for source in entry['sources']:
            if report['source_files_sha256'].get(source)!=sha(ROOT/source):raise ValueError('Synthetic lab source changed: '+source)
        snapshot=next(s for s in report['snapshots'] if s['id']==render['phase'])
        model=project(snapshot['files']['solidcraft']);image=project(report['renders'][render['view']])
        if sha(model)!=snapshot['artifact_sha256']['solidcraft'] or sha(image)!=report['render_sha256'][render['view']]:
            raise ValueError('Changed synthetic lab model or render')
        return model,commands,image,{'build_report':rel(path),'build_report_sha256':sha(path),'build_passed':True,
                                    'phase':render['phase'],'representation':'Native source-referenced five-device scene on the unchanged reference bench'}
    if kind in ['case','room']:
        family=render.get('family','lab-room-l01');model,evidence,case=checked_case(family,render.get('case','default'))
        if kind=='room' and render['scope']!='all':
            import lab_room_model as room
            import room_geometry_model as environment
            spec=room.load();p=room.parameters(spec);all_names=[b['id'] for b in room.expanded(spec,p)['bodies']]
            if render['scope']=='geometry':visible={b['id'] for b in environment.expanded(spec['_geometry'],p)['bodies']}
            else:
                instance=next(i for i in spec['_furnishings']['instances'] if i['id']==render['instance'])
                if instance['type']!=render['type']:raise ValueError('Wrong furniture example')
                prefix=instance['id'];visible={n for n in all_names if n==prefix or n.startswith(prefix+'_')}
                evidence['example_instance']=prefix;evidence['furniture_type']=instance['type']
            if not visible or not visible<=set(all_names):raise ValueError('Missing gallery projection bodies')
            commands=[{'command':'browser.visibility','params':{'items':[n for n in all_names if n not in visible],'visible':False}}]
            evidence['visible_bodies']=sorted(visible)
        return model,commands,None,evidence
    if kind=='robot':
        path=ROOT/'exports/generated/build-report.json';report=read(path)
        if not report['passed'] or report['spec_sha256']!=sha(ROOT/'model/robot.json'):raise ValueError('Rebuild current robot first')
        model=project(report['artifacts']['solidcraft'])
        if sha(model)!=report['artifact_sha256']['solidcraft']:raise ValueError('Changed robot CAD')
        return model,commands,None,{'build_report':rel(path),'build_report_sha256':sha(path),'build_passed':True}
    if kind=='state':
        path=ROOT/'cad'/render['family']/'shared-build-report.json';report=read(path)
        if not report['passed'] or report['source_sha256']!=sha(ROOT/entry['sources'][0]):raise ValueError('Rebuild mobile base first')
        state=next(s for s in report['states'] if s['id']==render['state']);model=project(state['solidcraft'])
        if not state['passed'] or sha(model)!=state['sha256']['solidcraft']:raise ValueError('Changed mobile model')
        return model,commands,None,{'build_report':rel(path),'build_report_sha256':sha(path),'build_passed':True,'state':state['id']}
    if kind=='checked-render':
        path=ROOT/'cad'/render['family']/'render-manifest.json';manifest=read(path);model=project(manifest['model'])
        if manifest['source_sha256']!=sha(ROOT/entry['sources'][0]) or sha(model)!=manifest['model_sha256']:raise ValueError('Stale checked render')
        view=next(v for v in manifest['views'] if v['id']==render['view']);image=path.parent/view['path']
        if sha(image)!=view['sha256']:raise ValueError('Changed checked render')
        review=manifest['visual_review']
        if not (review.get('passed') or review.get('reviewed')):raise ValueError('Original visual review missing')
        return model,commands,image,{'render_manifest':rel(path),'render_manifest_sha256':sha(path),'original_visual_review':review}
    if kind=='native':
        path=ROOT/'cad/centrifuge-cf01/solidcraft-pickup-build-report.json';report=read(path)
        if not report['passed'] or report['freecad_required']:raise ValueError('Checked independent CF01 build required')
        for source in entry['sources']:
            if report['source_files_sha256'].get(source)!=sha(ROOT/source):raise ValueError('Native CF01 source changed')
        snapshot=next(s for s in report['snapshots'] if s['phase']==render['phase']);model=project(snapshot['solidcraft'])
        if sha(model)!=report['artifact_sha256'][rel(model)]:raise ValueError('Changed native CF01 CAD')
        commands=[{'command':'browser.visibility','params':{'folder':'sketches','visible':False}}]
        if render['scope']=='rack':
            all_names=[n for b in report['body_manifest'] for n in b['names']]
            visible=[n for b in report['body_manifest'] if b['id'].startswith('Rack.') for n in b['names']]
            commands.append({'command':'browser.visibility','params':{'items':[n for n in all_names if n not in visible],'visible':False}})
            evidence['visible_bodies']=visible
        evidence.update(build_report=rel(path),build_report_sha256=sha(path),build_passed=True,
                        freecad_required=False,phase=render['phase'],cad_body_count=snapshot['body_count'])
        return model,commands,None,evidence
    if kind=='cycle':
        import tube_cam_cycle as cycle
        stem='tube-cam-h03-cycle-'+sha(ROOT/entry['sources'][0])[:12]
        reports=list((ROOT/'exports/generated').glob(stem+'*/animation-report.json'))
        if not reports:raise ValueError('Build checked H03 cycle first')
        compatible=[]
        for candidate in reports:
            data=read(candidate)
            if (data['passed'] and data['protocol_sha256']==sha(ROOT/entry['sources'][0])
                and all(sha(ROOT/source)==digest for source,digest in data['source_files_sha256'].items())):
                compatible.append(candidate)
        if not compatible:raise ValueError('No H03 cycle report matches the current sources')
        path=max(compatible,key=lambda p:p.stat().st_mtime);report=read(path)
        image=path.parent/'review-30.png'
        return None,commands,image,{'build_report':rel(path),'build_report_sha256':sha(path),'build_passed':True,
                                   'representation':'Browser view of checked source-derived geometry and cycle, at 30 s'}
    if kind=='bench':
        import synthetic_workspace as workspace
        bench=workspace.load()['bench'];shape=bench['operations'][0]['shape']
        params={'name':'ReferenceBench','body_name':'ReferenceBench','operation':'new',
                'corner':[robot.evaluate(v,{}) for v in shape['origin']],
                **dict(zip(['length','width','height'],[robot.evaluate(v,{}) for v in shape['size']]))}
        commands=[{'command':'solid.box','params':params},
                  {'command':'appearance.assign','params':{'bodies':['ReferenceBench'],**bench['bodies'][0]['appearance']}}]
        return None,commands,None,{'representation':'Native projection of the shared reference-surface recipe'}
    raise ValueError('Unknown renderer: '+kind)


def svg_document(title,content,width=1150,height=850):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img"><title>{html.escape(title)}</title><rect width="100%" height="100%" fill="#eef2f6"/><g font-family="sans-serif" fill="#203b50">{content}</g></svg>\n'


def diagram(entry):
    view=entry['render']['view'];text=lambda x,y,t,size=20:f'<text x="{x}" y="{y}" font-size="{size}">{html.escape(str(t))}</text>'
    if view=='integrated_workflow':
        from lab_workflow_sources import load
        definition=load();samples=definition['manifest']['samples'];count=len(samples)
        nd=definition['stages']['nanodrop']['profile']['parameters']['sample_volume_ul']
        qb=definition['stages']['qubit']['profile']['parameters']['sample_volume_ul']
        initial=next(s['initial_volume_ul'] for s in samples if s['initial_volume_ul'] is not None)
        number=lambda value:('%g'%value).replace('.',',')
        content=text(45,60,'CF01 → NanoDrop → Qubit 4',32)
        content+=text(45,105,'Schematischer Ablaufplan · ein Bestand · synthetische Eingaben',22)
        labels=[(str(count)+' Originale','Manifest / Rackplätze'),('CF01','beladen / Spin / zurück'),
                ('NanoDrop','Entnahme / Ergebnis'),('Qubit 4','Ansatz / Messung'),('Gesamtfreigabe','Rückgabe / Entsorgung')]
        for i,(title,caption) in enumerate(labels):
            x=35+i*222
            content+=f'<rect x="{x}" y="175" width="200" height="130" rx="12" fill="#d9e6ed" stroke="#496d83"/>'
            content+=text(x+12,215,title,22)+text(x+12,260,caption,14)
            if i<4:content+=text(x+202,250,'→',25)
        content+=text(45,385,'Eine Probe · ein Originalgefäß · derselbe Ursprungsplatz',25)
        content+=text(45,455,'Originalbestand: '+number(initial)+' µl → '+number(initial-nd)+' µl → '+number(initial-nd-qb)+' µl',26)
        content+=text(45,500,'Geplanter Beispielsaldo; unbekannte Anfangsmengen bleiben unbekannt.',20)
        standards=len(definition['stages']['qubit']['protocol']['assay']['standards'])
        content+=text(45,565,'Qubit: '+str(standards)+' Standards und '+str(count)+' serielle Probenansätze.',22)
        content+=text(45,610,'Ansatzgefäße besitzen eigene IDs und werden ausdrücklich entsorgt.',20)
        content+=text(45,710,'Quelle und Ablaufplan sind kein Mess- oder Funktionsnachweis.',22)
        content+=text(45,755,'Keine Netzwerk-, Hardware- oder Roboterbahnausführung.',20)
        return svg_document(entry['title'],content),{'representation':'Source-derived synthetic workflow plan; not execution evidence',
            'workflow_executed':False,'original_vessels':count,'network_executed':False,'hardware_executed':False}
    if view=='unbounded':
        import synthetic_workspace as workspace
        env=workspace.load()['environment'];assert env['extent']=='unbounded' and env['geometry']=='none'
        content=text(55,70,'Unbegrenzte synthetische Umgebung',32)+text(425,390,'∞',230)
        content+=text(290,510,'Keine Raumhülle · keine künstliche Grenze',25)+text(390,560,env['world_frame'],20)
        content+=text(180,725,'Symbolische Ansicht der Quelle; kein begrenzter Raumkörper.',22)
        return svg_document(entry['title'],content),{'representation':'Source-derived concept diagram; no finite room geometry'}
    if view=='batch':
        from cf01_rack_batch import Runner
        report=Runner().run();assert report['passed'] and report['order_restored'];count=len(report['initial_order'])
        labels=[('Rack bereit',str(count)+' Proben'),('Beladen','abstrahierte Übergaben'),('Zentrifugieren','Spin und Bremse bestätigt'),('Rückgabe','ursprüngliche Rackplätze'),('Rack vollständig','Identität / Reihenfolge erhalten')]
        content=text(45,60,'Rack → CF01 → Rack',32)+text(45,105,'Lokaler Mock-Lauf · keine ausgeführten Roboterbahnen',22)
        for i,(a,b) in enumerate(labels):
            x=35+i*222;content+=f'<rect x="{x}" y="175" width="200" height="130" rx="12" fill="#d9e6ed" stroke="#496d83"/>'
            content+=text(x+12,215,a,22)+text(x+12,260,b,12)
            if i<4:content+=text(x+202,250,'→',25)
        for k,label in [(0,'Anfang'),(1,'Ende')]:
            content+=text(85+k*550,390,label,25)
            for i,id in enumerate(report['initial_order'] if k==0 else report['final_order']):
                x=85+k*550+(i%4)*108;y=420+(i//4)*58
                content+=f'<rect x="{x}" y="{y}" width="98" height="46" rx="5" fill="#dbe9df" stroke="#6b927c"/>'+text(x+8,y+29,id,15)
        content+=text(45,700,'Das Rack ist bereits angeliefert; der Transporter wird nicht dargestellt.',20)
        return svg_document(entry['title'],content),{'representation':'Source-derived local mock protocol diagram','batch_passed':True,'original_order_restored':True,'network_executed':False,'hardware_executed':False}
    if view=='layout':
        import lab_room_model as room
        import lab_layout_model as layout
        spec=room.load();p=room.parameters(spec);source=room.expanded(spec,p);layout_spec=layout.load(validate_builds=False);lp=layout.parameters(layout_spec)
        operations=[op for op in source['operations'] if op['action']=='create'];floor=next(op['shape'] for op in operations if op['body']=='Floor')
        def points(shape):
            shape=room.numeric_shape(shape,p)
            if shape['kind']=='box':
                x,y,_=shape['origin'];w,h,_=shape['size'];return [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]
            return shape['points']
        boundary=points(floor);width=max(x for x,y in boundary);depth=max(y for x,y in boundary);scale=min(720/width,640/depth)
        def point(x,y):return (40+x*scale,135+(depth-y)*scale)
        def polygon(pts,fill):return '<polygon points="'+' '.join('%g,%g'%point(x,y) for x,y in pts)+f'" fill="{fill}" stroke="#7c909c" stroke-width="1.5"/>'
        content=text(40,55,'L01 · aktuelle Aufstellung',32)+text(40,95,'Vorläufiges Raummodell · schematische Gerätebezugspunkte',20)
        content+=polygon(boundary,'#f9fafb');worktops={b['id'] for b in source['bodies'] if b['role']=='work_surface'}
        for op in operations:
            if op['body'] in worktops:content+=polygon(points(op['shape']),'#d5e0e5')
        palette={'arm':'#2d6e94','centrifuge':'#ba873a','transporter':'#4c876b','tube_rack':'#826ba0','tip_collector':'#b86b50'}
        labels={'arm':'Laborarm','centrifuge':'Zentrifuge','transporter':'Transporter','tube_rack':'Rack','tip_collector':'Spitzenabwurf'}
        for i,item in enumerate(layout_spec['instances'],1):
            x,y,z=layout.xyz(item['xyz'],lp);sx,sy=point(x,y);color=palette[item['asset']]
            angle=math.radians(item['yaw_deg']);dx,dy=math.cos(angle),-math.sin(angle)
            ex,ey=sx+27*dx,sy+27*dy;bx,by=sx+19*dx,sy+19*dy
            content+=f'<path d="M {sx} {sy} L {ex} {ey}" stroke="{color}" stroke-width="2.5"/>'
            content+=f'<polygon points="{ex},{ey} {bx-4*dy},{by+4*dx} {bx+4*dy},{by-4*dx}" fill="{color}"/>'
            content+=f'<circle cx="{sx}" cy="{sy}" r="14" fill="{color}"/>'
            content+=f'<text x="{sx}" y="{sy+5}" text-anchor="middle" font-size="14" fill="white">{i}</text>'
            content+=f'<circle cx="815" cy="{170+i*53}" r="13" fill="{color}"/>'
            content+=f'<text x="815" y="{175+i*53}" text-anchor="middle" font-size="14" fill="white">{i}</text>'
            content+=text(840,175+i*53,item['id'],19)+text(840,196+i*53,labels[item['asset']]+' · Z '+str(round(z))+' mm',13)
        content+=text(40,830,'Symbole sind keine Bauraum- oder Kollisionshüllen. Ausrichtungspfeile folgen der Quelle.',16)
        return svg_document(entry['title'],content,height=865),{'representation':'Source-derived current floor/worktop outline and device-reference-point plan; not a full CAD assembly render','instances':len(layout_spec['instances'])}
    raise ValueError(view)


def render_entry(entry,cli):
    target=DIRECTORY/entry['image'];target.parent.mkdir(parents=True,exist_ok=True)
    record={'id':entry['id'],'image':entry['image'],'source_files_sha256':{s:sha(ROOT/s) for s in entry['sources']}}
    if entry['render']['kind']=='diagram':
        svg,evidence=diagram(entry);target.write_text(svg,encoding='utf-8');record.update(evidence)
    else:
        model,commands,image,evidence=input_for(entry);record.update(evidence)
        if model:record.update(native_model=rel(model),native_model_sha256=sha(model))
        if image:
            shutil.copyfile(image,target);record.update(reused_render=rel(image),reused_render_sha256=sha(image))
        else:
            script=WORK/(entry['id']+'.commands.json');script.write_text(json.dumps({'commands':commands},indent=2)+'\n')
            args=[cli,'snapshot']
            if commands:args.append(str(script))
            if model:args.extend(['--in',str(model)])
            args.extend(['--out',str(target),'--width','1000','--height','700','--view','iso','--no-grid','--no-axes'])
            run=subprocess.run(args,check=True,cwd=ROOT,capture_output=True,text=True)
            record.update(renderer_result=json.loads(run.stdout),commands=commands,command_line=args)
            if model and sha(model)!=record['native_model_sha256']:raise ValueError('Rendering modified CAD input')
    record.update(image_sha256=sha(target),bytes=target.stat().st_size,dependency_files_sha256=dependencies(entry))
    return record


def dependencies(entry):
    """Follow versioned data references, including furniture size bindings."""
    roots=list(entry['sources'])
    if entry['render']['kind']=='room':roots.append('model/lab-room-l01.shared.json')
    found={}
    def visit(value):
        if isinstance(value,dict):
            for field,digest_field in [('source','source_sha256'),('path','sha256'),('step','sha256')]:
                reference=value.get(field)
                if isinstance(reference,str) and reference.startswith(('model/','cad/vendor/')) and digest_field in value:
                    if sha(project(reference))!=value[digest_field]:raise ValueError('Pinned gallery dependency changed: '+reference)
            for item in value.values():visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
        elif isinstance(value,str) and value.startswith(('model/','cad/vendor/')):
            path=project(value)
            if path.is_file() and rel(path) not in found:
                found[rel(path)]=sha(path)
                if path.suffix=='.json':visit(read(path))
    for source in roots:visit(source)
    return found


def reusable(entry,record):
    path=DIRECTORY/entry['image']
    if record.get('image')!=entry['image'] or not path.exists() or sha(path)!=record['image_sha256']:return False
    if record['source_files_sha256']!={s:sha(ROOT/s) for s in entry['sources']}:return False
    if entry['render']['kind']=='diagram':
        content,_=diagram(entry)
        return hashlib.sha256(content.encode()).hexdigest()==record['image_sha256']
    model,commands,image,_=input_for(entry)
    if model and (rel(model)!=record.get('native_model') or sha(model)!=record.get('native_model_sha256')):return False
    if image:return sha(image)==record.get('reused_render_sha256')
    return commands==record.get('commands')


def portable_record(record):
    if 'command_line' in record:
        arguments=[]
        for argument in record['command_line'][1:]:
            path=Path(argument)
            arguments.append(rel(path) if path.is_absolute() and path.is_relative_to(ROOT) else argument)
        record['command_line']=['solidcraft-cli',*arguments]
    if 'renderer_result' in record:record['renderer_result']['path']=str(Path('docs/models')/record['image'])
    return record


def write_documentation():
    catalog=read(CATALOG);sections=[]
    for group in catalog['groups']:
        entries=[e for e in catalog['entries'] if e['group']==group['id']]
        section='\n<a id="'+group['id']+'"></a>\n\n## '+group['title']+'\n\n'+group['description']+'\n\n'
        def links(entry):
            sources=' · '.join('[Quelle'+(' '+str(i+1) if len(entry['sources'])>1 else '')+'](../../'+s+')' for i,s in enumerate(entry['sources']))
            return sources+' · [Details](../../'+entry['documentation']+')'
        if group['id'] in ['moeblierung','ausstattung','ablaeufe']:
            for entry in entries:
                section+='### '+entry['title']+'\n\n[!['+entry['title']+']('+entry['image']+')]('+entry['image']+')\n\n'+entry['caption']+'\n\n'+links(entry)+'\n\n'
        else:
            columns=min(3,len(entries));width=270 if columns==3 else 400
            section+='| '+' | '.join(['Modell']*columns)+' |\n| '+' | '.join(['---']*columns)+' |\n'
            for start in range(0,len(entries),columns):
                cells=[]
                for entry in entries[start:start+columns]:
                    image='<a href="'+entry['image']+'"><img src="'+entry['image']+'" alt="'+html.escape(entry['title'],quote=True)+'" width="'+str(width)+'"></a>'
                    cells.append('**'+entry['title']+'**<br>'+image+'<br>'+entry['caption']+'<br>'+links(entry))
                section+='| '+' | '.join(cells+['']*(columns-len(cells)))+' |\n'
        sections.append(section)
    template=(ROOT/'scripts/templates/model_gallery.md').read_text(encoding='utf-8')
    (DIRECTORY/'README.md').write_text(template.replace('__MODEL_GROUPS__','\n'.join(sections)),encoding='utf-8')


def required_model_sources():
    """Classify top-level shared sources; composition layers always need images."""
    expected={'model/robot.json'}
    for path in (ROOT/'model').glob('*.shared.json'):
        source=read(path)
        if not isinstance(source,dict) or source.get('format') not in NON_GEOMETRIC_SHARED_FORMATS:
            expected.add(str(path.relative_to(ROOT)))
    for directory in ['environments','furniture','furnishings','equipment']:
        expected|={str(p.relative_to(ROOT)) for p in (ROOT/'model'/directory).glob('*.json')}
    return expected


def check(require_review=True):
    catalog=read(CATALOG);provenance=read(PROVENANCE);records={r['id']:r for r in provenance['images']};covered=set()
    if len(records)!=len(provenance['images']):raise ValueError('Duplicate image identity')
    total=0;page=(DIRECTORY/'README.md').read_text(encoding='utf-8')
    for entry in catalog['entries']:
        record=records[entry['id']];path=DIRECTORY/entry['image']
        if record['image']!=entry['image'] or sha(path)!=record['image_sha256']:raise ValueError('Image changed: '+entry['id'])
        for source,digest in record['source_files_sha256'].items():
            if sha(ROOT/source)!=digest:raise ValueError('Source changed: '+source)
        for source,digest in record['dependency_files_sha256'].items():
            if sha(ROOT/source)!=digest:raise ValueError('Image dependency changed: '+source)
        if record['dependency_files_sha256']!=dependencies(entry):raise ValueError('Dependency graph changed: '+entry['id'])
        if set(record['source_files_sha256'])!=set(entry['sources']):raise ValueError('Source/image binding missing')
        covered.update(entry['sources']);total+=path.stat().st_size
        if path.suffix=='.png':
            data=path.read_bytes();assert data[:8]==b'\x89PNG\r\n\x1a\n';width,height=struct.unpack('>II',data[16:24]);assert width>=250 and height>=150
        else:
            svg=ET.parse(path).getroot();assert svg.tag=='{http://www.w3.org/2000/svg}svg'
            assert not any(e.tag.endswith('script') or e.tag.endswith('image') for e in svg.iter())
        if not (ROOT/entry['documentation']).is_file():raise ValueError('Broken documentation link')
        if entry['image'] not in page or any('../../'+s not in page for s in entry['sources']):raise ValueError('Model missing from gallery page')
    expected=required_model_sources()
    if expected-covered:raise ValueError('Model source without image: '+str(sorted(expected-covered)))
    if total>4_000_000:raise ValueError('Curated gallery exceeds 4 MB image budget')
    if require_review and not provenance.get('visual_review',{}).get('passed'):raise ValueError('Visual review pending')
    if provenance['catalog_sha256']!=sha(CATALOG):raise ValueError('Gallery catalog changed')
    print(json.dumps({'passed':True,'images':len(records),'covered_model_sources':len(expected),'image_bytes':total,'visual_reviewed':bool(provenance.get('visual_review',{}).get('passed'))}))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Reuse only previews whose image, sources, CAD inputs and view commands still match')
    tool_paths.add_tool_arguments(parser,freecad=False)
    args=parser.parse_args();tool_paths.resolve_tool_arguments(parser,args,required=not args.check)
    if args.check:check();return
    WORK.mkdir(parents=True,exist_ok=True);records=[]
    previous={r['id']:r for r in read(WORK/'progress.json')} if args.resume and (WORK/'progress.json').exists() else {}
    for entry in read(CATALOG)['entries']:
        cached=previous.get(entry['id'])
        if cached and reusable(entry,cached):
            cached['dependency_files_sha256']=dependencies(entry);records.append(cached)
        else:records.append(render_entry(entry,args.solidcraft_cli))
        records[-1]=portable_record(records[-1])
        print('Prepared '+entry['id'],flush=True)
        (WORK/'progress.json').write_text(json.dumps(records,indent=2)+'\n')
    provenance={'format':'solidcraftbot.curated-model-gallery/1','prepared_on':datetime.now(ZoneInfo('Europe/Berlin')).date().isoformat(),'catalog_sha256':sha(CATALOG),
                'render_generator':rel(Path(__file__)),'render_generator_sha256':sha(__file__),
                'solidcraft_version':subprocess.check_output([args.solidcraft_cli,'--version'],text=True).strip(),
                'images':records,'visual_review':{'passed':False},
                'limits':'Documentation views and explicitly labelled diagrams; no new hardware, manufacturing or full-path qualification. Historical README media provenance remains unchanged.'}
    PROVENANCE.write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    write_documentation()
    check(require_review=False)


if __name__=='__main__':main()
