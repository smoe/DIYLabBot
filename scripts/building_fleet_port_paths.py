"""Portable source-derived BF01 port paths, not an execution permission.

The recipe keeps initial rotation outside the actual fully open leaves, enters
through the source aperture band, then aligns to the allocated cabin lane.
Native/PVA/support checks and an actual own lift grant remain mandatory.
"""
import copy
import math

import building_fleet_model as model
from building_fleet_lift_checks import _source_aperture, fully_open_values, posed_mesh
from building_fleet_motion import Path, spatial_bounds
from building_fleet_l01 import _rectangle_distance

FLANK_APERTURE_BANDS = 5
UPPER_CORNER_TRIM_FRACTION = 1/4


class PortPaths:
    def __init__(self, source, navigation):
        self.source=model.validate(copy.deepcopy(source));self.nav=navigation
        self.trim=model.reference(source,'angular_profile')['curve']['corner_trim_mm']
        self.ports={p['level_id']:copy.deepcopy(p)for p in navigation.mesh.manifest['elevator']['ports']if p['active']}
        _,self.aperture,_=_source_aperture(checked_navigation=navigation);self.open_leaves={};self.departures={}
        scene=navigation.mesh.scene
        self.mesh_error=scene['linear_tessellation_deflection_mm']+math.sqrt(3)*scene['maximum_float32_error_mm']
        sensor=model.resolved_sensor(source);self.sensor=copy.deepcopy(sensor)
        self.passing=max(navigation.reserve,sensor['clearance_mm']+sensor['range_error_mm']+
            sensor['range_mm']*math.sin(math.radians(sensor['angular_step_deg']))+
            source['geometry']['localization_tolerance_mm'])+navigation.navigation_margin_mm
        self.band=(self.aperture[1]-self.aperture[0])/2-navigation.radius-navigation.reserve-self.mesh_error-navigation.navigation_margin_mm
        if self.band<=0:raise ValueError('Source aperture lacks the full rotating-envelope band')

    def first_corner(self, level):
        if level not in self.open_leaves:
            port=self.ports[level];actual=posed_mesh(self.nav.mesh,fully_open_values(self.nav.mesh,port['id']))
            objects={o['id']:o for o in actual.manifest['objects']}
            ids={ident for key in port['door_object_ids']for ident in objects[key]['moving_body_ids']}
            groups=[g for g in actual.scene['groups']if g['id']in ids]
            if not groups:raise ValueError('Actual source fully open port leaves required')
            outside=1 if port['exit_eye_mm'][0]>port['plane_x_mm']else-1
            front=max(actual.bounds(g)['max'][0]for g in groups)if outside>0 else min(actual.bounds(g)['min'][0]for g in groups)
            distance=self.nav.radius+self.nav.reserve+self.mesh_error+self.nav.navigation_margin_mm
            self.open_leaves[level]=(front+outside*distance,{'source_door_body_ids':sorted(ids),
                'fully_open_leaf_corridor_bound_x_mm':front,'rotation_envelope_mm':distance})
        return copy.deepcopy(self.open_leaves[level])

    def boarding(self, level, waiting_slot, cabin_slot, lanes):
        if level not in self.ports or type(waiting_slot)is not int or not 0<=waiting_slot<len(self.nav.waits[level]):
            raise ValueError('Known source port and own waiting slot required')
        if type(cabin_slot)is not int or not 0<=cabin_slot<len(lanes)or lanes[cabin_slot]['slot']!=cabin_slot:
            raise ValueError('Own source-derived cabin slot required')
        port=self.ports[level];wait=self.nav.waits[level][waiting_slot];park=lanes[cabin_slot]['pose_mm'][:2]
        toward=1 if port['cabin_entry_mm'][0]>port['exit_eye_mm'][0]else-1
        outside=-toward;centre=port['cabin_entry_mm'][1];side=1 if wait[1]>centre else-1
        original_outside=port['plane_x_mm']+outside*(port['wall_thickness_mm']/2+self.nav.radius+self.nav.reserve+self.nav.navigation_margin_mm)
        first,leaf=self.first_corner(level)
        delta=self.nav.radius-self.nav.envelope['width_mm']/2+self.passing-self.nav.reserve
        upper=cabin_slot!=0
        turn_y=centre-self.band if upper else centre+side*self.band
        fraction=.75 if upper and side<0 else 1.
        turn_x=original_outside+toward*delta*fraction
        flank_y=turn_y+side*FLANK_APERTURE_BANDS*self.band
        points=[wait[:2],[first,wait[1]],[first,flank_y],[turn_x,turn_y]]
        bound=self.nav.cabin_interior_mm['min'if toward>0 else'max'][0]
        clear_parked=park[0]-toward*(self.nav.envelope['length_mm']+self.passing)
        if upper:
            early=bound+toward*(self.nav.envelope['length_mm']/2+self.nav.reserve+self.mesh_error+self.nav.navigation_margin_mm)
            points.extend([[early,turn_y],[clear_parked,park[1]],park])
        else:
            clear_wall=bound+toward*(self.nav.radius+self.nav.reserve+self.nav.navigation_margin_mm)
            if (clear_parked-clear_wall)*toward<=0:raise ValueError('Source cabin has no physical alignment strip')
            inside=(clear_wall+clear_parked)/2
            points.extend([[inside,park[1]],park])
        caps=[{'point_index':i,'maximum_trim_mm':self.trim*UPPER_CORNER_TRIM_FRACTION}
            for i in range(1,len(points)-1)]if upper else[]
        path=Path(points,self.trim,corner_trim_caps=caps)
        yaw=wait[2]
        if any(abs(math.remainder(path.evaluate(s)[0][2]-yaw,2*math.pi))>1e-6 for s in(0.,path.length)):
            raise ValueError('Source port recipe failed its physical approach/parking headings')
        return {'level':level,'port_id':port['id'],'waiting_slot':waiting_slot,'cabin_slot':cabin_slot,
            'points_mm':points,'corner_trim_mm':self.trim,'corner_trim_caps':path.corner_trim_caps,
            'body_clear_waypoint_on_reverse':len(points)-2,
            'provenance':{'operation':'source_aperture_flank_and_split_lane',
                'flank_aperture_bands':FLANK_APERTURE_BANDS,'upper_corner_trim_fraction':UPPER_CORNER_TRIM_FRACTION,
                'source_aperture_y_mm':list(self.aperture),'rotating_aperture_band_mm':self.band,
                'turn_x_fraction':fraction,'fully_open_leaf':leaf,
                'scope':'Source-derived geometric proposal only; no lift grant, floor/native/PVA or hardware qualification'}}

    def alighting(self, level, waiting_slot, cabin_slot, lanes):
        row=self.boarding(level,waiting_slot,cabin_slot,lanes);count=len(row['points_mm'])
        row['points_mm'].reverse()
        row['corner_trim_caps']=sorted([{'point_index':count-1-r['point_index'],'maximum_trim_mm':r['maximum_trim_mm']}
            for r in row['corner_trim_caps']],key=lambda r:r['point_index'])
        return row

    def departure_first_corner(self, level, uncertainty):
        """Bound every source door position without guessing its live state."""
        if not math.isfinite(uncertainty)or uncertainty<0:
            raise ValueError('Finite nonnegative source sensing uncertainty required')
        objects={row['id']:row for row in self.nav.mesh.manifest['objects']};checked=set()
        for ident in self.ports[level]['door_object_ids']:
            while ident:
                obj=objects[ident];joint=obj['joint']
                # Native articulation axes are source-global. Pure Y/Z
                # translations leave the full X extent invariant throughout
                # the closed/open interval, including every parent motion.
                if joint['type']!='prismatic'or joint['axis'][0]!=0:
                    raise ValueError('Source door X envelope is not invariant over its articulation')
                checked.add(ident);ident=obj.get('parent_object_id')
        _,leaf=self.first_corner(level);port=self.ports[level]
        outside=1 if port['exit_eye_mm'][0]>port['plane_x_mm']else-1
        required=max(self.nav.reserve,uncertainty)
        envelope=self.nav.radius+required+self.mesh_error+self.nav.navigation_margin_mm
        return leaf['fully_open_leaf_corridor_bound_x_mm']+outside*envelope,{
            **leaf,'operation':'source_X_invariant_door_departure_envelope',
            'rotation_envelope_mm':envelope,'required_source_clearance_mm':required,
            'source_X_invariant_joint_ids':sorted(checked)}

    def waiting_departure(self, level, waiting_slot):
        """Leave an owned bay facing the cabin, then join the static hub."""
        if waiting_slot not in range(len(self.nav.waits[level])):raise ValueError('Known own source waiting slot required')
        key=level,waiting_slot
        if key in self.departures:return copy.deepcopy(self.departures[key])
        wait=self.nav.waits[level][waiting_slot];hub=self.nav.road_hubs[level]
        sensor=self.sensor
        uncertainty=(sensor['clearance_mm']+sensor['range_error_mm']+sensor['range_mm']*math.sin(math.radians(sensor['angular_step_deg']))
            +self.source['geometry']['localization_tolerance_mm'])
        first,leaf=self.departure_first_corner(level,uncertainty)
        points=[wait[:2],[first,wait[1]],[first,hub[1]],list(hub)]
        points=[p for i,p in enumerate(points)if i==0 or math.dist(p,points[i-1])>1e-7]
        others=[p for i,p in enumerate(self.nav.waiting_bay_polygons[level])if i!=waiting_slot]
        recipe={'operation':'owned_waiting_bay_departure_via_source_leaf_rotation_envelope','fully_open_leaf':leaf}
        if others and not self._bay_sweep_clear(points,others,uncertainty):
            # Keep the physical hub and its original outward tangent. The
            # horizontal pass stays on this own bay's side of every other
            # source bay; a support-line diagonal approaches a clear anchor.
            pad=self.nav.radius+max(self.nav.reserve,uncertainty)+self.mesh_error+self.nav.navigation_margin_mm
            low,high=-math.inf,math.inf
            for polygon in others:
                if sum(p[1]for p in polygon)/len(polygon)>wait[1]:high=min(high,min(p[1]for p in polygon)-pad)
                else:low=max(low,max(p[1]for p in polygon)+pad)
            if low>high:raise ValueError('No source-derived private departure pass band')
            pass_y=min(max(hub[1],low),high);outside=1 if hub[0]>first else-1
            threshold=self.nav.envelope['width_mm']/2+self.passing+self.mesh_error+self.nav.navigation_margin_mm
            constraints=[]
            for polygon in others:
                ymin,ymax=min(p[1]for p in polygon),max(p[1]for p in polygon)
                cy=min(max(hub[1],ymin),ymax);dy=abs(cy-hub[1])
                cx=min(p[0]for p in polygon)if outside<0 else max(p[0]for p in polygon)
                if dy<threshold:
                    limit=cx+outside*math.sqrt(max(0.,threshold*threshold-dy*dy))
                    constraints.append((limit,cx,cy))
            if constraints:
                bound,cx,cy=(min(constraints)if outside<0 else max(constraints))
                if outside*(bound-hub[0])>=0:raise ValueError('Source hub lacks a clear outward tangent anchor')
                anchor=(hub[0]+bound)/2;distance=math.hypot(cx-anchor,cy-hub[1])
                target=(threshold+distance)/2
                angle=math.atan2(abs(cx-anchor),abs(cy-hub[1]))-math.acos(min(1.,target/distance))
                if not 0<angle<math.pi/2:raise ValueError('Unresolved source support-line direction')
                start=anchor-outside*abs(pass_y-hub[1])/math.tan(angle)
                if outside*(start-first)<=0 or outside*(anchor-start)<=0:
                    raise ValueError('Source support-line start lies outside the private departure strip')
                points=[wait[:2],[first,wait[1]],[first,pass_y],[start,pass_y],[anchor,hub[1]],list(hub)]
                recipe.update(operation='owned_waiting_departure_support_line_diagonal',
                    pass_y_mm=pass_y,tangent_threshold_mm=threshold,anchor_x_mm=anchor,
                    diagonal_normal_target_mm=target,diagonal_angle_rad=angle)
            else:
                anchor=(hub[0]+first)/2
                points=[wait[:2],[first,wait[1]],[first,pass_y],[anchor,hub[1]],list(hub)]
                recipe.update(operation='owned_waiting_departure_shallow_diagonal',pass_y_mm=pass_y,anchor_x_mm=anchor)
            if not self._bay_sweep_clear(points,others,self.nav.reserve+self.mesh_error+self.nav.navigation_margin_mm):
                raise ValueError('Private departure proposal lacks continuous other-bay rectangle clearance')
        path=Path(points,self.trim)
        if abs(math.remainder(path.evaluate(0)[0][2]-wait[2],2*math.pi))>1e-6:
            raise ValueError('Owned waiting departure would rotate its stationary source heading')
        recipe['scope']='Static geometric proposal only; actual PVA/floor/native/perception checks remain mandatory'
        self.departures[key]={'level':level,'points_mm':points,'corner_trim_mm':self.trim,'corner_trim_caps':[],'provenance':recipe}
        return copy.deepcopy(self.departures[key])

    def _bay_sweep_clear(self,points,others,required):
        """One-sided continuous physical rectangle clearance against fixed bays."""
        path=Path(points,self.trim);L=self.nav.envelope['length_mm']/2;W=self.nav.envelope['width_mm']/2
        before=0.
        for piece in path.pieces:
            bound=spatial_bounds(piece,subdivisions=8);end=before+piece['weight'];pending=[(before,end,0)]
            while pending:
                a,b,depth=pending.pop();mid=(a+b)/2;pose=path.evaluate(mid)[0]
                distance=min(_rectangle_distance(poly,pose[:2],pose[2],L,W)for poly in others)
                error=128*math.ulp(max(1.,*[abs(v)for v in pose[:2]]))
                if distance+error<required:return False
                half_span=max(math.nextafter(mid-a,math.inf),math.nextafter(b-mid,math.inf))
                rotation=math.nextafter(self.nav.radius*bound['angular'][0],math.inf)
                rate=math.nextafter(bound['linear'][0]+rotation,math.inf)
                movement=math.nextafter(rate*half_span,math.inf)
                if math.nextafter(distance-error-movement,-math.inf)>=required:continue
                if depth>=24:return False
                pending.extend([(a,mid,depth+1),(mid,b,depth+1)])
            before=end
        return True
