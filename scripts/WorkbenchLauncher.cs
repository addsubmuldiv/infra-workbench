using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Windows.Forms;

[assembly: AssemblyTitle("Infra Workbench")]
[assembly: AssemblyDescription("Infra Workbench unified graphical launcher")]
[assembly: AssemblyProduct("Infra Workbench")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class WorkbenchLauncher {
    static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }
    static bool Installed(string root) {
        string stamp = Path.Combine(root, ".venv", ".iwb-requirements.sha256");
        if (!File.Exists(Path.Combine(root, ".venv", "Scripts", "pythonw.exe")) ||
            !File.Exists(stamp) || !File.Exists(Path.Combine(root,"frontend","dist","index.html"))) return false;
        using (var hash = SHA256.Create()) {
            string expected = BitConverter.ToString(hash.ComputeHash(File.ReadAllBytes(Path.Combine(root,"requirements.txt")))).Replace("-", "");
            return String.Equals(expected, File.ReadAllText(stamp).Trim(), StringComparison.OrdinalIgnoreCase);
        }
    }
    [STAThread]
    static int Main() {
        string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        try {
            if (!File.Exists(Path.Combine(root,"backend","launcher.py"))) throw new Exception("项目文件不完整，请将启动程序保留在 Infra Workbench 文件夹内。");
            if (!Installed(root)) {
                var install = new ProcessStartInfo {
                    FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe"),
                    Arguments = "-NoProfile -ExecutionPolicy Bypass -File " + Quote(Path.Combine(root,"install.ps1")) + " -NoLaunch -InstallPython -SkipLauncherBuild",
                    WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = false, WindowStyle = ProcessWindowStyle.Normal
                };
                using (var process = Process.Start(install)) {
                    process.WaitForExit();
                    if (process.ExitCode != 0 || !Installed(root)) throw new Exception("依赖安装未完成。请检查安装窗口中的错误，修复后再次打开。");
                }
            }
            var launch = new ProcessStartInfo {
                FileName = Path.Combine(root,".venv","Scripts","pythonw.exe"), Arguments = "-m backend.launcher",
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
            };
            if (String.IsNullOrEmpty(Environment.GetEnvironmentVariable("IWB_DATA"))) launch.EnvironmentVariables["IWB_DATA"] = Path.Combine(root,"data");
            using (var process = Process.Start(launch)) {
                if (!process.WaitForExit(100000)) throw new Exception("启动仍未完成，请查看数据目录中的 launch.log 和 desktop.log。");
                if (process.ExitCode != 0) throw new Exception("无法启动工作台。请查看数据目录中的 launch.log；未停止其他程序。");
            }
            return 0;
        } catch (Exception error) {
            MessageBox.Show(error.Message,"Infra Workbench",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
