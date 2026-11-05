"""H03 model views and native joint health report."""
import tube_cam_model
import render_tube_carrier as renderer


def render_plan(spec,p):
    views=tube_cam_model.render_plan(spec,p)
    for view in views:
        if view['id']=='mechanism':
            view['camera']['distance']=310
            view['camera']['target']=[p['module_pitch']/2+15,12,-6]
        elif view['id']=='cams':
            view['hide_roles']+=['bayonet_cross_pin','robot_release_handle','camshaft_support','structure']
            view['camera'].update(yaw=-2.3,distance=210,target=[p['module_pitch']/2,20,p['cam_center_z']+3])
        elif view['id']=='latch':
            view['hide_roles']+=['cam_follower_pin']
            view['section']={'plane':'XZ','at_mm':21,'flip':True}
            view['camera']['distance']=105
    return views


if __name__=='__main__':
    renderer.model=tube_cam_model
    renderer.main(plan_provider=render_plan)
