// Restart Manager query for the Sunday installer.
//
// The installer has to know which programs use the files it is about to replace
// before it starts replacing them. Windows answers that question through the
// Restart Manager, and this tiny assembly is the bridge the setup's release
// helper loads.
//
// It is compiled when the installer is built, not when it runs: runtime
// compilation (PowerShell's Add-Type) shells out to csc.exe, which is blocked on
// locked-down machines - including the machine where this bug was reported.
//
// The returned strings are "processId|applicationName|applicationType".
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class SundayRestartManager
{
    [StructLayout(LayoutKind.Sequential)]
    private struct RM_UNIQUE_PROCESS
    {
        public int dwProcessId;
        public System.Runtime.InteropServices.ComTypes.FILETIME ProcessStartTime;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct RM_PROCESS_INFO
    {
        public RM_UNIQUE_PROCESS Process;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string strAppName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string strServiceShortName;
        public int ApplicationType;
        public uint AppStatus;
        public uint TSSessionId;
        [MarshalAs(UnmanagedType.Bool)] public bool bRestartable;
    }

    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
    private static extern int RmStartSession(out uint pSessionHandle, int dwSessionFlags, string strSessionKey);

    [DllImport("rstrtmgr.dll")]
    private static extern int RmEndSession(uint pSessionHandle);

    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
    private static extern int RmRegisterResources(
        uint pSessionHandle,
        uint nFiles,
        string[] rgsFilenames,
        uint nApplications,
        RM_UNIQUE_PROCESS[] rgApplications,
        uint nServices,
        string[] rgsServiceNames);

    [DllImport("rstrtmgr.dll")]
    private static extern int RmGetList(
        uint dwSessionHandle,
        out uint pnProcInfoNeeded,
        ref uint pnProcInfo,
        [In, Out] RM_PROCESS_INFO[] rgAffectedApps,
        ref uint lpdwRebootReasons);

    /// <summary>Processes that have any of <paramref name="files"/> open or mapped.</summary>
    public static string[] Query(string[] files)
    {
        if (files == null || files.Length == 0)
        {
            return new string[0];
        }

        uint handle;
        string key = Guid.NewGuid().ToString();
        int start = RmStartSession(out handle, 0, key);
        if (start != 0)
        {
            throw new Exception("RmStartSession failed: " + start);
        }

        try
        {
            int registered = RmRegisterResources(handle, (uint)files.Length, files, 0, null, 0, null);
            if (registered != 0)
            {
                throw new Exception("RmRegisterResources failed: " + registered);
            }

            uint needed = 0;
            uint count = 0;
            uint reasons = 0;
            const int ErrorMoreData = 234;
            int result = RmGetList(handle, out needed, ref count, null, ref reasons);
            if (result == ErrorMoreData && needed > 0)
            {
                var infos = new RM_PROCESS_INFO[needed];
                count = needed;
                result = RmGetList(handle, out needed, ref count, infos, ref reasons);
                if (result != 0)
                {
                    throw new Exception("RmGetList failed: " + result);
                }

                var list = new List<string>();
                for (int index = 0; index < count; index++)
                {
                    list.Add(
                        infos[index].Process.dwProcessId + "|" +
                        infos[index].strAppName + "|" +
                        infos[index].ApplicationType);
                }

                return list.ToArray();
            }

            if (result != 0)
            {
                throw new Exception("RmGetList failed: " + result);
            }

            return new string[0];
        }
        finally
        {
            RmEndSession(handle);
        }
    }
}
