import base64,gzip,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import render_tr01_workcell as display

class DisplayClassification(unittest.TestCase):
    def test_native_window_shell_replaces_solid_display_envelopes(self):
        points=[(0,0,0),(40,0,0),(0,40,0),(80,0,0),(120,0,0),(80,40,0)]
        raw=struct.pack('<II',6,2)+b''.join(struct.pack('<hhh',*p) for p in points)
        raw+=struct.pack('<II3I',1,3,0,1,2)+struct.pack('<II3I',4,3,3,4,5)
        wall=[(200,0,0),(240,0,0),(200,40,0)];glass=[(200,80,0),(240,80,0),(200,120,0)]
        shell={'parts':[{'kind':1,'vertices_qmm':wall,'triangles':[[0,1,2]]},{'kind':13,'vertices_qmm':glass,'triangles':[[0,1,2]]}]}
        data=gzip.decompress(base64.b64decode(display.compact_mesh(base64.b64encode(gzip.compress(raw)).decode(),native_shell=shell)))
        count,groups=struct.unpack_from('<II',data);vertices=[struct.unpack_from('<hhh',data,8+i*6) for i in range(count)];offset=8+count*6;result={}
        for _ in range(groups):
            kind,length=struct.unpack_from('<II',data,offset);offset+=8;indices=struct.unpack_from('<'+'I'*length,data,offset);offset+=length*4
            result[kind]=[vertices[i] for i in indices]
        self.assertEqual(result[4],points[3:])
        self.assertEqual(result[1],wall)
        self.assertEqual(result[13],glass)
    def test_central_shelf_reuses_semantic_source_without_changing_triangles(self):
        bounds=display.central_shelf_bounds()
        self.assertTrue(any(b['body']=='IslandShelf_Board' for b in bounds))
        board=next(b for b in bounds if b['body']=='IslandShelf_Board');lo,hi=board['min'],board['max']
        vertices=[lo,[hi[0],lo[1],lo[2]],[lo[0],hi[1],lo[2]],[0,0,1000],[20,0,1000],[0,20,1000]]
        vertices=[tuple(round(v*4) for v in p) for p in vertices]
        raw=struct.pack('<II',6,1)+b''.join(struct.pack('<hhh',*p) for p in vertices)+struct.pack('<II6I',2,6,0,1,2,3,4,5)
        result=gzip.decompress(base64.b64decode(display.compact_mesh(base64.b64encode(gzip.compress(raw)).decode(),bounds)))
        count,groups=struct.unpack_from('<II',result);points=[struct.unpack_from('<hhh',result,8+6*i) for i in range(count)];offset=8+count*6;found={}
        for _ in range(groups):
            kind,length=struct.unpack_from('<II',result,offset);offset+=8
            indices=struct.unpack_from('<'+'I'*length,result,offset);offset+=length*4;found[kind]=[points[i] for i in indices]
        self.assertEqual(found[11],vertices[:3])
        self.assertEqual(found[2],vertices[3:])
        self.assertEqual(sorted(found[2]+found[11]),sorted(vertices))
