type DeviceStatus={processes:unknown[];processes_known:boolean;health:string};
type Snapshot={fresh:boolean;devices:DeviceStatus[]};

export function deviceUsage(snapshot:Snapshot){
  const usage={total:snapshot.devices.length,occupied:0,idle:0,unknown:0,abnormal:0};
  for(const device of snapshot.devices){
    if(!snapshot.fresh)usage.unknown++;
    else if(device.processes.length)usage.occupied++;
    else if(device.health==='Alarm')usage.abnormal++;
    else if(!device.processes_known)usage.unknown++;
    else usage.idle++;
  }
  return usage;
}
