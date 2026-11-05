Var IwbRuntimePrepared
!define IWB_RUNTIME_HELPER "${__FILEDIR__}\installer-runtime.ps1"
; Only the installer-owned Python onedir resources are replaced. User data is external.
!macro IWB_RUNTIME_ACTION ACTION
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\iwb-installer-runtime.ps1" -InstallDirectory "$INSTDIR" -Action ${ACTION}'
  Pop $R9
!macroend

!macro NSIS_HOOK_PREINSTALL
  StrCpy $IwbRuntimePrepared 0
  InitPluginsDir
  File /oname=$PLUGINSDIR\iwb-installer-runtime.ps1 "${IWB_RUNTIME_HELPER}"
  !insertmacro IWB_RUNTIME_ACTION prepare
  ${If} $R9 != 0
    IfSilent +2
    MessageBox MB_OK|MB_ICONSTOP "Cannot safely replace the old runtime. Exit Infra Workbench from the tray and retry. / 无法安全替换旧运行库，请从托盘退出工作台后重试。"
    SetErrorLevel 1
    Abort
  ${EndIf}
  StrCpy $IwbRuntimePrepared 1
!macroend

!macro NSIS_HOOK_POSTINSTALL
  StrCpy $IwbRuntimePrepared 0
  !insertmacro IWB_RUNTIME_ACTION commit
  ${If} $R9 != 0
    DetailPrint "Previous runtime backup retained; remove _internal.iwb-previous only after checking the new installation."
  ${EndIf}
!macroend

Function .onInstFailed
  StrCmp $IwbRuntimePrepared 1 0 done
  IfFileExists "$PLUGINSDIR\iwb-installer-runtime.ps1" 0 done
  SetOutPath $INSTDIR
  !insertmacro IWB_RUNTIME_ACTION rollback
done:
FunctionEnd

!define MUI_CUSTOMFUNCTION_ABORT IwbInstallerUserAbort
Function IwbInstallerUserAbort
  StrCmp $IwbRuntimePrepared 1 0 done
  IfFileExists "$PLUGINSDIR\iwb-installer-runtime.ps1" 0 done
  SetOutPath $INSTDIR
  !insertmacro IWB_RUNTIME_ACTION rollback
done:
FunctionEnd
