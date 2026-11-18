"""Portable compact kitchen furniture; room and appliance placements are separate."""
import math


def parameters(source):
    if source.get('format') != 'solidcraftbot.kitchenette-furniture/1' or source.get('recipe') != 'blue_compact_kitchen/1':
        raise ValueError('Supported shared kitchenette recipe required')
    result = {}
    for key, item in source['parameters'].items():
        value = item['value']
        if item['unit'] != 'mm' or type(value) not in (int, float) or not math.isfinite(value) or not item['range'][0] <= value <= item['range'][1]:
            raise ValueError('Bounded kitchenette dimension required: '+key)
        result[key] = value
    if set(result) != {'width','depth','counter_height','counter_thickness','fridge_bay','drawer_bay','upper_bottom','upper_height','upper_depth'}:
        raise ValueError('Explicit independent kitchenette dimensions required')
    if result['width']-result['fridge_bay']-result['drawer_bay'] < 480:
        raise ValueError('Sink cabinet must contain its basin')
    return result


def parts(source):
    p = parameters(source); colors = source['colors']; result = []
    def shape(name, shape, color='carcass', action='create', body=None):
        result.append({'id':name,'body':body or name,'action':action,'color':colors[color],'shape':shape})
    def box(name, origin, size, color='carcass', action='create', body=None):
        shape(name, {'kind':'box','origin':origin,'size':size}, color, action, body)
    def cylinder(name, origin, radius, height, color='metal', action='create', body=None):
        shape(name, {'kind':'cylinder','origin':origin,'radius':radius,'height':height}, color, action, body)
    def rounded(name, x, y, w, d, z, h, r, color, action='create', body=None):
        points = []
        for cx,cy,start in [(x+w-r,y+r,-90),(x+w-r,y+d-r,0),(x+r,y+d-r,90),(x+r,y+r,180)]:
            points.extend([[cx+r*math.cos(math.radians(start+i*90/8)),cy+r*math.sin(math.radians(start+i*90/8))] for i in range(9)])
        shape(name, {'kind':'polygon_prism','plane':'XY','points':points,'offset':z,'depth':h},color,action,body)
    def handle(name, x, y, z, length, vertical=False):
        if vertical:
            box(name,[x,y,z],[12,12,length],'metal')
            for i in (0,length-12): box(name+'Mount'+str(i),[x,y-25,z+i],[12,25,12],'metal')
        else:
            box(name,[x,y,z],[length,12,12],'metal')
            for i in (0,length-12): box(name+'Mount'+str(i),[x+i,y-25,z],[12,25,12],'metal')
    width,depth,h = p['width'],p['depth'],p['counter_height']
    split, drawers = width-p['fridge_bay'],p['drawer_bay']
    bottom = h-p['counter_thickness']; front = depth-25
    box('Plinth',[0,30,0],[split,depth-75,100],'plinth')
    for name,x,w in [('Drawers',0,drawers),('Sink',drawers,split-drawers)]:
        box(name+'Shell',[x,0,100],[w,depth-40,bottom-100])
        box(name+'Hollow',[x+18,18,118],[w-36,depth,bottom-136],action='cut',body=name+'Shell')
    box('Worktop',[0,0,bottom],[width,depth,p['counter_thickness']],'counter')
    sink_x = drawers+(split-drawers-440)/2
    rounded('SinkCut',sink_x,150,440,380,bottom-1,p['counter_thickness']+3,30,'counter','cut','Worktop')
    rounded('SinkCabinetCut',sink_x-9,141,458,398,h-191,200,39,'carcass','cut','SinkShell')
    rounded('SinkBasin',sink_x,150,440,380,h-190,198,30,'metal')
    rounded('SinkRim',sink_x-8,142,456,396,h,8,38,'metal','join','SinkBasin')
    rounded('SinkBowl',sink_x+8,158,424,364,h-178,205,24,'metal','cut','SinkBasin')
    cylinder('Drain',[sink_x+220,340,h-177],22,3,'dark')
    rounded('Drainer',30,145,drawers-40,390,h,7,15,'metal')
    for n in range(13):
        box('DrainerRib'+str(n),[48+n*(drawers-85)/13,175,h+7],[4,325,3],'metal')
    cylinder('TapFoot',[sink_x+220,95,h],24,18)
    cylinder('Tap',[sink_x+220,95,h+18],16,135)
    box('TapSpout',[sink_x+207,90,h+125],[26,145,22],'metal')
    cylinder('TapOutlet',[sink_x+220,220,h+114],14,15)
    box('TapLever',[sink_x+214,65,h+152],[12,65,8],'metal')
    box('SinkFront',[drawers+3,front,103],[split-drawers-6,18,bottom-106],'blue')
    handle('SinkHandle',split-45,front+43,bottom-240,170,True)
    drawer_height = (bottom-100)/5
    for n in range(5):
        z = 103+n*drawer_height
        box('DrawerFront'+str(n+1),[3,front,z],[drawers-6,18,drawer_height-6],'blue')
        handle('DrawerHandle'+str(n+1),60,front+43,z+drawer_height-42,drawers-120)
    upper_z,upper_h,upper_d = p['upper_bottom'],p['upper_height'],p['upper_depth']
    box('UpperShell',[0,0,upper_z],[width,upper_d,upper_h])
    for name,x,w,z,hh in [('Left',18,split/2-27,upper_z+18,upper_h-36),
                          ('Right',split/2+9,split/2-27,upper_z+18,upper_h-36),
                          ('Microwave',split+18,p['fridge_bay']-36,upper_z+18,340),
                          ('Top',split+18,p['fridge_bay']-36,upper_z+376,upper_h-394)]:
        box('UpperCavity'+name,[x,18,z],[w,upper_d,hh],action='cut',body='UpperShell')
    for n in range(2):
        box('UpperDoor'+str(n+1),[3+n*split/2,upper_d,upper_z+3],[split/2-6,18,upper_h-6],'blue')
        handle('UpperHandle'+str(n+1),split/2+(-32 if n==0 else 20),upper_d+43,upper_z+95,180,True)
    box('UpperFlap',[split+3,upper_d,upper_z+361],[p['fridge_bay']-6,18,upper_h-364],'blue')
    handle('UpperFlapHandle',split+100,upper_d+43,upper_z+410,p['fridge_bay']-200)
    # The cubby bottom is the microwave support, distinct from its open cavity.
    # Wall tiles are finishes, not a copied room wall.
    tile=195; rows=4; backsplash_top=upper_z
    for row in range(rows):
        z=h+row*(backsplash_top-h)/rows
        for col in range(math.ceil(width/200)):
            x=col*200
            box('BackTile_'+str(row)+'_'+str(col),[x,-8,z],[min(tile,width-x),8,(backsplash_top-h)/rows-3],'tile')
        for col in range(math.ceil(depth/200)):
            y=col*200
            box('ReturnTile_'+str(row)+'_'+str(col),[-8,y,z],[8,min(tile,depth-y),(backsplash_top-h)/rows-3],'tile')
    # Small recognizable objects from the reference photograph.
    cylinder('SoapBottle',[width-400,95,h],32,175,'tile')
    cylinder('SoapPump',[width-400,95,h+175],12,30,'tile')
    box('SoapSpout',[width-405,90,h+198],[10,55,10],'tile')
    for n in range(5): rounded('Plate'+str(n),40,35,190,90,h+n*6,5,9,'tile')
    box('Cloth',[240,110,h+8],[70,60,9],'cloth')
    return result


def appliance_origin(p, slot):
    bay = p['width']-p['fridge_bay']
    if slot == 'fridge': return [bay+(p['fridge_bay']-560)/2,0,0]
    if slot == 'microwave': return [bay+(p['fridge_bay']-520)/2,0,p['upper_bottom']+18]
    if slot == 'kettle': return [p['width']-180,340,p['counter_height']]
    raise ValueError('Unknown kitchenette appliance support: '+slot)
