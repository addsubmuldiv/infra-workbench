param([switch]$SystemInfo)
$ErrorActionPreference='Stop'
if($SystemInfo){
  $cpu=Get-CimInstance Win32_Processor
  $system=Get-CimInstance Win32_ComputerSystem
  @{cpu=($cpu.Name -join ', ');logicalProcessors=($cpu | Measure-Object NumberOfLogicalProcessors -Sum).Sum;physicalBytes=$system.TotalPhysicalMemory;os=[Environment]::OSVersion.VersionString} | ConvertTo-Json -Compress
  exit
}
while($null -ne ($line=[Console]::ReadLine())){
  try{
    $request=$line | ConvertFrom-Json
    $family=New-Object 'System.Collections.Generic.HashSet[int]'
    [void]$family.Add([int]$request.root)
    $processes=@(Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='msedgewebview2.exe' OR Name='infra-workbench-desktop.exe'")
    do{
      $changed=$false
      foreach($process in $processes){
        if($family.Contains([int]$process.ParentProcessId) -and $family.Add([int]$process.ProcessId)){$changed=$true}
      }
    }while($changed)
    $filter=($family | ForEach-Object {'IDProcess = '+$_}) -join ' OR '
    $memory=@(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -Filter $filter)
    $details=@(foreach($id in $family){
      $process=Get-Process -Id $id -ErrorAction SilentlyContinue
      $counter=$memory | Where-Object IDProcess -eq $id | Select-Object -First 1
      if($process){[PSCustomObject]@{pid=$id;name=$process.ProcessName;cpuSeconds=$process.TotalProcessorTime.TotalSeconds;privateBytes=[double]$process.PrivateMemorySize64;privateWorkingSet=if($counter){[double]$counter.WorkingSetPrivate}else{$null};workingSet=[double]$process.WorkingSet64}}
    })
    @{at=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds();root=$request.root;details=$details;privateBytes=($details | Measure-Object privateBytes -Sum).Sum;privateWorkingSet=($details | Measure-Object privateWorkingSet -Sum).Sum;workingSet=($details | Measure-Object workingSet -Sum).Sum;processCount=$details.Count} | ConvertTo-Json -Depth 5 -Compress
  }catch{@{error=$_.Exception.Message} | ConvertTo-Json -Compress}
}
