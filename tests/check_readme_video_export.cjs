const assert=require('node:assert/strict');
const {assertStateOwnership}=require('../scripts/export_readme_video.cjs');
const source={multiSample:true,sampleIds:['one','two','three','waiting'],transfers:[
  {sample_id:'one',gripped_s:1,support_s:2},{sample_id:'two',gripped_s:3,support_s:4},
  {sample_id:'three',gripped_s:5,support_s:6}]};
for(const time of [0,1,2,3,4,5,6,7]){
  const owners=Object.fromEntries(source.sampleIds.map(id=>{
    const transfer=source.transfers.find(x=>x.sample_id===id);
    return [id,transfer&&time>=transfer.support_s?'rack':transfer&&time>=transfer.gripped_s?'gripper':'rotor'];
  }));
  const state={sourceTimeS:time,sampleOwners:JSON.stringify(owners)};
  assertStateOwnership(state,source);
  assert.throws(()=>assertStateOwnership({...state,sampleOwners:JSON.stringify({...owners,waiting:'rack'})},source));
}
for(const [time,tubeOwner]of [[0,'station'],[1,'gripper'],[2,'rack']])
  assertStateOwnership({sourceTimeS:time,tubeOwner},{attachment:1,handoff:2});
console.log('PASS: all sample identities and legacy single-tube recording states');
