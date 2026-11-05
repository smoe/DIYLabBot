"""CAD-independent spindle, braking and powered-lid mechanism recipes (mm/deg)."""
import math


def drive(spec,p,body,cyl,box):
    mount=body('MotorMount','Frame','#87939e','steel_motor_mount')
    box('MotorMountPlate',mount,[100,100,6],[-50,-50,p['base_floor']])
    cyl('MotorMountBore',mount,8.5,8,[0,0,p['base_floor']-1],'cut')
    stator=body('MotorStator','Frame','#426980','motor_stator_envelope')
    cyl('StatorShell',stator,p['motor_outer_radius'],74,[0,0,18]);cyl('StatorAirGap',stator,24,76,[0,0,17],'cut')
    for tag,z in [('Lower',12),('Upper',92)]:
        cap=body('MotorBearing'+tag,'Frame','#65798d','motor_bearing_envelope')
        cyl('MotorEndCap'+tag,cap,p['motor_outer_radius'] if tag=='Lower' else 20,6,[0,0,z])
        cyl('MotorBearingBore'+tag,cap,8.5,8,[0,0,z-1],'cut')
    core=body('MotorRotor','RotorGroup','#7d668b','motor_rotor_envelope');cyl('MotorRotorCore',core,23,70,[0,0,20])
    shaft=body('SpindleShaft','RotorGroup','#748fa5','unselected_spindle');cyl('Shaft',shaft,8,p['rotor_bottom']-12,[0,0,12])
    bearing=body('SpindleBearingHousing','Frame','#65798d','spindle_bearing_envelope')
    z=p['base_height']-18;h=p['chamber_floor_z']-z
    cyl('UpperSpindleBearing',bearing,20,h,[0,0,z]);cyl('UpperSpindleBore',bearing,8.5,h+2,[0,0,z-1],'cut')
    driver=body('SpindleDrive','Frame','#244a66','drive_and_brake_chopper_envelope');box('DriveModule',driver,[44,40,90],[65,25,15])
    resistor=body('BrakingResistor','Frame','#a47959','braking_resistor_envelope');box('ResistorBlock',resistor,[70,24,16],[-130,-55,22])
    for i in range(4):box('ResistorFin'+str(i),resistor,[70,2,8],[-130,-55+i*7,38],'join')
    terminal=body('MotorTerminalBox','Frame','#426980','motor_terminal_envelope');box('MotorTerminal',terminal,[20,16,20],[23,-43,40])
    cable=body('MotorPowerLead','Frame','#d99439','motor_power_cable_envelope')
    a=[43,-35,50];b=[65,25,50];length=math.dist(a,b)
    cyl('MotorPowerLeadRoute',cable,3,length,a,axis=[(v-u)/length for u,v in zip(a,b)])
    z=p['brake_disc_z'];r=p['brake_disc_radius'];t=p['brake_disc_thickness']
    disc=body('ParkingBrakeDisc','RotorGroup','#bb7f65','unqualified_brake_disc')
    cyl('BrakeDisc',disc,r,t,[0,0,z]);cyl('BrakeDiscBore',disc,8,t+2,[0,0,z-1],'cut')
    caliper=body('ParkingCaliper','Frame','#d3a04b','parking_caliper_envelope')
    box('CaliperSpine',caliper,[24,12,26],[-12,r+4,z-10])
    box('CaliperLowerArm',caliper,[24,24,4],[-12,r-8,z-10],'join')
    box('CaliperUpperArm',caliper,[24,24,4],[-12,r-8,z+12],'join')
    post=body('CaliperSupport','Frame','#87939e','steel_brake_support')
    box('CaliperSupportPost',post,[16,6,z-10-p['base_floor']],[-8,r+10,p['base_floor']])
    coil=body('CaliperActuator','Frame','#6d6e75','bistable_caliper_actuator_envelope')
    box('CaliperCoil',coil,[16,12,12],[-8,r+16,z-3])
    for tag,group,pz in [('Upper','BrakePadUpperGroup',z+t),('Lower','BrakePadLowerGroup',z-3)]:
        pad=body('BrakePad'+tag,group,'#383b42','friction_pad_envelope');box('BrakePadBlock'+tag,pad,[16,4,3],[-8,r-7,pz])


def lid(spec,p,frame,body,cyl,box):
    y,z=frame[1:];sr=p['hinge_shaft_radius'];r=p['chamber_inner_radius']+p['chamber_wall']
    shaft=body('LidHingeShaft','LidGroup','#87939e','steel_lid_hinge_shaft');cyl('HingeShaft',shaft,sr,220,[-102,y,z],axis=[1,0,0])
    for tag,x in [('Left',-92),('Right',68)]:
        tower=body('Hinge'+tag+'Envelope','Frame','#65798d','steel_hinge_support')
        box('HingePost'+tag,tower,[24,20,z-12-p['base_height']],[x,y-10,p['base_height']])
        bearing=body('HingeBearing'+tag,'Frame','#87939e','steel_hinge_bearing_housing')
        cyl('HingeBearingOuter'+tag,bearing,13,24,[x,y,z],axis=[1,0,0])
        cyl('HingeBearingBore'+tag,bearing,sr+0.5,26,[x-1,y,z],'cut',axis=[1,0,0])
    for tag,x in [('Left',-62),('Right',50)]:
        lug=body('LidHingeArm'+tag,'LidGroup','#87939e','steel_lid_hinge_arm')
        box('LidRearArm'+tag,lug,[12,32,12],[x,y-28,z+4])
    coupling=body('LidOutputCoupling','LidGroup','#748fa5','steel_lid_output_coupling')
    cyl('LidCoupling',coupling,17,16,[96,y,z],axis=[1,0,0])
    for i in range(4):
        a=math.radians(45+i*90);cyl('CouplingBolt'+str(i),coupling,2.2,18,[95,y+13*math.cos(a),z+13*math.sin(a)],'cut',axis=[1,0,0])
    gearbox=body('LidGearbox','Frame','#426980','lid_gearbox_envelope')
    cyl('LidReductionHousing',gearbox,26,44,[116,y,z],axis=[1,0,0]);cyl('LidOutputBore',gearbox,12,46,[115,y,z],'cut',axis=[1,0,0])
    motor=body('LidMotor','Frame','#426980','lid_motor_envelope');cyl('LidMotorCase',motor,18,22,[160,y,z],axis=[1,0,0])
    brake=body('LidHoldingBrake','Frame','#d3a04b','lid_motor_holding_brake_envelope');cyl('LidHoldingBrakeCase',brake,18,12,[182,y,z],axis=[1,0,0])
    mount=body('LidDriveSupport','Frame','#87939e','steel_lid_drive_support')
    box('LidDrivePedestal',mount,[44,20,z-26-p['base_height']],[116,y-10,p['base_height']])
    for tag,x,group in [('Left',-40,'LatchLeftGroup'),('Right',40,'LatchRightGroup')]:
        lz=p['lid_z'];lc=lz+8
        strike=body('LidStrike'+tag,'LidGroup','#87939e','steel_lid_strike')
        box('StrikeLug'+tag,strike,[12,20,14],[x-6,-r-10,lz+1])
        cyl('StrikeBore'+tag,strike,3.5,10,[x,-r-11,lc],'cut',axis=[0,1,0])
        lock=body('LidLock'+tag,'Frame','#d3a04b','powered_lid_lock_housing')
        box('LockHousing'+tag,lock,[18,18,22],[x-9,-r-30,lc-14])
        cyl('LockGuide'+tag,lock,3.5,20,[x,-r-31,lc],'cut',axis=[0,1,0])
        actuator=body('LidLockActuator'+tag,'Frame','#687784','lid_lock_actuator_envelope')
        cyl('LatchActuator'+tag,actuator,6,20,[x,-r-48,lc],axis=[0,1,0])
        cyl('LatchActuatorBore'+tag,actuator,3.5,22,[x,-r-49,lc],'cut',axis=[0,1,0])
        post=body('LidLockSupport'+tag,'Frame','#87939e','steel_lid_lock_support')
        box('LockSupport'+tag,post,[18,14,lc-14-p['base_height']],[x-9,-r-28,p['base_height']])
        pin=body('LidLockPin'+tag,group,'#748fa5','lid_lock_pin')
        cyl('LockPin'+tag,pin,3,18,[x,-r-20,lc],axis=[0,1,0])


def joints(p):
    result=[];z=p['brake_disc_z'];r=p['chamber_inner_radius']+p['chamber_wall']
    for tag,axis,pz in [('Upper',[0,0,1],z+6),('Lower',[0,0,-1],z)]:
        result.append({'id':'Brake'+tag,'type':'slider','parent':'Frame','child':'BrakePad'+tag+'Group',
            'origin':[0,p['brake_disc_radius']-5,pz],'axis':axis,'reference_x':[1,0,0],'limits':[0,p['brake_clearance']],'unit':'mm'})
    for tag,x in [('Left',-40),('Right',40)]:
        result.append({'id':'Latch'+tag,'type':'slider','parent':'Frame','child':'Latch'+tag+'Group',
            'origin':[x,-r-10,p['lid_z']+8],'axis':[0,-1,0],'reference_x':[1,0,0],'limits':[0,p['latch_travel']],'unit':'mm'})
    return result


def requirements(spec,p):
    lid=spec['mechanisms']['lid'];r=p['chamber_inner_radius']+p['chamber_wall']+4
    mass=math.pi*r*r*p['lid_thickness']*spec['structure']['density_assumption_kg_m3']/1e9
    torque=mass*9.80665*(r-2)/1000
    rpm=math.sqrt(spec['rotor']['target_rcf_x_g']/(1.118e-5*p['bottom_radius']/10));omega=rpm*2*math.pi/60
    inertia=spec['mechanisms']['spindle']['total_rotating_inertia_kg_m2']
    return {'lid_mass_estimate_kg':mass,'lid_static_gravity_torque_nm':torque,'lid_torque_with_factor_nm':torque*lid['gravity_sizing_factor'],
            'lid_output_target_nm':lid['output_torque_target_nm'],'gravity_target_covers_case':lid['output_torque_target_nm']>=torque*lid['gravity_sizing_factor'],
            'lid_motor_target_rpm':lid['nominal_lid_speed_deg_s']/6*lid['gear_ratio'],
            'target_spindle_rpm':rpm,'energy_per_inertia_j_per_kg_m2':0.5*omega*omega,
            'stored_energy_j':None if inertia is None else 0.5*inertia*omega*omega,'stop_time_qualified':False}
