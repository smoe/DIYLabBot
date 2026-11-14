"""Task-owned persistent headless SolidCraft MCP session; never a desktop bridge."""
import json
import subprocess


class Session:
    def __init__(self,cli,root,directory,path):
        self.log=(directory/'session.log').open('w');self.sequence=0
        self.process=subprocess.Popen([cli,'mcp','--headless','--allow-path',str(root)],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1)
        info=self.rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'H02 native audit','version':'1'}})
        if 'Backend: headless' not in info.get('instructions',''):
            self.close();raise ValueError('CAD audit requires an isolated headless process')
        (directory/'session-info.json').write_text(json.dumps(info,indent=2)+'\n')
        self.tool('skill_reference',{'skill':'solidcraft-modeling','file':'SKILL.md'})
        state=self.tool('inspect_design',{'measure':False,'sketches':False})
        if isinstance(state,dict) and state.get('features'):
            self.close();raise ValueError('Refusing to replace an unexpected existing headless design')
        self.tool('open',{'path':str(path)})

    def rpc(self,method,params):
        self.sequence+=1
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.sequence,'method':method,'params':params})+'\n');self.process.stdin.flush()
        while True:
            line=self.process.stdout.readline()
            if not line:raise RuntimeError('SolidCraft audit session closed unexpectedly')
            message=json.loads(line)
            if message.get('id')==self.sequence:break
        if 'error' in message:raise RuntimeError(str(message['error']))
        return message['result']

    def tool(self,name,arguments):
        result=self.rpc('tools/call',{'name':name,'arguments':arguments})
        while result.get('isError'):
            text='\n'.join(c.get('text','') for c in result.get('content',[]) if c.get('type')=='text')
            if not text.startswith('still running:'):raise RuntimeError(text)
            result=self.rpc('tools/call',{'name':'pending','arguments':{}})
        texts=[c['text'] for c in result.get('content',[]) if c.get('type')=='text']
        if not texts:return None
        try:return json.loads(texts[0])
        except json.JSONDecodeError:return texts[0]

    def run(self,commands):
        result=self.tool('batch',{'commands':commands,'verbose':False,'timings':True})
        if not isinstance(result,dict) or not result.get('ok') or result.get('completed')!=len(commands):
            raise RuntimeError('Incomplete native CAD batch: '+str(result)[:1200])
        return result['results']

    def close(self):
        if getattr(self,'process',None):
            self.process.terminate();self.process.wait(timeout=20);self.process=None
        if getattr(self,'log',None):self.log.close();self.log=None
