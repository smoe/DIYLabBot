const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const {pathToFileURL} = require('node:url');

const reference = String.raw`
import json, math, random, sys
sys.path.insert(0,'scripts')
from building_fleet_sim import SegmentIndex
random.seed(7)
segments=[((0.,0.),(0.,500.)),((0.,0.),(250.,250.)),((500.,500.),(0.,500.))]
segments += [(tuple(random.uniform(-2400,2400) for _ in range(2)),
              tuple(random.uniform(-2400,2400) for _ in range(2))) for _ in range(100)]
index=SegmentIndex(segments)
scenes=[]
for x,y in ((0.,0.),(-500.,-500.),(250.,250.),(775.,-203.3),(10000.,0.),(-10000.,10000.)):
    headings=[(1.,-0.),(-1.,0.),(0.,1.),(-0.,-1.)]
    for yaw in (0., .89388147495242, 1.9706476277134124, math.pi):
        headings += [(math.cos(yaw+math.radians(i*.36)),math.sin(yaw+math.radians(i*.36)))
                     for i in range(1000)]
    scenes.append([x,y,12000.,headings,[index.ray((x,y),d,12000.) for d in headings]])
print(json.dumps({"segments":index.segments,"cells":[[x,y,rows] for (x,y),rows in index.cells.items()],
                  "bounds":index._ray_bounds,"cell":index.cell,"scenes":scenes},allow_nan=False))
`;

(async function () {
    const result = spawnSync('python3', ['-B','-c',reference], {
        cwd:path.join(__dirname,'..'), encoding:'utf8', maxBuffer:8*1024*1024
    });
    assert.equal(result.status,0,result.stderr);
    const {makeStaticRayBatch} = await import(pathToFileURL(
        path.join(__dirname,'../scripts/building_fleet_browser_worker.mjs')));
    const {segments,cells,cell,bounds,scenes} = JSON.parse(result.stdout);
    const getDistances = makeStaticRayBatch(segments,cells,cell,bounds);
    for (const [x,y,limit,headings,expected] of scenes) {
        assert.deepEqual(getDistances(x,y,limit,headings),expected);
    }
    const empty = makeStaticRayBatch([],[],500,null);
    assert.deepEqual(empty(0,0,12000,[[1,0]]),[12000]);
    console.log('Static ray batch matches the ordered Python grid traversal for 24,024 beams.');
})().catch(error => { console.error(error); process.exitCode=1; });
