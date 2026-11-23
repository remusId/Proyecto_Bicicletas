Option Explicit
Dim shell, files, root, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
command = "cmd.exe /d /c " & Chr(34) & Chr(34) & root & "\iniciar_app.bat" & Chr(34) & " --bootstrap" & Chr(34)
result = shell.Run(command, 0, True)
If result <> 0 Then
    MsgBox "No se pudo preparar la aplicación. Comprueba que Python 3.11 o superior y el lanzador py estén instalados y que tengas conexión a Internet.", 16, "Rutas ciclistas"
End If
