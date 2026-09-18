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
    [ValidatePattern("^[a-fA-F0-9]{64}$")]
    [string]$ExpectedWorkerSha256,

    [Parameter(Mandatory = $true)]
    [int]$WorkerStartupTimeoutSeconds,

    [Parameter(DontShow = $true)]
    [string]$TestLifecycleTracePath,

    [Parameter(DontShow = $true)]
    [switch]$TestFailAssignProcess,

    [Parameter(DontShow = $true)]
    [int]$TestPauseAfterResumeMilliseconds = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

public sealed class BCBenchSafeJobHandle : SafeHandleZeroOrMinusOneIsInvalid
{
    private BCBenchSafeJobHandle() : base(true)
    {
    }

    public BCBenchSafeJobHandle(IntPtr handle) : base(true)
    {
        SetHandle(handle);
    }

    protected override bool ReleaseHandle()
    {
        return BCBenchJobObject.CloseHandleNative(handle);
    }
}

public sealed class BCBenchSuspendedProcess : IDisposable
{
    public SafeProcessHandle ProcessHandle { get; private set; }
    public SafeWaitHandle PrimaryThreadHandle { get; private set; }
    public int ProcessId { get; private set; }

    public BCBenchSuspendedProcess(SafeProcessHandle processHandle, SafeWaitHandle primaryThreadHandle, int processId)
    {
        ProcessHandle = processHandle;
        PrimaryThreadHandle = primaryThreadHandle;
        ProcessId = processId;
    }

    public void Dispose()
    {
        PrimaryThreadHandle.Dispose();
        ProcessHandle.Dispose();
    }
}

public static class BCBenchJobObject
{
    public const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    public const int JobObjectExtendedLimitInformation = 9;
    public const uint CREATE_SUSPENDED = 0x00000004;
    public const uint CREATE_NO_WINDOW = 0x08000000;
    public const uint CREATE_UNICODE_ENVIRONMENT = 0x00000400;

    private const uint STARTF_USESTDHANDLES = 0x00000100;
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint FILE_SHARE_DELETE = 0x00000004;
    private const uint CREATE_ALWAYS = 2;
    private const uint OPEN_EXISTING = 3;
    private const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
    private const uint WAIT_OBJECT_0 = 0x00000000;
    private const uint WAIT_TIMEOUT = 0x00000102;
    private const uint WAIT_FAILED = 0xFFFFFFFF;
    private const uint INFINITE = 0xFFFFFFFF;
    private const uint STILL_ACTIVE = 259;

    private static string LifecycleTracePath = null;
    private static bool FailAssignProcessForTesting = false;

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
    private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
    {
        public long TotalUserTime;
        public long TotalKernelTime;
        public long ThisPeriodTotalUserTime;
        public long ThisPeriodTotalKernelTime;
        public uint TotalPageFaultCount;
        public uint TotalProcesses;
        public uint ActiveProcesses;
        public uint TotalTerminatedProcesses;
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

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        public uint nLength;
        public IntPtr lpSecurityDescriptor;

        [MarshalAs(UnmanagedType.Bool)]
        public bool bInheritHandle;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public uint cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public uint dwX;
        public uint dwY;
        public uint dwXSize;
        public uint dwYSize;
        public uint dwXCountChars;
        public uint dwYCountChars;
        public uint dwFillAttribute;
        public uint dwFlags;
        public ushort wShowWindow;
        public ushort cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "CreateJobObjectW", SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr jobAttributes, string name);

    [DllImport("kernel32.dll", EntryPoint = "SetInformationJobObject", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(
        BCBenchSafeJobHandle job,
        int informationClass,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION information,
        uint informationLength);

    [DllImport("kernel32.dll", EntryPoint = "AssignProcessToJobObject", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(BCBenchSafeJobHandle job, SafeProcessHandle process);

    [DllImport("kernel32.dll", EntryPoint = "TerminateJobObject", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateJobObject(BCBenchSafeJobHandle job, uint exitCode);

    [DllImport("kernel32.dll", EntryPoint = "QueryInformationJobObject", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryInformationJobObject(
        BCBenchSafeJobHandle job,
        int informationClass,
        out JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information,
        uint informationLength,
        IntPtr returnLength);

    [DllImport("kernel32.dll", EntryPoint = "TerminateProcess", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcessNative(SafeProcessHandle process, uint exitCode);

    [DllImport("kernel32.dll", EntryPoint = "TerminateProcess", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcessRaw(IntPtr process, uint exitCode);

    [DllImport("kernel32.dll", EntryPoint = "ResumeThread", SetLastError = true)]
    private static extern uint ResumeThread(SafeWaitHandle thread);

    [DllImport("kernel32.dll", EntryPoint = "WaitForSingleObject", SetLastError = true)]
    private static extern uint WaitForSingleObject(SafeProcessHandle handle, uint milliseconds);

    [DllImport("kernel32.dll", EntryPoint = "GetExitCodeProcess", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(SafeProcessHandle process, out uint exitCode);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "CreateFileW", SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        ref SECURITY_ATTRIBUTES securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "CreateProcessW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcess(
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref STARTUPINFO startupInfo,
        out PROCESS_INFORMATION processInformation);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, EntryPoint = "CreateProcessWithLogonW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessWithLogon(
        string username,
        string domain,
        string password,
        uint logonFlags,
        string applicationName,
        StringBuilder commandLine,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref STARTUPINFO startupInfo,
        out PROCESS_INFORMATION processInformation);

    [DllImport("kernel32.dll", EntryPoint = "CloseHandle", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool CloseHandleNative(IntPtr handle);

    public static BCBenchSafeJobHandle CreateKillOnCloseJob()
    {
        IntPtr rawJob = CreateJobObject(IntPtr.Zero, null);
        if (rawJob == IntPtr.Zero)
        {
            throw CreateWin32Exception("CreateJobObject");
        }

        BCBenchSafeJobHandle job = new BCBenchSafeJobHandle(rawJob);
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION information = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        uint informationLength = (uint)Marshal.SizeOf(information);
        if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref information, informationLength))
        {
            Win32Exception failure = CreateWin32Exception("SetInformationJobObject");
            job.Dispose();
            throw failure;
        }

        return job;
    }

    public static BCBenchSuspendedProcess CreateSuspendedWorker(
        string applicationName,
        string[] arguments,
        string currentDirectory,
        string[] environmentEntries,
        string stdoutPath,
        string stderrPath,
        string username,
        string domain,
        string password)
    {
        SECURITY_ATTRIBUTES inheritableAttributes = new SECURITY_ATTRIBUTES();
        inheritableAttributes.nLength = (uint)Marshal.SizeOf(inheritableAttributes);
        inheritableAttributes.bInheritHandle = true;
        uint outputShareMode = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE;

        using (SafeFileHandle standardInput = CreateCheckedFile(
            "NUL",
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            ref inheritableAttributes,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL))
        using (SafeFileHandle standardOutput = CreateCheckedFile(
            stdoutPath,
            GENERIC_WRITE,
            outputShareMode,
            ref inheritableAttributes,
            CREATE_ALWAYS,
            FILE_ATTRIBUTE_NORMAL))
        using (SafeFileHandle standardError = CreateCheckedFile(
            stderrPath,
            GENERIC_WRITE,
            outputShareMode,
            ref inheritableAttributes,
            CREATE_ALWAYS,
            FILE_ATTRIBUTE_NORMAL))
        {
            STARTUPINFO startupInfo = new STARTUPINFO();
            startupInfo.cb = (uint)Marshal.SizeOf(startupInfo);
            startupInfo.dwFlags = STARTF_USESTDHANDLES;
            startupInfo.hStdInput = standardInput.DangerousGetHandle();
            startupInfo.hStdOutput = standardOutput.DangerousGetHandle();
            startupInfo.hStdError = standardError.DangerousGetHandle();

            IntPtr environment = BuildEnvironmentBlock(environmentEntries);
            PROCESS_INFORMATION processInformation = new PROCESS_INFORMATION();
            StringBuilder commandLine = new StringBuilder(BuildCommandLine(applicationName, arguments));
            uint creationFlags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW;
            bool created;
            int createError;
            string createOperation;
            try
            {
                if (String.IsNullOrEmpty(username))
                {
                    createOperation = "CreateProcessW";
                    created = CreateProcess(
                        applicationName,
                        commandLine,
                        IntPtr.Zero,
                        IntPtr.Zero,
                        true,
                        creationFlags,
                        environment,
                        currentDirectory,
                        ref startupInfo,
                        out processInformation);
                }
                else
                {
                    createOperation = "CreateProcessWithLogonW";
                    created = CreateProcessWithLogon(
                        username,
                        domain,
                        password,
                        0,
                        applicationName,
                        commandLine,
                        creationFlags,
                        environment,
                        currentDirectory,
                        ref startupInfo,
                        out processInformation);
                }
                createError = created ? 0 : Marshal.GetLastWin32Error();
            }
            finally
            {
                Marshal.FreeHGlobal(environment);
            }

            if (!created)
            {
                throw new Win32Exception(createError, createOperation + " failed");
            }

            SafeProcessHandle processHandle = null;
            SafeWaitHandle threadHandle = null;
            try
            {
                processHandle = new SafeProcessHandle(processInformation.hProcess, true);
                processInformation.hProcess = IntPtr.Zero;
                threadHandle = new SafeWaitHandle(processInformation.hThread, true);
                processInformation.hThread = IntPtr.Zero;
                BCBenchSuspendedProcess process = new BCBenchSuspendedProcess(
                    processHandle,
                    threadHandle,
                    checked((int)processInformation.dwProcessId));
                Trace("Created:" + process.ProcessId);
                return process;
            }
            catch
            {
                if (processHandle != null)
                {
                    TerminateProcessNative(processHandle, 1);
                    processHandle.Dispose();
                }
                else if (processInformation.hProcess != IntPtr.Zero)
                {
                    TerminateProcessRaw(processInformation.hProcess, 1);
                    CloseHandleNative(processInformation.hProcess);
                }
                if (threadHandle != null)
                {
                    threadHandle.Dispose();
                }
                else if (processInformation.hThread != IntPtr.Zero)
                {
                    CloseHandleNative(processInformation.hThread);
                }
                throw;
            }
        }
    }

    public static void AssignProcess(BCBenchSafeJobHandle job, SafeProcessHandle process)
    {
        if (FailAssignProcessForTesting)
        {
            throw new InvalidOperationException("AssignProcessToJobObject failed (simulated)");
        }
        if (!AssignProcessToJobObject(job, process))
        {
            throw CreateWin32Exception("AssignProcessToJobObject");
        }
        Trace("Assigned");
    }

    public static void ResumePrimaryThread(BCBenchSuspendedProcess process)
    {
        if (ResumeThread(process.PrimaryThreadHandle) == UInt32.MaxValue)
        {
            throw CreateWin32Exception("ResumeThread");
        }
        Trace("Resumed");
    }

    public static bool WaitForExit(BCBenchSuspendedProcess process, uint timeoutMilliseconds)
    {
        uint result = WaitForSingleObject(process.ProcessHandle, timeoutMilliseconds);
        if (result == WAIT_OBJECT_0)
        {
            return true;
        }
        if (result == WAIT_TIMEOUT)
        {
            return false;
        }
        if (result == WAIT_FAILED)
        {
            throw CreateWin32Exception("WaitForSingleObject");
        }
        throw new InvalidOperationException("WaitForSingleObject returned unexpected result " + result);
    }

    public static void WaitForExit(BCBenchSuspendedProcess process)
    {
        if (WaitForSingleObject(process.ProcessHandle, INFINITE) != WAIT_OBJECT_0)
        {
            throw CreateWin32Exception("WaitForSingleObject");
        }
    }

    public static bool IsRunning(BCBenchSuspendedProcess process)
    {
        uint exitCode;
        if (!GetExitCodeProcess(process.ProcessHandle, out exitCode))
        {
            throw CreateWin32Exception("GetExitCodeProcess");
        }
        return exitCode == STILL_ACTIVE;
    }

    public static uint GetExitCode(BCBenchSuspendedProcess process)
    {
        uint exitCode;
        if (!GetExitCodeProcess(process.ProcessHandle, out exitCode))
        {
            throw CreateWin32Exception("GetExitCodeProcess");
        }
        return exitCode;
    }

    public static void TerminateJob(BCBenchSafeJobHandle job, uint exitCode)
    {
        if (!TerminateJobObject(job, exitCode))
        {
            throw CreateWin32Exception("TerminateJobObject");
        }
        Trace("JobTerminated");
    }

    public static void WaitForEmptyJob(BCBenchSafeJobHandle job, int timeoutMilliseconds)
    {
        Stopwatch timer = Stopwatch.StartNew();
        while (true)
        {
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information;
            if (!QueryInformationJobObject(
                job, 1, out information,
                (uint)Marshal.SizeOf(typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)),
                IntPtr.Zero))
            {
                throw CreateWin32Exception("QueryInformationJobObject");
            }
            if (information.ActiveProcesses == 0)
            {
                Trace("JobEmpty");
                return;
            }
            if (timer.ElapsedMilliseconds >= timeoutMilliseconds)
            {
                throw new TimeoutException("Timed out waiting for contained job to become empty");
            }
            Thread.Sleep(10);
        }
    }

    public static void TerminateProcess(SafeProcessHandle process, uint exitCode)
    {
        if (!TerminateProcessNative(process, exitCode))
        {
            throw CreateWin32Exception("TerminateProcess");
        }
    }

    private static IntPtr BuildEnvironmentBlock(string[] environmentEntries)
    {
        string[] sortedEntries = (string[])environmentEntries.Clone();
        Array.Sort(sortedEntries, StringComparer.OrdinalIgnoreCase);
        HashSet<string> names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        StringBuilder environment = new StringBuilder();
        foreach (string entry in sortedEntries)
        {
            int separator = entry.IndexOf('=');
            if (separator <= 0 || entry.IndexOf('\0') >= 0)
            {
                throw new ArgumentException("Environment entries must use non-empty NAME=VALUE strings without null characters");
            }
            string name = entry.Substring(0, separator);
            if (!names.Add(name))
            {
                throw new ArgumentException("Environment contains duplicate variable " + name);
            }
            environment.Append(entry);
            environment.Append('\0');
        }
        if (sortedEntries.Length == 0)
        {
            environment.Append('\0');
        }
        environment.Append('\0');
        return Marshal.StringToHGlobalUni(environment.ToString());
    }

    private static string BuildCommandLine(string applicationName, string[] arguments)
    {
        StringBuilder commandLine = new StringBuilder(QuoteArgument(applicationName));
        foreach (string argument in arguments)
        {
            commandLine.Append(' ');
            commandLine.Append(QuoteArgument(argument));
        }
        return commandLine.ToString();
    }

    private static string QuoteArgument(string argument)
    {
        StringBuilder quoted = new StringBuilder();
        quoted.Append('"');
        int backslashCount = 0;
        foreach (char character in argument)
        {
            if (character == '\\')
            {
                backslashCount++;
            }
            else if (character == '"')
            {
                quoted.Append('\\', backslashCount * 2 + 1);
                quoted.Append('"');
                backslashCount = 0;
            }
            else
            {
                quoted.Append('\\', backslashCount);
                quoted.Append(character);
                backslashCount = 0;
            }
        }
        quoted.Append('\\', backslashCount * 2);
        quoted.Append('"');
        return quoted.ToString();
    }

    private static SafeFileHandle CreateCheckedFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        ref SECURITY_ATTRIBUTES securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes)
    {
        SafeFileHandle handle = CreateFile(
            fileName,
            desiredAccess,
            shareMode,
            ref securityAttributes,
            creationDisposition,
            flagsAndAttributes,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            Win32Exception failure = CreateWin32Exception("CreateFile");
            handle.Dispose();
            throw failure;
        }
        return handle;
    }

    private static Win32Exception CreateWin32Exception(string operation)
    {
        return new Win32Exception(Marshal.GetLastWin32Error(), operation + " failed");
    }

    private static void Trace(string lifecycleEvent)
    {
        string tracePath = LifecycleTracePath;
        if (!String.IsNullOrEmpty(tracePath))
        {
            File.AppendAllText(tracePath, lifecycleEvent + Environment.NewLine, new UTF8Encoding(false));
        }
    }
}
'@

function Add-RestrictedAccess {
    param(
        [IO.FileSystemInfo]$Path,
        [Security.Principal.NTAccount]$Account,
        [Security.AccessControl.FileSystemRights]$Rights,
        [Security.AccessControl.InheritanceFlags]$InheritanceFlags
    )

    $security = [IO.FileSystemAclExtensions]::GetAccessControl($Path)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $Account,
        $Rights,
        $InheritanceFlags,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $security.AddAccessRule($rule) | Out-Null
    [IO.FileSystemAclExtensions]::SetAccessControl($Path, $security)
}

function Enable-TestHooks {
    $bindingFlags = [Reflection.BindingFlags]"Static, NonPublic"
    if ($TestLifecycleTracePath) {
        [BCBenchJobObject].GetField("LifecycleTracePath", $bindingFlags).SetValue($null, $TestLifecycleTracePath)
    }
    if ($TestFailAssignProcess) {
        [BCBenchJobObject].GetField("FailAssignProcessForTesting", $bindingFlags).SetValue($null, $true)
    }
}

function Write-TestLifecycleEvent {
    param([string]$LifecycleEvent)

    if ($TestLifecycleTracePath) {
        [IO.File]::AppendAllText($TestLifecycleTracePath, "$LifecycleEvent`n", [Text.UTF8Encoding]::new($false))
    }
}

$job = $null
$worker = $null
$jobAssigned = $false
$payload = $null

try {
    Enable-TestHooks
    $request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $workerRequest = @{
        command = @($request.command)
        cwd = [string]$request.cwd
        env = $request.env
    }
    $inheritedEnvironment = @{}
    if ($null -ne $request.PSObject.Properties["parent_environment_keys"]) {
        if ($null -ne $request.identity) { throw "Restricted workers cannot inherit evaluator environment." }
        $workerRequest.parent_environment_keys = @($request.parent_environment_keys)
        foreach ($name in $workerRequest.parent_environment_keys) {
            if ([string]::IsNullOrWhiteSpace($name) -or $name -match '[=\x00]' -or
                $inheritedEnvironment.ContainsKey($name) -or $null -ne $request.env.PSObject.Properties[$name]) {
                throw "Invalid or duplicate parent environment key."
            }
            $value = [Environment]::GetEnvironmentVariable($name)
            if ($null -eq $value) { throw "Required parent environment variable is missing." }
            $inheritedEnvironment[$name] = $value
        }
    }

    if ($null -ne $request.identity) {
        $aclDomain = if ([string]$request.identity.domain -eq ".") {
            [Environment]::MachineName
        }
        else {
            [string]$request.identity.domain
        }
        $account = [Security.Principal.NTAccount]::new(
            $aclDomain,
            [string]$request.identity.username
        )
        $sharedDirectory = [IO.DirectoryInfo]::new((Split-Path -Parent $WorkerRequestPath))
        $tempDirectory = [IO.DirectoryInfo]::new((Split-Path -Parent $sharedDirectory.FullName))
        Add-RestrictedAccess `
            -Path $tempDirectory `
            -Account $account `
            -Rights ([Security.AccessControl.FileSystemRights]::Traverse) `
            -InheritanceFlags ([Security.AccessControl.InheritanceFlags]::None)
        Add-RestrictedAccess `
            -Path $sharedDirectory `
            -Account $account `
            -Rights ([Security.AccessControl.FileSystemRights]::Traverse) `
            -InheritanceFlags ([Security.AccessControl.InheritanceFlags]::None)
    }

    $workerRequest | ConvertTo-Json -Compress -Depth 10 | Set-Content -LiteralPath $WorkerRequestPath -Encoding utf8NoBOM
    if ($null -ne $request.identity) {
        Add-RestrictedAccess `
            -Path ([IO.FileInfo]::new($WorkerRequestPath)) `
            -Account $account `
            -Rights ([Security.AccessControl.FileSystemRights]::Read) `
            -InheritanceFlags ([Security.AccessControl.InheritanceFlags]::None)
    }

    [string[]]$environmentEntries = @(
        foreach ($property in $request.env.PSObject.Properties) {
            "$($property.Name)=$([string]$property.Value)"
        }
        foreach ($name in $inheritedEnvironment.Keys) {
            "$name=$($inheritedEnvironment[$name])"
        }
    )
    [string[]]$workerArguments = @(
        $WorkerPath,
        $WorkerRequestPath,
        $GatePath,
        [string]$WorkerStartupTimeoutSeconds
    )
    $username = if ($null -eq $request.identity) { $null } else { [string]$request.identity.username }
    $domain = if ($null -eq $request.identity) { $null } else { [string]$request.identity.domain }
    $password = if ($null -eq $request.identity) { $null } else { [string]$request.identity.password }

    $actualWorkerSha256 = (Get-FileHash -LiteralPath $WorkerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualWorkerSha256 -ne $ExpectedWorkerSha256.ToLowerInvariant()) {
        throw "Contained process worker hash mismatch for '$WorkerPath'."
    }

    $job = [BCBenchJobObject]::CreateKillOnCloseJob()
    $worker = [BCBenchJobObject]::CreateSuspendedWorker(
        $PythonExecutable,
        $workerArguments,
        [string]$request.cwd,
        $environmentEntries,
        $StdoutPath,
        $StderrPath,
        $username,
        $domain,
        $password
    )
    [BCBenchJobObject]::AssignProcess($job, $worker.ProcessHandle)
    $jobAssigned = $true
    [BCBenchJobObject]::ResumePrimaryThread($worker)
    if ($TestPauseAfterResumeMilliseconds -gt 0) {
        Start-Sleep -Milliseconds $TestPauseAfterResumeMilliseconds
    }
    [IO.File]::WriteAllText($GatePath, "ready", [Text.UTF8Encoding]::new($false))
    if ($null -ne $request.identity) {
        Add-RestrictedAccess `
            -Path ([IO.FileInfo]::new($GatePath)) `
            -Account $account `
            -Rights ([Security.AccessControl.FileSystemRights]::Read) `
            -InheritanceFlags ([Security.AccessControl.InheritanceFlags]::None)
    }
    Write-TestLifecycleEvent "GateCreated"

    $timeoutMilliseconds = [Math]::Min([int64]$request.timeout_seconds * 1000, [int]::MaxValue)
    $stopProperty = $request.PSObject.Properties["stop_path"]
    $stopRequested = $false
    if ($null -eq $stopProperty) {
        $timedOut = -not [BCBenchJobObject]::WaitForExit($worker, [uint32]$timeoutMilliseconds)
    }
    else {
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $exited = $false
        while (-not ($exited = [BCBenchJobObject]::WaitForExit($worker, 100))) {
            $stopRequested = Test-Path -LiteralPath ([string]$stopProperty.Value) -PathType Leaf
            if ($stopRequested -or $timer.ElapsedMilliseconds -ge $timeoutMilliseconds) {
                break
            }
        }
        $timedOut = -not $exited -and -not $stopRequested
    }
    $returnCode = if ($timedOut) { $null } elseif ($stopRequested) { 1 } else { [long][BCBenchJobObject]::GetExitCode($worker) }
    # Kill-on-close starts termination asynchronously; retain the job until all descendants exit.
    [BCBenchJobObject]::TerminateJob($job, 1)
    [BCBenchJobObject]::WaitForEmptyJob($job, 5000)
    $job.Dispose()
    $job = $null

    $payload = @{
        returncode = $returnCode
        stdout = [IO.File]::ReadAllText($StdoutPath, [Text.Encoding]::UTF8)
        stderr = [IO.File]::ReadAllText($StderrPath, [Text.Encoding]::UTF8)
        timed_out = $timedOut
    } | ConvertTo-Json -Compress
    Write-TestLifecycleEvent "CapturesRead"
}
catch {
    $failure = $_
    if ($null -ne $worker) {
        try {
            if ($jobAssigned -and $null -ne $job) {
                [BCBenchJobObject]::TerminateJob($job, 1)
                [BCBenchJobObject]::WaitForEmptyJob($job, 5000)
            }
            elseif ([BCBenchJobObject]::IsRunning($worker)) {
                [BCBenchJobObject]::TerminateProcess($worker.ProcessHandle, 1)
                if (-not [BCBenchJobObject]::WaitForExit($worker, 5000)) {
                    throw "Timed out waiting for unassigned worker termination."
                }
            }
        }
        catch {
            [Console]::Error.WriteLine($_.Exception.ToString())
        }
    }
    [Console]::Error.WriteLine($failure.Exception.ToString())
    exit 1
}
finally {
    if ($null -ne $job) {
        $job.Dispose()
    }
    if ($null -ne $worker) {
        $worker.Dispose()
    }
}

[Console]::Out.WriteLine($payload)
