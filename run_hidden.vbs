Set WinScriptHost = CreateObject("WScript.Shell")
Set FileSystem = CreateObject("Scripting.FileSystemObject")

Function ReadEnvFile(EnvPath)
    Dim Stream, Line, Parts, Key, Value
    Set Stream = FileSystem.OpenTextFile(EnvPath, 1)
    Do While Not Stream.AtEndOfStream
        Line = Trim(Stream.ReadLine())
        If Len(Line) > 0 And Left(Line, 1) <> "#" Then
            Parts = Split(Line, "=", 2)
            If UBound(Parts) = 1 Then
                Key = Trim(Parts(0))
                Value = Trim(Parts(1))
                WinScriptHost.Environment("PROCESS")(Key) = Value
            End If
        End If
    Loop
    Stream.Close
End Function

Function IsDimmerAlreadyRunning(ScriptDir)
    Dim WmiService, Processes, ProcessInfo, CommandLine
    Set WmiService = GetObject("winmgmts:\\.\root\cimv2")
    Set Processes = WmiService.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='python.exe'")

    For Each ProcessInfo In Processes
        CommandLine = ""
        If Not IsNull(ProcessInfo.CommandLine) Then
            CommandLine = LCase(ProcessInfo.CommandLine)
            If InStr(CommandLine, LCase(ScriptDir & "\dimmer.py")) > 0 Then
                IsDimmerAlreadyRunning = True
                Exit Function
            End If
        End If
    Next

    IsDimmerAlreadyRunning = False
End Function

Dim EnvFile, ScriptDir, VenvPython
EnvFile = FileSystem.GetParentFolderName(WScript.ScriptFullName) & "\.env"

If FileSystem.FileExists(EnvFile) Then
    ReadEnvFile(EnvFile)
End If

ScriptDir = WinScriptHost.Environment("PROCESS")("SCRIPT_DIR")

If IsDimmerAlreadyRunning(ScriptDir) Then
    WScript.Quit 0
End If

WinScriptHost.CurrentDirectory = ScriptDir

VenvPython = ScriptDir & "\.venv\Scripts\python.exe"

If FileSystem.FileExists(VenvPython) Then
    WinScriptHost.Run """" & VenvPython & """ """ & ScriptDir & "\dimmer.py""", 0, False
Else
    WScript.Quit 2
End If

Set WinScriptHost = Nothing
Set FileSystem = Nothing