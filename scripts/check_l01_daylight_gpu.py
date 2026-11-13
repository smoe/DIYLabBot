"""Replay recorded WebGL draws in native offscreen macOS OpenGL for GPU QA.

Only the GLSL ES header/precision declarations and immutable texture allocation
are adapted to desktop GL 4.1. No shader lighting logic or geometry is replaced.
This checks the GPU pipeline, not browser layout or calibrated illumination.
"""
import ctypes as c,json,re,struct,zlib,sys,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'exports/tr01-workcell'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--no-casters',action='store_true',help='Negative control: suppress only shadow-caster draws');options=parser.parse_args();
    record=json.loads((OUT/'daylight-gl-commands.json').read_text());width,height=record['width'],record['height']
    lib=c.CDLL('/System/Library/Frameworks/OpenGL.framework/OpenGL')
    def function(name,restype,argtypes):
        f=getattr(lib,name);f.restype=restype;f.argtypes=argtypes;return f
    U,I,F,B,P=c.c_uint,c.c_int,c.c_float,c.c_ubyte,c.c_void_p
    choose=function('CGLChoosePixelFormat',I,[c.POINTER(I),c.POINTER(P),c.POINTER(I)]);create=function('CGLCreateContext',I,[P,P,c.POINTER(P)]);current=function('CGLSetCurrentContext',I,[P])
    attrs=(I*3)(99,0x4100,0);fmt=P();number=I();context=P()
    if choose(attrs,c.byref(fmt),c.byref(number)) or create(fmt,None,c.byref(context)) or current(context):raise RuntimeError('Offscreen native GPU context unavailable')
    string=function('glGetString',c.c_char_p,[U]);version=string(0x1F02).decode()
    funcs={}
    def call(name,*args,types=None,result=None):
        key=(name,tuple(types or []),result)
        if key not in funcs:funcs[key]=function('gl'+name,result,types or [])
        return funcs[key](*args)
    ids={};locations={};compiled=0;linked=0;captures=[];active_program=None
    depth_program_symbol=[cmd['result']['id'] for cmd in record['commands'] if cmd['name']=='createProgram'][-1]
    def gen(kind):
        value=U();call('Gen'+kind,1,c.byref(value),types=[I,c.POINTER(U)]);return value.value
    vao=gen('VertexArrays');call('BindVertexArray',vao,types=[U])
    root=gen('Framebuffers');call('BindFramebuffer',0x8D40,root,types=[U,U])
    colour=gen('Textures');call('BindTexture',0x0DE1,colour,types=[U,U]);call('TexImage2D',0x0DE1,0,0x8058,width,height,0,0x1908,0x1401,None,types=[U,I,I,I,I,I,U,U,P]);call('FramebufferTexture2D',0x8D40,0x8CE0,0x0DE1,colour,0,types=[U,U,U,U,I])
    depth=gen('Renderbuffers');call('BindRenderbuffer',0x8D41,depth,types=[U,U]);call('RenderbufferStorage',0x8D41,0x81A6,width,height,types=[U,U,I,I]);call('FramebufferRenderbuffer',0x8D40,0x8D00,0x8D41,depth,types=[U,U,U,U]);call('DrawBuffer',0x8CE0,types=[U]);call('ReadBuffer',0x8CE0,types=[U])
    assert call('CheckFramebufferStatus',0x8D40,types=[U],result=U)==0x8CD5
    def identifier(arg):return root if arg is None else ids[arg['id']]
    def array(arg,ctype):
        values=arg['data'] if isinstance(arg,dict) else arg
        return (ctype*len(values))(*values)
    def status(shader,program=False):
        nonlocal compiled,linked
        value=I();call('GetProgramiv' if program else 'GetShaderiv',shader,0x8B82 if program else 0x8B81,c.byref(value),types=[U,U,c.POINTER(I)])
        if not value.value:
            buffer=c.create_string_buffer(16384);length=I();call('GetProgramInfoLog' if program else 'GetShaderInfoLog',shader,len(buffer),c.byref(length),buffer,types=[U,I,c.POINTER(I),P]);raise RuntimeError(buffer.value.decode())
        if program:linked+=1
        else:compiled+=1
    def capture(name):
        if options.no_casters:name='no-casters-'+name
        call('BindFramebuffer',0x8D40,root,types=[U,U]);call('ReadBuffer',0x8CE0,types=[U]);call('Finish')
        pixels=(B*(width*height*4))();call('ReadPixels',0,0,width,height,0x1908,0x1401,pixels,types=[I,I,I,I,U,U,P]);raw=bytes(pixels)
        scan=b''.join(b'\0'+raw[y*width*4:(y+1)*width*4] for y in reversed(range(height)))
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(scan,9))+chunk(b'IEND',b'')
        (OUT/name).write_bytes(png);captures.append({'file':name,'bytes':len(png),'nonzero_rgb_bytes':sum(v!=0 for i,v in enumerate(raw) if i%4!=3)})
    for index,command in enumerate(record['commands']):
        name=command['name'];a=command.get('args',[]);r=command.get('result')
        if name=='createShader':ids[r['id']]=call('CreateShader',a[0],types=[U],result=U)
        elif name=='createProgram':ids[r['id']]=call('CreateProgram',result=U)
        elif name in ('createBuffer','createTexture','createFramebuffer'):ids[r['id']]=gen({'createBuffer':'Buffers','createTexture':'Textures','createFramebuffer':'Framebuffers'}[name])
        elif name=='shaderSource':
            source=re.sub(r'precision\s+\w+\s+\w+\s*;','',a[1].replace('#version 300 es','#version 410 core')).encode();ptr=c.c_char_p(source);call('ShaderSource',identifier(a[0]),1,c.byref(ptr),None,types=[U,I,c.POINTER(c.c_char_p),P])
        elif name=='compileShader':call('CompileShader',identifier(a[0]),types=[U]);status(identifier(a[0]))
        elif name=='attachShader':call('AttachShader',identifier(a[0]),identifier(a[1]),types=[U,U])
        elif name=='linkProgram':call('LinkProgram',identifier(a[0]),types=[U]);status(identifier(a[0]),True)
        elif name=='getUniformLocation':locations[r['id']]=call('GetUniformLocation',identifier(a[0]),a[1].encode(),types=[U,c.c_char_p],result=I)
        elif name=='getAttribLocation':assert call('GetAttribLocation',identifier(a[0]),a[1].encode(),types=[U,c.c_char_p],result=I)==r
        elif name in ('getShaderParameter','getProgramParameter','getParameter'):continue
        elif name=='checkFramebufferStatus':assert call('CheckFramebufferStatus',a[0],types=[U],result=U)==r
        elif name=='useProgram':active_program=a[0]['id'];call('UseProgram',identifier(a[0]),types=[U])
        elif name in ('bindBuffer','bindTexture','bindFramebuffer'):call(name[0].upper()+name[1:],a[0],identifier(a[1]),types=[U,U])
        elif name=='bufferData':
            data=array(a[1],{'Int16Array':c.c_short,'Uint32Array':U,'Float32Array':F}[a[1]['typed']]);call('BufferData',a[0],c.sizeof(data),data,a[2],types=[U,c.c_ssize_t,P,U])
        elif name=='vertexAttribPointer':call('VertexAttribPointer',*a[:5],P(a[5]),types=[U,I,U,B,I,P])
        elif name in ('enable','disable','enableVertexAttribArray','activeTexture','readBuffer'):call(name[0].upper()+name[1:],a[0],types=[U])
        elif name in ('blendFunc','texParameteri','framebufferTextureLayer'):
            if name=='blendFunc':call('BlendFunc',*a,types=[U,U])
            elif name=='texParameteri':call('TexParameteri',*a,types=[U,U,I])
            else:call('FramebufferTextureLayer',a[0],a[1],identifier(a[2]),a[3],a[4],types=[U,U,U,I,I])
        elif name=='texStorage3D':call('TexImage3D',a[0],0,a[2],a[3],a[4],a[5],0,0x1902,0x1405,None,types=[U,I,I,I,I,I,I,U,U,P])
        elif name=='drawBuffers':data=(U*len(a[0]))(*a[0]);call('DrawBuffers',len(data),data,types=[I,c.POINTER(U)])
        elif name=='uniformMatrix4fv':data=array(a[2],F);call('UniformMatrix4fv',locations[a[0]['id']],len(data)//16,a[1],data,types=[I,I,B,c.POINTER(F)])
        elif name in ('uniform1fv','uniform2fv','uniform3fv','uniform4fv','uniform1iv'):
            dtype=I if name.endswith('iv') else F;data=array(a[1],dtype);size=int(name[7]);call(name[0].upper()+name[1:],locations[a[0]['id']],len(data)//size,data,types=[I,I,c.POINTER(dtype)])
        elif name in ('uniform1i','uniform1f','uniform4f'):
            dtype=I if name.endswith('i') else F;call(name[0].upper()+name[1:],locations[a[0]['id']],*a[1:],types=[I]+[dtype]*(len(a)-1))
        elif name=='viewport':call('Viewport',*a,types=[I]*4)
        elif name=='depthMask':call('DepthMask',a[0],types=[B])
        elif name=='clearDepth':call('ClearDepth',a[0],types=[c.c_double])
        elif name=='clearColor':call('ClearColor',*a,types=[F]*4)
        elif name=='clear':call('Clear',a[0],types=[U])
        elif name=='polygonOffset':call('PolygonOffset',*a,types=[F,F])
        elif name=='blitFramebuffer':call('BlitFramebuffer',*a,types=[I]*8+[U,U])
        elif name=='drawElements':
            if not options.no_casters or active_program!=depth_program_symbol:call('DrawElements',*a[:3],P(a[3]),types=[U,I,U,P])
        elif name=='drawArrays':call('DrawArrays',*a,types=[U,I,I])
        elif name=='capture':capture(a[0])
        else:raise RuntimeError('Unknown recorded GPU operation: '+name)
        error=call('GetError',result=U)
        if error:raise RuntimeError(f'GL error {error:#x} at {index}: {name}')
    report={'passed':True,'fragment_sha256':record.get('fragment_sha256'),'no_casters_control':options.no_casters,'backend':version,'compiled_shaders':compiled,'linked_programs':linked,'commands':len(record['commands']),'captures':captures,
        'scope':'Native offscreen GPU replay of recorded WebGL draws, GLSL header/precision and immutable texture allocation adapted to desktop GL; no browser or photometric validation'}
    (OUT/('daylight-gpu-control.json' if options.no_casters else 'daylight-gpu-validation.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
