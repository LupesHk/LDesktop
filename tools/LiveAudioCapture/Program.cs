using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using NAudio.CoreAudioApi;
using NAudio.Wave;

internal static class Program
{
    private const int ProcessBasicInformation = 0;
    private const int SampleRate = 48000;
    private const int Channels = 2;
    private const int BitsPerSample = 16;
    private const int SamplesPerChannel = 480;
    private const int FrameBytes =
        SamplesPerChannel * Channels * (BitsPerSample / 8);

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_BASIC_INFORMATION
    {
        public int ExitStatus;
        public IntPtr PebBaseAddress;
        public IntPtr AffinityMask;
        public int BasePriority;
        public IntPtr UniqueProcessId;
        public IntPtr InheritedFromUniqueProcessId;
    }

    [DllImport("ntdll.dll", ExactSpelling = true)]
    private static extern int NtQueryInformationProcess(
        IntPtr processHandle,
        int processInformationClass,
        out PROCESS_BASIC_INFORMATION processInformation,
        uint processInformationLength,
        out uint returnLength
    );

    public static async Task<int> Main(string[] args)
    {
        try
        {
            if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, 19041))
            {
                throw new PlatformNotSupportedException(
                    "A captura por processo exige Windows 10 build 19041 ou superior."
                );
            }

            if (args.Length == 1 && args[0] == "--probe-discord")
            {
                Console.WriteLine(FindDiscordRootProcess());
                return 0;
            }

            if (args.Length == 1 && args[0] == "capture")
            {
                int? discordPid = FindDiscordRootProcess(
                    allowMissing: true
                );

                Console.Error.WriteLine(
                    discordPid.HasValue
                        ? $"MODE|PROCESS_LOOPBACK_EXCLUDE_DISCORD|{discordPid.Value}"
                        : "MODE|SYSTEM_LOOPBACK"
                );

                return await CaptureAsync(discordPid);
            }

            Console.Error.WriteLine(
                "Uso: LiveAudioCapture --probe-discord | capture"
            );

            return 64;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(
                $"ERROR|{error.GetType().Name}|{error.Message}"
            );

            return 2;
        }
    }

    [SupportedOSPlatform("windows")]
    private static int GetParentProcessId(Process process)
    {
        int status = NtQueryInformationProcess(
            process.Handle,
            ProcessBasicInformation,
            out PROCESS_BASIC_INFORMATION info,
            (uint)Marshal.SizeOf<PROCESS_BASIC_INFORMATION>(),
            out _
        );

        if (status != 0)
        {
            throw new InvalidOperationException(
                $"Não foi possível identificar o processo pai de PID {process.Id}. " +
                $"NTSTATUS: 0x{status:X8}"
            );
        }

        return checked(
            (int)info.InheritedFromUniqueProcessId.ToInt64()
        );
    }

    [SupportedOSPlatform("windows10.0.19041.0")]
    private static int? FindDiscordRootProcess(bool allowMissing = false)
    {
        Process[] processes = Process.GetProcessesByName("Discord");

        if (processes.Length == 0)
        {
            if (allowMissing)
            {
                return null;
            }

            throw new InvalidOperationException(
                "Discord não está aberto."
            );
        }

        try
        {
            var ids = processes
                .Select(process => process.Id)
                .ToHashSet();

            var parents = new Dictionary<int, int>();

            foreach (Process process in processes)
            {
                parents[process.Id] = GetParentProcessId(process);
            }

            var roots = parents
                .Where(item => !ids.Contains(item.Value))
                .Select(item => item.Key)
                .ToList();

            if (roots.Count != 1)
            {
                throw new InvalidOperationException(
                    "Foram encontradas múltiplas árvores independentes do Discord. " +
                    "Para evitar transmitir áudio da chamada, feche instâncias extras. " +
                    $"Raízes encontradas: {string.Join(", ", roots)}"
                );
            }

            return roots[0];
        }
        finally
        {
            foreach (Process process in processes)
            {
                process.Dispose();
            }
        }
    }

    [SupportedOSPlatform("windows10.0.19041.0")]
    private static async Task<int> CaptureAsync(int? discordPid)
    {
        using Process? discord = discordPid.HasValue
            ? Process.GetProcessById(discordPid.Value)
            : null;

        var recorderBuilder = new WasapiRecorderBuilder();

        if (discordPid.HasValue)
        {
            // Discord aberto: captura o restante do sistema,
            // excluindo a árvore de processos do Discord.
            recorderBuilder.WithProcessLoopback(
                (uint)discordPid.Value,
                ProcessLoopbackMode.ExcludeTargetProcessTree
            );
        }
        else
        {
            // Discord fechado: captura o áudio global do dispositivo
            // de saída padrão do Windows.
            recorderBuilder.WithLoopbackCapture();
        }

        await using var recorder = await recorderBuilder
            .WithFormat(
                new WaveFormat(
                    SampleRate,
                    BitsPerSample,
                    Channels
                )
            )
            .WithBufferLength(20)
            .BuildAsync();

        Stream output = Console.OpenStandardOutput();
        object outputLock = new();
        byte[] pending = new byte[FrameBytes];
        int pendingCount = 0;

        using var stop = new CancellationTokenSource();

        recorder.DataAvailable += (
            buffer,
            flags,
            devicePosition,
            qpcPosition
        ) =>
        {
            if (stop.IsCancellationRequested)
            {
                return;
            }

            lock (outputLock)
            {
                int offset = 0;

                while (offset < buffer.Length)
                {
                    int amount = Math.Min(
                        FrameBytes - pendingCount,
                        buffer.Length - offset
                    );

                    buffer.Slice(offset, amount)
                        .CopyTo(pending.AsSpan(pendingCount));

                    offset += amount;
                    pendingCount += amount;

                    if (pendingCount == FrameBytes)
                    {
                        try
                        {
                            output.Write(
                                pending,
                                0,
                                FrameBytes
                            );

                            output.Flush();
                            pendingCount = 0;
                        }
                        catch (IOException)
                        {
                            stop.Cancel();
                            return;
                        }
                    }
                }
            }
        };

        recorder.StartRecording();

        Console.Error.WriteLine(
            $"READY|{discordPid}|{SampleRate}|{Channels}|{BitsPerSample}"
        );

        Console.Error.Flush();

        Task processExit = discord?.WaitForExitAsync()
            ?? Task.Delay(Timeout.InfiniteTimeSpan);

        Task stopRequested = Task.Delay(
            Timeout.InfiniteTimeSpan,
            stop.Token
        );

        Task shutdownSignal = Console.In.ReadLineAsync();

        await Task.WhenAny(
            processExit,
            stopRequested,
            shutdownSignal
        );

        bool discordClosed = discord is not null && processExit.IsCompleted;

        stop.Cancel();

        try
        {
            recorder.StopRecording();
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(
                $"STOP_WARNING|{error.Message}"
            );
        }

        if (discordClosed)
        {
            Console.Error.WriteLine(
                "DISCORD_EXITED|O Discord foi encerrado. Reinicie a transmissão."
            );

            return 3;
        }

        Console.Error.WriteLine("CAPTURE_STOPPED");
        return 0;
    }
}