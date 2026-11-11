"""Source-referenced C2 spatial route; no new construction or device state."""
import math


def _plus(a,b,f=1.):return [x+f*y for x,y in zip(a,b)]


class LoadedPath:
    """Axial line, seventh-degree Bezier blend, vertical rack entry.

    Two collinear control edges at each blend endpoint give zero curvature.
    Piece weights match first derivatives, so nonzero traversal speed does not
    create an acceleration jump at either straight/blend join.
    """
    def __init__(self,goals,tilt_deg,route):
        xyz=lambda name:[goals[name][i][3] for i in range(3)]
        self.start=xyz('grasp');self.end=xyz('rack_seated');self.tilt=tilt_deg
        delta=[b-a for a,b in zip(self.start,xyz('extracted'))];length=math.sqrt(sum(v*v for v in delta))
        self.axis=[v/length for v in delta]
        self.axial_exit_mm=route['axial_exit_mm'];self.vertical_entry_mm=route['vertical_entry_mm']
        a,b=route['axial_blend_mm'],route['vertical_blend_mm']
        x=_plus(self.start,self.axis,self.axial_exit_mm);y=_plus(self.end,[0.,0.,1.],self.vertical_entry_mm)
        self.controls=[x,_plus(x,self.axis,a),_plus(x,self.axis,2*a),xyz('withdrawn'),xyz('upright'),
                       _plus(y,[0.,0.,1.],2*b),_plus(y,[0.,0.,1.],b),y]
        weights=[self.axial_exit_mm/(7*a),1.,self.vertical_entry_mm/(7*b)];total=sum(weights)
        self.boundaries=(weights[0]/total,(weights[0]+weights[1])/total)
        self.clearance_x_mm=xyz(route['clearance_pose'])[0]
        self.removed_distance_mm=length

    def pose(self,u):
        u=max(0.,min(1.,u));first,last=self.boundaries
        if u<=first:return {'position':_plus(self.start,self.axis,self.axial_exit_mm*u/first),'tilt':self.tilt}
        if u>=last:return {'position':_plus(self.end,[0.,0.,1.],self.vertical_entry_mm*(1-u)/(1-last)),'tilt':0.}
        z=(u-first)/(last-first);points=[point[:] for point in self.controls]
        while len(points)>1:points=[[(1-z)*x+z*y for x,y in zip(a,b)] for a,b in zip(points,points[1:])]
        f=35*z**4-84*z**5+70*z**6-20*z**7
        return {'position':points[0],'tilt':self.tilt*(1-f)}


class CornerPath:
    """Two original straight legs joined by a local C2 seventh-degree blend.

    The corner is a control point, not a required pass-through or resting pose.
    ``u`` is weighted geometric progress; a separate clock sets physical speed.
    Tilt stays fixed along the first straight leg, then changes over the blend
    and remaining final leg, with zero first three endpoint derivatives. No
    collision clearance or physical timing is implied.
    """
    def __init__(self,start,corner,end,start_tilt_deg,end_tilt_deg,trim_mm=10.):
        def finite(value):return type(value) in (int,float) and math.isfinite(value)
        def point(value):
            if not isinstance(value,(list,tuple)) or len(value)!=3 or not all(finite(x) for x in value):
                raise ValueError('Finite three-dimensional source points required')
            return list(value)
        self.start,self.corner,self.end=point(start),point(corner),point(end)
        if not finite(start_tilt_deg) or not finite(end_tilt_deg):raise ValueError('Finite source tilts required')
        if not finite(trim_mm) or trim_mm<=0:raise ValueError('Finite positive corner trim required')
        incoming=[b-a for a,b in zip(self.start,self.corner)];outgoing=[b-a for a,b in zip(self.corner,self.end)]
        length_in,length_out=math.hypot(*incoming),math.hypot(*outgoing)
        if not all(math.isfinite(x) and x>trim_mm for x in [length_in,length_out]):
            raise ValueError('Both source legs must be strictly longer than the corner trim')
        self.incoming=[v/length_in for v in incoming];self.outgoing=[v/length_out for v in outgoing]
        if math.hypot(*[a+b for a,b in zip(self.incoming,self.outgoing)])<=1e-12:
            raise ValueError('A reversing corner cannot form a non-cusped local blend')
        self.start_tilt,self.end_tilt=start_tilt_deg,end_tilt_deg;self.trim_mm=trim_mm
        self.first_length,self.last_length=length_in-trim_mm,length_out-trim_mm
        h=trim_mm/3.;x=_plus(self.corner,self.incoming,-trim_mm);y=_plus(self.corner,self.outgoing,trim_mm)
        if h<=0:raise ValueError('Numerically resolvable corner trim required')
        self.controls=[x,_plus(x,self.incoming,h),_plus(x,self.incoming,2*h),self.corner[:],self.corner[:],
                       _plus(y,self.outgoing,-2*h),_plus(y,self.outgoing,-h),y]
        weights=[self.first_length/(7*h),1.,self.last_length/(7*h)];total=sum(weights)
        self.boundaries=(weights[0]/total,(weights[0]+weights[1])/total)
        if not 0<self.boundaries[0]<self.boundaries[1]<1:raise ValueError('Numerically distinct corner progress intervals required')

    def _piece(self,u,side):
        if type(u) not in (int,float) or not math.isfinite(u) or not 0<=u<=1:raise ValueError('Finite progress in 0..1 required')
        if side not in ('left','right'):raise ValueError('Left or right endpoint side required')
        first,last=self.boundaries
        if u<first or u==first and side=='left':return 0,u/first
        if u>last or u==last and side=='right':return 2,(u-last)/(1-last)
        return 1,(u-first)/(last-first)

    @staticmethod
    def _bezier(controls,z):
        points=[point[:] for point in controls]
        while len(points)>1:points=[[(1-z)*x+z*y for x,y in zip(a,b)] for a,b in zip(points,points[1:])]
        return points[0]

    def pose(self,u):
        piece,z=self._piece(u,'right')
        if u==0:return {'position':self.start[:],'tilt':self.start_tilt}
        if u==1:return {'position':self.end[:],'tilt':self.end_tilt}
        first=self.boundaries[0];angular=max(0.,(u-first)/(1-first))
        blend=35*angular**4-84*angular**5+70*angular**6-20*angular**7
        tilt=self.start_tilt+(self.end_tilt-self.start_tilt)*blend
        if piece==0:return {'position':_plus(self.start,self.incoming,z*self.first_length),'tilt':tilt}
        if piece==2:return {'position':_plus(self.controls[-1],self.outgoing,z*self.last_length),'tilt':tilt}
        return {'position':self._bezier(self.controls,z),'tilt':tilt}

    def derivative(self,u,order=1,side='right'):
        if type(order) is not int or order not in (1,2):raise ValueError('Spatial derivative order 1 or 2 required')
        piece,z=self._piece(u,side);first,last=self.boundaries
        if piece!=1:
            if order==2:return [0.,0.,0.]
            direction,length,span=(self.incoming,self.first_length,first) if piece==0 else (self.outgoing,self.last_length,1-last)
            return [v*length/span for v in direction]
        controls=self.controls
        for degree in range(7,7-order,-1):controls=[[degree*(b-a) for a,b in zip(x,y)] for x,y in zip(controls,controls[1:])]
        return [v/(last-first)**order for v in self._bezier(controls,z)]
