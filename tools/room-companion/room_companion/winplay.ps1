# Play a PCM WAV on one Windows output device (picked by a word in its name), without changing the default device.
#   winplay.ps1 -List                                   active outputs: "OUT [default] Name | volume=N% mute=B"
#   winplay.ps1 -Wav C:\x\say.wav -Device Speakers -Volume 70
# -Volume N: while playing, unmute the device and raise it to at least N%, then put mute and volume back.
# Prints one line: "played device=... frames=... seconds=... peak=0.xyz volume_before=..% mute_before=.. volume_during=..%"
param([string]$Wav = "", [string]$Device = "", [int]$Volume = -1, [switch]$List)
$code = @'
using System;
using System.IO;
using System.Threading;
using System.Runtime.InteropServices;

[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
  [PreserveSig] int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
  [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint); }
[ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceCollection { [PreserveSig] int GetCount(out int count); [PreserveSig] int Item(int index, out IMMDevice device); }
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
  [PreserveSig] int Activate(ref Guid iid, int clsCtx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o);
  [PreserveSig] int OpenPropertyStore(int access, out IPropertyStore store);
  [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
  [PreserveSig] int GetState(out int state); }
[ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore { [PreserveSig] int GetCount(out int c); [PreserveSig] int GetAt(int i, out PKEY k); [PreserveSig] int GetValue(ref PKEY k, out PVAR v); }
[StructLayout(LayoutKind.Sequential)] struct PKEY { public Guid fmtid; public int pid; }
[StructLayout(LayoutKind.Sequential)] struct PVAR { public short vt; short r1, r2, r3; public IntPtr p; public IntPtr p2; }
[ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  [PreserveSig] int RegisterControlChangeNotify(IntPtr n); [PreserveSig] int UnregisterControlChangeNotify(IntPtr n); [PreserveSig] int GetChannelCount(out int c);
  [PreserveSig] int SetMasterVolumeLevel(float l, ref Guid g); [PreserveSig] int SetMasterVolumeLevelScalar(float l, ref Guid g);
  [PreserveSig] int GetMasterVolumeLevel(out float l); [PreserveSig] int GetMasterVolumeLevelScalar(out float l);
  [PreserveSig] int SetChannelVolumeLevel(int c, float l, ref Guid g); [PreserveSig] int SetChannelVolumeLevelScalar(int c, float l, ref Guid g);
  [PreserveSig] int GetChannelVolumeLevel(int c, out float l); [PreserveSig] int GetChannelVolumeLevelScalar(int c, out float l);
  [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool m, ref Guid g); [PreserveSig] int GetMute([MarshalAs(UnmanagedType.Bool)] out bool m); }
[ComImport, Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioClient {
  [PreserveSig] int Initialize(int shareMode, uint streamFlags, long bufferDuration, long periodicity, IntPtr format, IntPtr sessionGuid);
  [PreserveSig] int GetBufferSize(out uint frames);
  [PreserveSig] int GetStreamLatency(out long latency);
  [PreserveSig] int GetCurrentPadding(out uint frames);
  [PreserveSig] int IsFormatSupported(int shareMode, IntPtr format, out IntPtr closest);
  [PreserveSig] int GetMixFormat(out IntPtr format);
  [PreserveSig] int GetDevicePeriod(out long def, out long min);
  [PreserveSig] int Start();
  [PreserveSig] int Stop();
  [PreserveSig] int Reset();
  [PreserveSig] int SetEventHandle(IntPtr h);
  [PreserveSig] int GetService(ref Guid iid, [MarshalAs(UnmanagedType.IUnknown)] out object svc); }
[ComImport, Guid("F294ACFC-3146-4483-A7BF-ADDCA7C260E2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioRenderClient { [PreserveSig] int GetBuffer(uint frames, out IntPtr data); [PreserveSig] int ReleaseBuffer(uint frames, uint flags); }
[ComImport, Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioMeterInformation { [PreserveSig] int GetPeakValue(out float peak); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {}

public static class WinPlay {
  static void Ok(int hr, string what) { if (hr != 0) throw new Exception(what + " failed: 0x" + hr.ToString("X8")); }
  static string Name(IMMDevice d) {
    IPropertyStore s; Ok(d.OpenPropertyStore(0, out s), "OpenPropertyStore");
    var k = new PKEY { fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"), pid = 14 }; PVAR v; Ok(s.GetValue(ref k, out v), "GetValue");
    return Marshal.PtrToStringUni(v.p); }
  static T Act<T>(IMMDevice d) { var iid = typeof(T).GUID; object o; Ok(d.Activate(ref iid, 23, IntPtr.Zero, out o), "Activate " + typeof(T).Name); return (T)o; }
  static string Vol(IMMDevice d) { var ev = Act<IAudioEndpointVolume>(d); float l; bool m; ev.GetMasterVolumeLevelScalar(out l); ev.GetMute(out m);
    return "volume=" + Math.Round(l * 100) + "% mute=" + m; }
  public static string List() {
    var e = (IMMDeviceEnumerator)new MMDeviceEnumerator(); var sb = new System.Text.StringBuilder();
    IMMDevice def; string defId = "";
    if (e.GetDefaultAudioEndpoint(0, 1, out def) == 0) def.GetId(out defId);
    IMMDeviceCollection c; Ok(e.EnumAudioEndpoints(0, 1, out c), "EnumAudioEndpoints"); int n; c.GetCount(out n);
    for (int i = 0; i < n; i++) { IMMDevice d; c.Item(i, out d); string id; d.GetId(out id);
      sb.AppendLine("OUT " + (id == defId ? "[default] " : "          ") + Name(d) + " | " + Vol(d)); }
    return sb.ToString(); }
  static IMMDevice Find(string want, out string name) {
    var e = (IMMDeviceEnumerator)new MMDeviceEnumerator();
    if (string.IsNullOrEmpty(want)) { IMMDevice def; Ok(e.GetDefaultAudioEndpoint(0, 1, out def), "GetDefaultAudioEndpoint"); name = Name(def); return def; }
    IMMDeviceCollection c; Ok(e.EnumAudioEndpoints(0, 1, out c), "EnumAudioEndpoints"); int n; c.GetCount(out n);
    for (int i = 0; i < n; i++) { IMMDevice d; c.Item(i, out d); string nm = Name(d);
      if (nm.IndexOf(want, StringComparison.OrdinalIgnoreCase) >= 0) { name = nm; return d; } }
    name = null; return null; }
  public static string Play(string wav, string want, int volume) {
    byte[] all = File.ReadAllBytes(wav);
    int ch = 0, rate = 0, bits = 0, dataOff = -1, dataLen = 0, p = 12;
    while (p + 8 <= all.Length) {
      string id = System.Text.Encoding.ASCII.GetString(all, p, 4); int len = BitConverter.ToInt32(all, p + 4);
      if (id == "fmt ") { ch = BitConverter.ToInt16(all, p + 10); rate = BitConverter.ToInt32(all, p + 12); bits = BitConverter.ToInt16(all, p + 22); }
      if (id == "data") { dataOff = p + 8; dataLen = Math.Min(len, all.Length - dataOff); break; }
      p += 8 + len + (len & 1); }
    if (dataOff < 0 || bits != 16) throw new Exception("not a 16-bit PCM wav");
    string name; IMMDevice d = Find(want, out name);
    if (d == null) throw new Exception("no active output matching '" + want + "'");
    var ev = Act<IAudioEndpointVolume>(d); var g = Guid.Empty;
    float lvl0; bool mute0; ev.GetMasterVolumeLevelScalar(out lvl0); ev.GetMute(out mute0);
    bool changed = false;
    if (volume >= 0) {
      if (mute0) { Ok(ev.SetMute(false, ref g), "SetMute"); changed = true; }
      if (lvl0 * 100 < volume - 0.5) { Ok(ev.SetMasterVolumeLevelScalar(volume / 100f, ref g), "SetVolume"); changed = true; } }
    float lvlDuring; ev.GetMasterVolumeLevelScalar(out lvlDuring);
    float peak = 0; int frameBytes = ch * bits / 8; int total = dataLen / frameBytes;
    IntPtr fmt = Marshal.AllocHGlobal(18);
    try {
      var ac = Act<IAudioClient>(d);
      Marshal.WriteInt16(fmt, 0, 1); Marshal.WriteInt16(fmt, 2, (short)ch); Marshal.WriteInt32(fmt, 4, rate);
      Marshal.WriteInt32(fmt, 8, rate * frameBytes); Marshal.WriteInt16(fmt, 12, (short)frameBytes); Marshal.WriteInt16(fmt, 14, (short)bits); Marshal.WriteInt16(fmt, 16, 0);
      // shared mode; let Windows convert our PCM to the device format
      Ok(ac.Initialize(0, 0x80000000u | 0x08000000u, 10000000, 0, fmt, IntPtr.Zero), "Initialize");
      uint buf; Ok(ac.GetBufferSize(out buf), "GetBufferSize");
      var rid = typeof(IAudioRenderClient).GUID; object ro; Ok(ac.GetService(ref rid, out ro), "GetService"); var rc = (IAudioRenderClient)ro;
      var meter = Act<IAudioMeterInformation>(d);
      int pos = 0; bool started = false;
      while (pos < total) {
        uint pad; Ok(ac.GetCurrentPadding(out pad), "GetCurrentPadding");
        int k = Math.Min((int)(buf - pad), total - pos);
        if (k > 0) { IntPtr dst; Ok(rc.GetBuffer((uint)k, out dst), "GetBuffer"); Marshal.Copy(all, dataOff + pos * frameBytes, dst, k * frameBytes); Ok(rc.ReleaseBuffer((uint)k, 0), "ReleaseBuffer"); pos += k; }
        if (!started) { Ok(ac.Start(), "Start"); started = true; }
        float pk; meter.GetPeakValue(out pk); if (pk > peak) peak = pk;
        Thread.Sleep(15); }
      var end = DateTime.UtcNow.AddSeconds(3);
      while (DateTime.UtcNow < end) { uint pad; ac.GetCurrentPadding(out pad); float pk; meter.GetPeakValue(out pk); if (pk > peak) peak = pk; if (pad == 0) break; Thread.Sleep(15); }
      Thread.Sleep(80);
      ac.Stop();
    } finally {
      Marshal.FreeHGlobal(fmt);
      if (changed) { ev.SetMasterVolumeLevelScalar(lvl0, ref g); ev.SetMute(mute0, ref g); } }
    return "played device=" + name + " | frames=" + total + " seconds=" + Math.Round((double)total / rate, 2) + " peak=" + peak.ToString("0.000")
      + " volume_before=" + Math.Round(lvl0 * 100) + "% mute_before=" + mute0 + " volume_during=" + Math.Round(lvlDuring * 100) + "%"; }
}
'@
# Compile once into a DLL next to this script; recompile when the script changes.
$dll = Join-Path $PSScriptRoot ("winplay-" + (Get-FileHash -Algorithm SHA256 $PSCommandPath).Hash.Substring(0, 12) + ".dll")
if (-not (Test-Path $dll)) {
  Get-ChildItem (Join-Path $PSScriptRoot "winplay-*.dll") -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue
  Add-Type -TypeDefinition $code -OutputAssembly $dll -OutputType Library }
Add-Type -Path $dll
try {
  if ($List) { [WinPlay]::List() } elseif ($Wav) { [WinPlay]::Play($Wav, $Device, $Volume) } else { "usage: -List | -Wav file [-Device word] [-Volume N]" }
} catch { "error " + $_.Exception.InnerException.Message + $_.Exception.Message; exit 1 }
