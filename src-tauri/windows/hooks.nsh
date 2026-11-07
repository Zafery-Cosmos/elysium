; Hooks de l'installeur NSIS d'Elysium.
; Si le moteur (elysium-engine.exe) tourne encore, Windows verrouille le
; fichier et l'installation échoue avec « Error opening file for writing ».
; On ferme donc l'application et son moteur avant de copier les fichiers.

!macro NSIS_HOOK_PREINSTALL
  nsExec::Exec 'taskkill /F /T /IM elysium-engine.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /T /IM elysium.exe'
  Pop $0
  Sleep 800
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec 'taskkill /F /T /IM elysium-engine.exe'
  Pop $0
  Sleep 500
!macroend
