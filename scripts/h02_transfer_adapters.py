"""Portable instance operations for the referenced rack and occupied places."""
import types
import h02_rack_transfer as transfer
import h02_direct_pickup as local
import tube_carrier_model as portable


def extra_source(program,variant):
    parts=program.extra_parts(variant);source={'id':'H02RackParts','components':[{'id':'Rack','grounded':True},{'id':'Tube','grounded':False}],'bodies':[],'operations':[],'joints':[]}
    for b in parts:
        source['bodies'].append({'id':b['id'],'component':b['group'],'role':b['role'],'appearance':b['appearance']})
        for i,s in enumerate([b['shape'],*b['cuts']]):source['operations'].append({'id':b['id']+'_Op'+str(i),'body':b['id'],'action':'create' if i==0 else 'cut','shape':s})
    return parts,source


def solidcraft_extra(program,variant):
    parts,source=extra_source(program,variant)
    provider=types.SimpleNamespace(SOURCE=transfer.SOURCE,expanded=lambda spec,p:source,pose=lambda spec,p:{},samples=lambda spec,p:[])
    spec={'id':source['id'],'status':'Referenced rack geometry','parameters':{}}
    commands=[c for c in portable.solidcraft_commands(spec,{},provider=provider) if not(c['command']=='component.create' and c['params']['name']=='Tube')]
    for b in parts:
        if any(b['translation']):commands.append({'command':'solid.move','params':{'bodies':[b['id']],'translate':b['translation']}})
        if b['group']=='Tube':commands.append({'command':'component.move_bodies','params':{'component':'Tube','bodies':[b['id']]}})
    return commands,parts


def transfer_sliders(commands,program):
    # Add independent Y travel above the existing Z sliders. Joint topology,
    # rather than editing solved transforms, owns both native coordinates.
    result=[]
    for c in commands:
        if c['command']=='joint.create' and c['params']['name'] in ('ToolZ','TubeZ'):
            child=c['params']['name'][:-1];carrier=child+'YCarrier'
            result.append({'command':'component.create','params':{'name':carrier,'parent':'root','activate':False,'grounded':False}})
            frame={'origin':[0,0,0],'z':[0,1,0],'x':[1,0,0]}
            result.append({'command':'joint.create','params':{'name':child+'Y','type':'slider','a':{'occurrence':'Ground','frame':frame},'b':{'occurrence':carrier,'frame':frame},'flip':True,'values':[0],'limits':[program.coordinate_limits[child+'Y']],'quiet':True}})
            zcarrier=child+'ZCarrier'
            result.append({'command':'component.create','params':{'name':zcarrier,'parent':'root','activate':False,'grounded':False}})
            c['params']['a']['occurrence']=carrier;c['params']['b']['occurrence']=zcarrier;c['params']['limits']=[program.coordinate_limits[child+'Z']]
            result.append(c)
            yawframe={'origin':[0,0,0],'z':[0,0,1],'x':[1,0,0]}
            result.append({'command':'joint.create','params':{'name':child+'Yaw','type':'revolute','a':{'occurrence':zcarrier,'frame':yawframe},'b':{'occurrence':child,'frame':yawframe},'flip':True,'values':[0],'limits':[program.coordinate_limits[child+'Yaw']],'quiet':True}})
            continue
        result.append(c)
    return result


def freecad_extras(program,variant,path,adapter):
    parts,source=extra_source(program,variant);saved=adapter.model
    adapter.model=types.SimpleNamespace(ROOT=transfer.ROOT,SOURCE=transfer.SOURCE,digest=transfer.base.robot.digest,evaluate=local.evaluate,expanded=lambda s,p:source,pose=lambda s,p:{})
    try:doc=adapter.build({'id':'H02RackExtras','status':'Referenced rack and vessels','parameters':{}},{},path)
    finally:adapter.model=saved
    return parts,doc
