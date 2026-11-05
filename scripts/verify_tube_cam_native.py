"""Probe native SolidCraft cam and jaw links against the common H03 motion law."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import tube_cam_model as model


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',default=None)
    args=parser.parse_args();spec=model.load();folder=model.ROOT/'cad'/spec['family']
    report=json.loads((folder/'shared-build-report.json').read_text(encoding='utf-8'))
    if not report['passed'] or report['source_sha256']!=model.digest(model.SOURCE):
        raise ValueError('Rebuild and validate the current H03 source first')
    checks=[]
    for case in report['cases']:
        if args.case and case['id']!=args.case:continue
        print('Native cam/link checks: '+case['id'],flush=True)
        if model.digest(model.ROOT/case['files']['solidcraft'])!=case['artifact_sha256']['solidcraft']:
            raise ValueError('Native model differs from its build report: '+case['id'])
        p=model.parameters(spec,case['overrides'])
        refs=[{'id':'angle_'+str(a),'joint_values':model.values_at(spec,p,a)} for a in [0,30,75,130,165,195,200,210,220,260,290,320,360]]
        refs += [{'id':name,'joint_values':model.pose(spec,p,name)} for name in ['carried','release_pull','release_twist','return_open','returned']]
        commands=[]
        for ref in refs:
            commands+=model.drive_commands(spec,p,ref['joint_values'])
            commands += [{'command':'joint.solve','params':{}},{'command':'joint.list','params':{}}]
        script=folder/(case['id']+'-native-probes.commands.json');raw=folder/(case['id']+'-native-probes.raw.json')
        script.write_text(json.dumps({'commands':commands},indent=2)+'\n',encoding='utf-8')
        subprocess.run([shutil.which('solidcraft-cli'),'run',str(script),'--in',str(model.ROOT/case['files']['solidcraft']),
                        '--results','--json-out',str(raw),'--quiet'],check=True,cwd=model.ROOT)
        snapshots=[r for r in json.loads(raw.read_text(encoding='utf-8')) if isinstance(r,dict) and 'joints' in r and 'links' in r]
        if len(snapshots)!=len(refs):raise AssertionError('Native joint snapshot count')
        for ref,snapshot in zip(refs,snapshots):
            by_name={j['name']:j for j in snapshot['joints']};errors=[]
            for name,expected in ref['joint_values'].items():
                actual=by_name[name]['values'][0]
                if isinstance(actual,dict):actual=actual['value']
                tolerance=0.08 if name.startswith(('Pusher','ClosingFollower')) else 1e-5
                errors.append({'joint':name,'expected':expected,'actual':actual,'error':abs(actual-expected),
                               'unit':'deg' if name.startswith(('CamAngle','BoltTurn')) else 'mm','passed':abs(actual-expected)<=tolerance})
            checks.append({'case':case['id'],'pose':ref['id'],'passed':all(e['passed'] for e in errors) and not snapshot.get('conflicts') and not snapshot.get('errors'),
                           'joint_checks':errors,'native_links':len(snapshot['links']),
                           'conflicts':snapshot.get('conflicts',[]),'errors':snapshot.get('errors',[])})
    result={'passed':bool(checks) and all(c['passed'] for c in checks),'source_sha256':model.digest(model.SOURCE),
            'native_models_sha256':{c['files']['solidcraft']:model.digest(model.ROOT/c['files']['solidcraft']) for c in report['cases']},
            'checks':checks,'verifier_sha256':model.digest(__file__),
            'scope':'Native geometric cam links and linear wedge/jaw links; cam-table tolerance 0.08 mm, not a physical precision claim'}
    (folder/'native-coupling-checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    failed=[{'case':c['case'],'pose':c['pose'],'joints':[e for e in c['joint_checks'] if not e['passed']],
             'conflicts':c['conflicts'],'errors':c['errors']} for c in checks if not c['passed']]
    print(json.dumps({'passed':result['passed'],'poses':len(checks),'failed':failed},indent=2),flush=True)
    if not result['passed']:raise AssertionError('Native H03 coupling mismatch')


if __name__=='__main__':main()
