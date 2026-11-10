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
