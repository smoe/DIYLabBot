# Frozen ClearanceCertificate.check from Git commit 586ff76.
# Function SHA256: b57ffe2842ae574259097c78957085ef55105f4c10f161b9fc89d2fa465cba29
# Test oracle only; production uses the current shared checker.
def check(self,curve,max_depth=24):
    first=curve.evaluate(curve.times[0])[floor.F[0]];cell=self.start_grid.cell(first[:2])
    if self.lift_context is None and(cell is None or self.start_grid.blocked[cell]):return {'passed':False,'reason':'initial_pose_not_proven_outside_closed_projected_solids'}
    if self.lift_context is not None:
        # The semantic shaft mask may be removed only for an allocated
        # port stage. Keep an independent physical closed-solid test:
        # raster filling a hollow cabin would incorrectly block boarding.
        from building_fleet_lift_checks import posed_mesh
        actual=posed_mesh(self.mesh,self.lift_context.timeline.values(curve.times[0]))
        z=next(row['z_mm']for row in actual.manifest['levels']if row['id']==self.level)
        low=z+self.config['geometry']['floor_band_start_mm'];high=z+geometry.vehicle_envelope()['height_mm']
        for group in actual.scene['groups']:
            if group['role']=='viewing_cone':continue
            bounds=actual.bounds(group)
            if any(not bounds['min'][k]<=first[k]<=bounds['max'][k]for k in range(2)):continue
            a,b=max(low,bounds['min'][2]),min(high,bounds['max'][2])
            if b<=a:continue
            membership=nav.closed_mesh_membership(actual,group['id'],[*first[:2],(a+b)/2])
            if membership['inside']or membership['boundary']:
                return {'passed':False,'reason':'initial_pose_inside_or_on_closed_native_solid',
                        'body_id':group['id'],'membership':membership}
    accepted=[];evaluations=0;applications=[];queue=[(a,b,0)for a,b in zip(curve.times,curve.times[1:])]
    while queue:
        start,end,depth=queue.pop();mid=(start+end)/2;pose=curve.evaluate(mid)[floor.F[0]];bounds=_extrema(curve,start,end)
        translation=math.hypot(*[max(abs(bounds[k][i]-pose[i])for k in ('min','max'))for i in range(2)]);turn=max(abs(bounds[k][2]-pose[2])for k in ('min','max'));movement=math.nextafter(translation+self.radius*turn,math.inf)
        distance,body=self.distance(pose[:2],pose[2]);lower=math.nextafter(distance-movement,-math.inf);evaluations+=1
        if distance<self.reserve:return {'passed':False,'reason':'midpoint_mesh_or_exclusion_clearance','time_s':[start,end],'midpoint_pose_mm_rad':pose,'midpoint_clearance_mm':distance,'limiting_body':body,'evaluations':evaluations}
        # An impossible static midpoint cannot be repaired by splitting;
        # a larger interval-support failure may be a conservative envelope.
        def floor_at(inflation,left,right):
            try:return self.support(pose[:2],pose[2],inflation,start_s=left,end_s=right,
                curve_ref={'level':self.level,'time_s':[left,right]})
            except ValueError as exc:return {'passed':False,'reason':str(exc),'lift_gate_failed':True}
        support=floor_at(movement,start,end)if lower>=self.reserve else None
        if lower>=self.reserve and support['passed']:
            applications.extend(support.get('applications',[]))
            accepted.append({'time_s':[start,end],'clearance_lower_mm':lower,'limiting_body':body,'floor_support':True,'support_rule_applied':support.get('rule_applied',False),'height_exception_applied':support.get('lift_height_exception_applied',False),'depth':depth});continue
        if depth>=max_depth:return {'passed':False,'reason':'interval_clearance_or_exact_floor_union_unresolved','time_s':[start,end],'midpoint_pose_mm_rad':pose,'interval_clearance_lower_mm':lower,'floor_union':support,'limiting_body':body,'evaluations':evaluations}
        if support is not None and not floor_at(0,mid,mid)['passed']:return {'passed':False,'reason':'midpoint_expanded_oriented_rectangle_lacks_floor_union','time_s':[start,end],'midpoint_pose_mm_rad':pose,'floor_union':floor_at(0,mid,mid),'evaluations':evaluations}
        queue.extend([(start,mid,depth+1),(mid,end,depth+1)])
    return {'passed':True,'minimum_interval_clearance_lower_mm':min(v['clearance_lower_mm']for v in accepted),'intervals':accepted,'evaluations':evaluations,'minimum_clearance_mm':self.reserve,'mesh_reserve_mm':self.mesh_error,'support_applications':applications,'lift_support':self.lift_context.report()if self.lift_context else None,'floor_support_method':'canonical exact native union plus conservative owner disk closing; full expanded oriented rectangle and source-gated lift-only raised surfaces','qualification':{'native_BRep_curve_checked':False,'dynamic_lift_checked':False,'bench_zones_changed':False},'scope':'Continuous actual PVA x/y/yaw projected-surface and excluded-area clearance plus whole-rectangle floor-union coverage; static enclosed-body start membership checked. Independent native BRep and lift-stage proofs remain required.'}
