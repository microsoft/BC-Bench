param(
    [Parameter(Mandatory = $true)]
    [string]$RequestPath,

    [Parameter(Mandatory = $true)]
    [string]$WorkerRequestPath,

    [Parameter(Mandatory = $true)]
    [string]$GatePath,

    [Parameter(Mandatory = $true)]
    [string]$StdoutPath,

    [Parameter(Mandatory = $true)]
    [string]$StderrPath,

    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,

    [Parameter(Mandatory = $true)]
    [string]$WorkerPath,

    [Parameter(Mandatory = $true)]
    [int]$WorkerStartupTimeoutSeconds
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class BCBenchJobObject
{
    public const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    public const int JobObjectExtendedLimitInformation = 9;

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "CreateJobObjectW", SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr jobAttributes, string name);

    [DllImport("kernel32.dll", EntryPoint = "SetInformationJobObject", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(
        IntPtr job,
        int informationClass,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION information,
        uint informationLength);

    [DllImport("kernel32.dll", EntryPoint = "AssignProcessToJobObject", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", EntryPoint = "TerminateJobObject", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateJobObject(IntPtr job, uint exitCode);

    [DllImport("kernel32.dll", EntryPoint = "CloseHandle", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandleNative(IntPtr handle);

    public static IntPtr CreateKillOnCloseJob()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObject failed");
        }

        JOBOBJECT_EXTENDED_LIMIT_INFORMATION information = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        uint informationLength = (uint)Marshal.SizeOf(information);
        if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref information, informationLength))
        {
            int errorCode = Marshal.GetLastWin32Error();
            CloseHandleNative(job);
            throw new Win32Exception(errorCode, "SetInformationJobObject failed");
        }

        return job;
    }

    public static void AssignProcess(IntPtr job, IntPtr process)
    {
        if (!AssignProcessToJobObject(job, process))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "AssignProcessToJobObject failed");
        }
    }

    public static void TerminateJob(IntPtr job, uint exitCode)
    {
        if (!TerminateJobObject(job, exitCode))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "TerminateJobObject failed");
        }
    }

    public static void CloseHandle(IntPtr handle)
    {
        if (!CloseHandleNative(handle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "CloseHandle failed");
        }
    }
}
'@

function Grant-WorkerRequestAccess {
    param(
        [string]$DirectoryPath,
        [string]$Domain,
        [string]$Username
    )

    $account = [Security.Principal.NTAccount]::new($Domain, $Username)
    $directoryInfo = [IO.DirectoryInfo]::new($DirectoryPath)
    $security = [IO.FileSystemAclExtensions]::GetAccessControl($directoryInfo)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $account,
        [Security.AccessControl.FileSystemRights]::ReadAndExecute,
        [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit",
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $security.AddAccessRule($rule) | Out-Null
    [IO.FileSystemAclExtensions]::SetAccessControl($directoryInfo, $security)
}

$job = [IntPtr]::Zero
$process = $null
$stdoutStream = $null
$stderrStream = $null
$jobAssigned = $false
$processStarted = $false
$payload = $null

try {
    $request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $workerRequest = @{
        command = @($request.command)
        cwd = [string]$request.cwd
        env = $request.env
    }

    if ($null -ne $request.identity) {
        Grant-WorkerRequestAccess `
            -DirectoryPath (Split-Path -Parent $WorkerRequestPath) `
            -Domain ([string]$request.identity.domain) `
            -Username ([string]$request.identity.username)
    }
    $workerRequest | ConvertTo-Json -Compress -Depth 10 | Set-Content -LiteralPath $WorkerRequestPath -Encoding utf8NoBOM

    $job = [BCBenchJobObject]::CreateKillOnCloseJob()

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $PythonExecutable
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Environment.Clear()
    foreach ($property in $request.env.PSObject.Properties) {
        $startInfo.Environment[$property.Name] = [string]$property.Value
    }
    $startInfo.ArgumentList.Add($WorkerPath)
    $startInfo.ArgumentList.Add($WorkerRequestPath)
    $startInfo.ArgumentList.Add($GatePath)
    $startInfo.ArgumentList.Add([string]$WorkerStartupTimeoutSeconds)

    if ($null -ne $request.identity) {
        $startInfo.UserName = [string]$request.identity.username
        $startInfo.Domain = [string]$request.identity.domain
        $startInfo.PasswordInClearText = [string]$request.identity.password
        $startInfo.LoadUserProfile = $false
    }

    $stdoutStream = [IO.FileStream]::new($StdoutPath, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $stderrStream = [IO.FileStream]::new($StderrPath, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "ProcessStartInfo failed to launch the contained worker"
    }
    $processStarted = $true

    [BCBenchJobObject]::AssignProcess($job, $process.Handle)
    $jobAssigned = $true

    $stdoutCopy = $process.StandardOutput.BaseStream.CopyToAsync($stdoutStream)
    $stderrCopy = $process.StandardError.BaseStream.CopyToAsync($stderrStream)
    [IO.File]::WriteAllText($GatePath, "ready", [Text.UTF8Encoding]::new($false))

    $timeoutMilliseconds = [Math]::Min([int64]$request.timeout_seconds * 1000, [int]::MaxValue)
    $timedOut = -not $process.WaitForExit([int]$timeoutMilliseconds)
    if ($timedOut) {
        [BCBenchJobObject]::TerminateJob($job, 1)
        $process.WaitForExit()
    }

    [BCBenchJobObject]::CloseHandle($job)
    $job = [IntPtr]::Zero

    $null = $stdoutCopy.GetAwaiter().GetResult()
    $null = $stderrCopy.GetAwaiter().GetResult()
    $stdoutStream.Dispose()
    $stderrStream.Dispose()
    $stdoutStream = $null
    $stderrStream = $null

    $payload = @{
        returncode = if ($timedOut) { $null } else { $process.ExitCode }
        stdout = [IO.File]::ReadAllText($StdoutPath, [Text.Encoding]::UTF8)
        stderr = [IO.File]::ReadAllText($StderrPath, [Text.Encoding]::UTF8)
        timed_out = $timedOut
    } | ConvertTo-Json -Compress
}
catch {
    $failure = $_
    if ($processStarted -and -not $process.HasExited) {
        if ($jobAssigned) {
            try {
                [BCBenchJobObject]::TerminateJob($job, 1)
            }
            catch {
                [Console]::Error.WriteLine($_.Exception.ToString())
            }
        }
        else {
            $process.Kill()
        }
        $process.WaitForExit()
    }
    [Console]::Error.WriteLine($failure.Exception.ToString())
    exit 1
}
finally {
    if ($null -ne $stdoutStream) {
        $stdoutStream.Dispose()
    }
    if ($null -ne $stderrStream) {
        $stderrStream.Dispose()
    }
    if ($job -ne [IntPtr]::Zero) {
        try {
            [BCBenchJobObject]::CloseHandle($job)
        }
        catch {
            [Console]::Error.WriteLine($_.Exception.ToString())
        }
    }
    if ($null -ne $process) {
        $process.Dispose()
    }
}

[Console]::Out.WriteLine($payload)
