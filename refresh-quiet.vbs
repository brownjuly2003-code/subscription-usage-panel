' Completely silent dashboard.html refresh (no console flash).
' Used by Task Scheduler and optional quiet open.
Option Explicit

Dim sh, fso, root, pyw, py, exe, cmd, exitCode
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
If Not fso.FolderExists(root & "\.cache") Then
  On Error Resume Next
  fso.CreateFolder root & "\.cache"
  On Error GoTo 0
End If

pyw = FindExe("pythonw.exe")
py = FindExe("python.exe")
If pyw <> "" Then
  exe = pyw
ElseIf py <> "" Then
  exe = py
Else
  WScript.Quit 1
End If

' Window style 0 = hidden, wait until finished
cmd = """" & exe & """ """ & root & "\limits.py"" --html """ & root & "\dashboard.html"""
exitCode = sh.Run(cmd, 0, True)
WScript.Quit exitCode

Function FindExe(name)
  Dim line, rc
  FindExe = ""
  On Error Resume Next
  rc = sh.Run("cmd /c where " & name & " > """ & root & "\.cache\_where.tmp"" 2>nul", 0, True)
  On Error GoTo 0
  If fso.FileExists(root & "\.cache\_where.tmp") Then
    Dim ts
    Set ts = fso.OpenTextFile(root & "\.cache\_where.tmp", 1)
    If Not ts.AtEndOfStream Then
      line = Trim(ts.ReadLine)
      If line <> "" And fso.FileExists(line) Then FindExe = line
    End If
    ts.Close
    On Error Resume Next
    fso.DeleteFile root & "\.cache\_where.tmp", True
    On Error GoTo 0
  End If
  ' Prefer real install over WindowsApps stub
  If InStr(1, FindExe, "WindowsApps", vbTextCompare) > 0 Then
    Dim alt
    alt = sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python\Python313\" & name)
    If fso.FileExists(alt) Then FindExe = alt
  End If
End Function
