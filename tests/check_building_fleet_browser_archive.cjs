// Browser-native extraction preserves exact source bytes and verifies every file.
const assert=require('node:assert/strict'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
(async()=>{
 const api=await import(pathToFileURL(path.resolve(__dirname,'../scripts/building_fleet_browser_worker.mjs')).href);
 const raw=execFileSync('python3',['-c',"import io,zipfile,sys; f=io.BytesIO(); z=zipfile.ZipFile(f,'w',compression=zipfile.ZIP_DEFLATED); z.writestr('scripts/example.py',b'original source\\n'); z.writestr('NOTICE',b'0.0,-0.0,1.0'); z.close(); sys.stdout.buffer.write(f.getvalue())"]);
 const original={'scripts/example.py':Buffer.from('original source\n'),NOTICE:Buffer.from('0.0,-0.0,1.0')};
 const manifest={files:Object.fromEntries(Object.entries(original).map(([k,b])=>[k,{bytes:b.length,sha256:crypto.createHash('sha256').update(b).digest('hex')}]))};
 const written=new Map(),directories=[];
 const python={FS:{mkdirTree:p=>directories.push(p),writeFile:(p,b)=>written.set(p,Buffer.from(b))}};
 await api.extractArchive(python,raw,manifest);assert.deepEqual(directories,['/project/scripts']);
 for(const [k,b]of Object.entries(original))assert.deepEqual(written.get('/project/'+k),b);
 await assert.rejects(api.extractArchive(python,raw,{files:{...manifest.files,extra:{bytes:0,sha256:'a'.repeat(64)}}}),/directory/);
 const bad=structuredClone(manifest);bad.files.NOTICE.sha256='b'.repeat(64);
 await assert.rejects(api.extractArchive(python,raw,bad),/source bytes differ/);
 const truncated=raw.subarray(0,raw.length-1);
 await assert.rejects(api.extractArchive(python,truncated,manifest),/end record/);
 console.log('Passed native ZIP extraction, complete file closure, original numeric bytes and corruption rejection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
